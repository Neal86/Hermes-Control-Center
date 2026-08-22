from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None

_INSTALLED = False
_CONFIG_CHANGED = False


def _root_hermes_home() -> Path:
    raw = str(os.environ.get("HERMES_HOME") or "").strip()
    if raw:
        home = Path(raw).expanduser().resolve()
    elif os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        home = (Path(os.environ["LOCALAPPDATA"]) / "hermes").resolve()
    else:
        home = (Path.home() / ".hermes").resolve()
    parts = [part.lower() for part in home.parts]
    if "profiles" in parts:
        index = len(parts) - 1 - parts[::-1].index("profiles")
        if index >= 1:
            return Path(*home.parts[:index]).resolve()
    return home


def _persist_independent_gateway_config(root: Path) -> bool:
    """Persist gateway.multiplex_profiles=false without touching other settings."""
    if yaml is None:
        return False
    path = root / "config.yaml"
    try:
        payload: dict[str, Any] = {}
        if path.exists():
            parsed = yaml.safe_load(path.read_text("utf-8"))
            if isinstance(parsed, dict):
                payload = parsed
        gateway = payload.get("gateway")
        if not isinstance(gateway, dict):
            gateway = {}
            payload["gateway"] = gateway
        if gateway.get("multiplex_profiles") is False:
            return False
        gateway["multiplex_profiles"] = False
        root.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix="config.gateway-isolation.", suffix=".yaml", dir=str(root))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)
            Path(temp_name).replace(path)
        finally:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass
        return True
    except Exception:
        # Gateway isolation is also enforced in-memory below. A read-only config
        # must not prevent the plugin from loading.
        return False


def install_independent_gateway_policy() -> None:
    """Make Control Center Agents use one real Gateway process per profile.

    The previous management layer deliberately treated non-default profiles as
    clients of the default Gateway when gateway.multiplex_profiles was enabled.
    That is incompatible with per-Agent WeChat HWND ownership: two Agents can
    otherwise execute in one process and resolve the wrong desktop resource.

    This installer does three things:
      1. persists multiplex_profiles=false for subsequent Gateway launches;
      2. makes ManagementCenter always start/status/stop the requested profile;
      3. injects HERMES_PROFILE into every profile command so plugin resource
         resolution is pinned to the exact Agent even though HERMES_HOME stays at
         the shared root.
    """
    global _INSTALLED, _CONFIG_CHANGED
    if _INSTALLED:
        return

    root = _root_hermes_home()
    _CONFIG_CHANGED = _persist_independent_gateway_config(root)

    from .management.service import ManagementCenter

    original_action = ManagementCenter.agent_action

    def independent_env_for(self: ManagementCenter, name: str | None) -> dict[str, str]:
        profile = self._normalize_profile(name)
        self._profile_home(profile)
        env = self.cli.profile_env(self.root)
        env["HERMES_PROFILE"] = profile
        env["HERMES_PROFILE_NAME"] = profile
        # Also expose the policy explicitly for future Hermes versions that elect
        # to honor an environment override.
        env["HERMES_GATEWAY_MULTIPLEX_PROFILES"] = "0"
        return env

    def never_multiplex(self: ManagementCenter) -> bool:
        return False

    def independent_agent_action(
        self: ManagementCenter,
        name: str,
        action: str,
        value: str | None = None,
    ) -> dict[str, Any]:
        global _CONFIG_CHANGED
        profile = self._normalize_profile(name)
        normalized_action = str(action or "").strip().lower()

        # If this dashboard process is the one that changed the persisted config,
        # the already-running default Gateway may still have loaded the old
        # multiplex setting. Restart it once before the first non-default Gateway
        # starts so there is no overlap window where both processes service the
        # same profile.
        if (
            _CONFIG_CHANGED
            and profile != "default"
            and normalized_action in {"gateway_start", "gateway_restart"}
        ):
            try:
                if self._normalized_gateway_state("default") == "running":
                    self.cli.run_text(
                        self._profile_cli("default", "gateway", "restart"),
                        env=self._env_for("default"),
                        timeout=90,
                    )
                    self._verify_gateway_transition("default", expected_running=True, timeout=15.0)
            finally:
                # Never restart the default Gateway repeatedly from later clicks.
                _CONFIG_CHANGED = False

        return original_action(self, profile, normalized_action, value)

    ManagementCenter._env_for = independent_env_for
    ManagementCenter._gateway_multiplexes_profiles = never_multiplex
    ManagementCenter.agent_action = independent_agent_action
    _INSTALLED = True

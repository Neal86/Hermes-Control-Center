from __future__ import annotations

import os
import shutil
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
        return False


def _sync_enabled_user_plugins(root: Path, profile_home: Path) -> list[str]:
    """Mirror enabled root user plugins into an isolated profile home.

    Hermes scopes user-plugin discovery to the active profile home. A profile
    gateway therefore cannot load root-installed plugins merely because their
    names are present in the profile config. Refresh only explicitly enabled
    root user plugins immediately before that profile gateway starts.
    """
    if yaml is None:
        return []
    config_path = profile_home / "config.yaml"
    if not config_path.is_file():
        return []
    try:
        payload = yaml.safe_load(config_path.read_text("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Unable to read profile plugin config: {config_path}: {exc}") from exc
    plugins = payload.get("plugins") if isinstance(payload, dict) else None
    enabled = plugins.get("enabled") if isinstance(plugins, dict) else None
    if not isinstance(enabled, list):
        return []

    source_root = root / "plugins"
    target_root = profile_home / "plugins"
    copied: list[str] = []
    for raw_name in enabled:
        name = str(raw_name or "").strip()
        if not name or "/" in name or chr(92) in name or Path(name).name != name:
            continue
        # replaced invalid separator check
        # \"\\\")):
            continue
        source = source_root / name
        if not source.is_dir():
            continue
        target_root.mkdir(parents=True, exist_ok=True)
        target = target_root / name
        try:
            shutil.copytree(source, target, dirs_exist_ok=True)
        except OSError as exc:
            raise RuntimeError(f"Unable to inherit enabled user plugin '{name}' into profile '{profile_home.name}': {exc}") from exc
        copied.append(name)
    return copied


def _management_center_class():
    try:  # normal package import when loaded by Hermes
        from ..management.service import ManagementCenter
    except (ImportError, ValueError):  # direct source/test import
        from management.service import ManagementCenter
    return ManagementCenter


def install_independent_gateway_policy(management_center_class=None) -> None:
    """Make every Control Center Agent use its own real Gateway profile."""
    global _INSTALLED, _CONFIG_CHANGED

    root = _root_hermes_home()
    config_changed = _persist_independent_gateway_config(root)
    _CONFIG_CHANGED = _CONFIG_CHANGED or config_changed
    ManagementCenter = management_center_class or _management_center_class()
    if getattr(ManagementCenter, "_hcc_independent_gateway_policy_installed", False):
        return
    original_action = ManagementCenter.agent_action

    def independent_env_for(self, name: str | None) -> dict[str, str]:
        profile = self._normalize_profile(name)
        self._profile_home(profile)
        env = self.cli.profile_env(self.root)
        env["HERMES_PROFILE"] = profile
        env["HERMES_PROFILE_NAME"] = profile
        env["HERMES_GATEWAY_MULTIPLEX_PROFILES"] = "0"
        return env

    def never_multiplex(self) -> bool:
        return False

    def independent_agent_action(
        self,
        name: str,
        action: str,
        value: str | None = None,
    ) -> dict[str, Any]:
        global _CONFIG_CHANGED
        profile = self._normalize_profile(name)
        normalized_action = str(action or "").strip().lower()
        if profile != "default" and normalized_action in {"gateway_start", "gateway_restart"}:
            _sync_enabled_user_plugins(root, self._profile_home(profile))
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
                _CONFIG_CHANGED = False
        return original_action(self, profile, normalized_action, value)

    ManagementCenter._env_for = independent_env_for
    ManagementCenter._gateway_multiplexes_profiles = never_multiplex
    ManagementCenter.agent_action = independent_agent_action
    ManagementCenter._hcc_independent_gateway_policy_installed = True
    _INSTALLED = True

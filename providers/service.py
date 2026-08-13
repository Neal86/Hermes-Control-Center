from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml

try:
    from hermes_constants import get_hermes_home
except Exception:
    get_hermes_home = None

_PROVIDER_ENV = {
    "openai-api": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "xai": "XAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "together": "TOGETHER_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "kimi-coding": "KIMI_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "opencode-zen": "OPENCODE_ZEN_API_KEY",
    "opencode-go": "OPENCODE_GO_API_KEY",
    "custom": "HERMES_CUSTOM_PROVIDER_API_KEY",
}

_PROVIDER_LABELS = {
    "openai-api": "OpenAI API (direct)",
    "openrouter": "OpenRouter",
    "anthropic": "Anthropic / Claude",
    "gemini": "Google Gemini",
    "deepseek": "DeepSeek",
    "xai": "xAI Grok",
    "groq": "Groq",
    "together": "Together AI",
    "mistral": "Mistral",
    "kimi-coding": "Kimi / Moonshot",
    "minimax": "MiniMax",
    "opencode-zen": "OpenCode Zen",
    "opencode-go": "OpenCode Go",
    "custom": "Custom OpenAI-compatible Provider",
    "nous": "Nous Portal OAuth",
}

_CUSTOM_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


def _default_hermes_home() -> Path:
    explicit = str(os.environ.get("HERMES_HOME") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    if get_hermes_home is not None:
        try:
            return Path(get_hermes_home()).expanduser()
        except Exception:
            pass
    local = str(os.environ.get("LOCALAPPDATA") or "").strip()
    if local:
        candidate = Path(local) / "hermes"
        if candidate.exists():
            return candidate
    return Path.home() / ".hermes"


def _provider_slug(name: str) -> str:
    slug = _CUSTOM_SLUG_RE.sub("-", str(name or "").strip().lower()).strip("-_")
    if not slug:
        return ""
    if slug in {"auto", "custom", "none"} or slug in _PROVIDER_LABELS:
        slug = f"custom-{slug}"
    return slug[:96]


class ProviderService:
    """Profile-aware provider settings without exposing stored secrets.

    Built-in provider secrets live in the profile .env. A custom endpoint is
    mirrored into Hermes' canonical ``providers:`` config section and uses
    ``key_env`` so the secret itself never needs to be written into config.yaml.
    """

    def __init__(self, hermes_home: Path | None = None) -> None:
        self.hermes_home = (hermes_home or _default_hermes_home()).expanduser().resolve()
        self.data_root = self.hermes_home / "plugin-data" / "hermes-extensions" / "providers"
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.path = self.data_root / "providers.json"

    def _profile_home(self, profile: str, *, require_exists: bool = False) -> Path:
        name = str(profile or "default").strip().lower() or "default"
        if name == "default":
            return self.hermes_home
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name):
            raise ValueError("invalid profile")
        profiles_root = (self.hermes_home / "profiles").resolve()
        home = (profiles_root / name).resolve()
        if home.parent != profiles_root:
            raise ValueError("invalid profile")
        if require_exists and not home.is_dir():
            raise ValueError(f"unknown Hermes profile: {name}")
        return home

    def catalog(self) -> list[dict[str, Any]]:
        rows = []
        for provider, label in _PROVIDER_LABELS.items():
            rows.append({
                "id": provider,
                "runtime_provider_id": provider if provider != "custom" else "",
                "label": label,
                "auth": "oauth" if provider == "nous" else "api_key",
                "supports_base_url": provider in {"openai-api", "openrouter", "custom"},
                "supports_custom_name": provider == "custom",
                "env_key": _PROVIDER_ENV.get(provider),
            })
        return rows

    def _read_meta(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text("utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_meta(self, payload: dict[str, Any]) -> None:
        fd, tmp = tempfile.mkstemp(prefix="providers.", suffix=".json", dir=str(self.data_root))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            Path(tmp).replace(self.path)
        finally:
            try:
                Path(tmp).unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _parse_env(path: Path) -> dict[str, str]:
        result: dict[str, str] = {}
        try:
            lines = path.read_text("utf-8").splitlines()
        except OSError:
            return result
        for line in lines:
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            result[key.strip()] = value.strip().strip('"').strip("'")
        return result

    @staticmethod
    def _quote_env(value: str) -> str:
        return json.dumps(str(value), ensure_ascii=False)

    def _update_env(self, profile: str, updates: dict[str, str | None]) -> None:
        home = self._profile_home(profile, require_exists=True)
        path = home / ".env"
        try:
            current_lines = path.read_text("utf-8").splitlines()
        except OSError:
            current_lines = []
        wanted = set(updates)
        output: list[str] = []
        seen: set[str] = set()
        for line in current_lines:
            stripped = line.strip()
            key = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else ""
            if key in wanted:
                seen.add(key)
                value = updates[key]
                if value is not None and str(value) != "":
                    output.append(f"{key}={self._quote_env(str(value))}")
                continue
            output.append(line)
        for key, value in updates.items():
            if key in seen or value is None or str(value) == "":
                continue
            output.append(f"{key}={self._quote_env(str(value))}")
        text = "\n".join(output).rstrip() + ("\n" if output else "")
        fd, tmp = tempfile.mkstemp(prefix="env.", suffix=".tmp", dir=str(home))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            Path(tmp).replace(path)
        finally:
            try:
                Path(tmp).unlink(missing_ok=True)
            except OSError:
                pass

    def _read_config(self, profile: str) -> dict[str, Any]:
        path = self._profile_home(profile, require_exists=True) / "config.yaml"
        try:
            value = yaml.safe_load(path.read_text("utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, yaml.YAMLError):
            return {}

    def _write_config(self, profile: str, config: dict[str, Any]) -> None:
        home = self._profile_home(profile, require_exists=True)
        path = home / "config.yaml"
        fd, tmp = tempfile.mkstemp(prefix="config.", suffix=".yaml.tmp", dir=str(home))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                yaml.safe_dump(config, handle, sort_keys=False, allow_unicode=True)
            Path(tmp).replace(path)
        finally:
            try:
                Path(tmp).unlink(missing_ok=True)
            except OSError:
                pass

    def _sync_custom_runtime_provider(
        self,
        profile: str,
        current: dict[str, Any],
        previous_runtime_id: str = "",
    ) -> str:
        name = str(current.get("custom_name") or "").strip()
        base_url = str(current.get("base_url") or "").strip()
        model = str(current.get("default_model") or "").strip()
        runtime_id = _provider_slug(name)
        config = self._read_config(profile)
        providers = config.get("providers")
        if not isinstance(providers, dict):
            providers = {}
            config["providers"] = providers

        old_id = str(previous_runtime_id or current.get("runtime_provider_id") or "").strip()
        if old_id and old_id != runtime_id:
            old_entry = providers.get(old_id)
            if isinstance(old_entry, dict) and old_entry.get("key_env") == _PROVIDER_ENV["custom"]:
                providers.pop(old_id, None)

        if runtime_id and base_url:
            existing = providers.get(runtime_id)
            entry = dict(existing) if isinstance(existing, dict) else {}
            entry.update({
                "name": name or runtime_id,
                "api": base_url,
                "key_env": _PROVIDER_ENV["custom"],
                "transport": "openai_chat",
            })
            if model:
                entry["models"] = [model]
            elif "models" in entry:
                entry.pop("models", None)
            entry.setdefault("discover_models", True)
            providers[runtime_id] = entry
        elif old_id:
            old_entry = providers.get(old_id)
            if isinstance(old_entry, dict) and old_entry.get("key_env") == _PROVIDER_ENV["custom"]:
                providers.pop(old_id, None)

        self._write_config(profile, config)
        return runtime_id

    def list(self, profile: str = "default") -> list[dict[str, Any]]:
        normalized_profile = str(profile or "default").strip().lower() or "default"
        home = self._profile_home(normalized_profile, require_exists=True)
        env = self._parse_env(home / ".env")
        meta = self._read_meta().get(normalized_profile, {})
        rows = []
        for item in self.catalog():
            provider = item["id"]
            env_key = item.get("env_key")
            stored = meta.get(provider, {}) if isinstance(meta, dict) else {}
            custom_name = str(stored.get("custom_name") or "")
            runtime_id = (
                str(stored.get("runtime_provider_id") or _provider_slug(custom_name) or "")
                if provider == "custom"
                else provider
            )
            label = (custom_name or item["label"]) if provider == "custom" else item["label"]
            has_key = bool(env_key and env.get(str(env_key)))
            base_url = str(stored.get("base_url") or "")
            configured = (
                bool(runtime_id and base_url and has_key)
                if provider == "custom"
                else has_key or bool(stored.get("configured"))
            )
            rows.append({
                **item,
                "label": label,
                "custom_name": custom_name,
                "runtime_provider_id": runtime_id,
                "configured": configured,
                "has_api_key": has_key,
                "base_url": base_url,
                "default_model": str(stored.get("default_model") or ""),
                "oauth_status": str(stored.get("oauth_status") or "not_checked") if item["auth"] == "oauth" else None,
            })
        return rows

    def save(self, profile: str, provider: str, data: dict[str, Any]) -> dict[str, Any]:
        provider = str(provider or "").strip().lower()
        if provider not in _PROVIDER_LABELS:
            raise ValueError("unsupported provider")
        profile = str(profile or "default").strip().lower() or "default"
        self._profile_home(profile, require_exists=True)
        env_key = _PROVIDER_ENV.get(provider)
        api_key = data.get("api_key")
        clear_key = bool(data.get("clear_api_key"))
        if env_key:
            if clear_key:
                self._update_env(profile, {env_key: None})
            elif api_key is not None and str(api_key).strip():
                self._update_env(profile, {env_key: str(api_key).strip()})

        payload = self._read_meta()
        by_profile = payload.setdefault(profile, {})
        if not isinstance(by_profile, dict):
            by_profile = {}
            payload[profile] = by_profile
        current = by_profile.setdefault(provider, {})
        if not isinstance(current, dict):
            current = {}
            by_profile[provider] = current
        previous_runtime_id = str(current.get("runtime_provider_id") or "")
        for key in ("base_url", "default_model"):
            if key in data:
                current[key] = str(data.get(key) or "").strip()
        if provider == "custom" and "custom_name" in data:
            current["custom_name"] = str(data.get("custom_name") or "").strip()[:128]

        if provider == "custom":
            current["runtime_provider_id"] = self._sync_custom_runtime_provider(profile, current, previous_runtime_id)
        if provider == "nous":
            current["configured"] = bool(data.get("configured", current.get("configured", False)))
            current["oauth_status"] = str(data.get("oauth_status") or current.get("oauth_status") or "external_login_required")
        elif env_key:
            current["configured"] = bool(self._parse_env(self._profile_home(profile, require_exists=True) / ".env").get(env_key))
        else:
            current["configured"] = bool(current.get("base_url"))
        self._write_meta(payload)
        return next(row for row in self.list(profile) if row["id"] == provider)

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

_PROVIDER_ENV = {
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "google": "GEMINI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "xai": "XAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "together": "TOGETHER_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
    "kimi": "MOONSHOT_API_KEY",
    "minimax": "MINIMAX_API_KEY",
}

_PROVIDER_LABELS = {
    "openai": "OpenAI",
    "openrouter": "OpenRouter",
    "anthropic": "Anthropic / Claude",
    "google": "Google Gemini",
    "deepseek": "DeepSeek",
    "xai": "xAI Grok",
    "groq": "Groq",
    "together": "Together AI",
    "mistral": "Mistral",
    "moonshot": "Kimi / Moonshot",
    "minimax": "MiniMax",
    "custom": "Custom OpenAI-compatible endpoint",
    "nous": "Nous Portal OAuth",
    "opencode": "OpenCode",
}


class ProviderService:
    """Profile-aware provider settings managed without exposing stored secrets.

    API keys are written to the selected Hermes profile's .env so Hermes itself
    consumes them. Non-secret endpoint metadata is also mirrored in plugin data
    for the Control Center UI. OAuth-only providers are represented as external
    authentication modes and never fake a successful login.
    """

    def __init__(self, hermes_home: Path | None = None) -> None:
        self.hermes_home = (hermes_home or Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")).expanduser().resolve()
        self.data_root = self.hermes_home / "plugin-data" / "hermes-extensions" / "providers"
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.path = self.data_root / "providers.json"

    def _profile_home(self, profile: str) -> Path:
        name = str(profile or "default").strip().lower()
        if name == "default":
            home = self.hermes_home
        else:
            home = (self.hermes_home / "profiles" / name).resolve()
            profiles_root = (self.hermes_home / "profiles").resolve()
            if profiles_root not in home.parents:
                raise ValueError("invalid profile")
        home.mkdir(parents=True, exist_ok=True)
        return home

    def catalog(self) -> list[dict[str, Any]]:
        rows = []
        for provider, label in _PROVIDER_LABELS.items():
            rows.append({
                "id": provider,
                "label": label,
                "auth": "oauth" if provider in {"nous", "opencode"} else "api_key",
                "supports_base_url": provider in {"openai", "openrouter", "custom"},
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
        home = self._profile_home(profile)
        path = home / ".env"
        current_lines: list[str] = []
        try:
            current_lines = path.read_text("utf-8").splitlines()
        except OSError:
            pass
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

    def list(self, profile: str = "default") -> list[dict[str, Any]]:
        home = self._profile_home(profile)
        env = self._parse_env(home / ".env")
        meta = self._read_meta().get(profile, {})
        rows = []
        for item in self.catalog():
            provider = item["id"]
            env_key = item.get("env_key")
            stored = meta.get(provider, {}) if isinstance(meta, dict) else {}
            rows.append({
                **item,
                "configured": bool(env_key and env.get(str(env_key))) or bool(stored.get("configured")),
                "has_api_key": bool(env_key and env.get(str(env_key))),
                "base_url": str(stored.get("base_url") or ""),
                "default_model": str(stored.get("default_model") or ""),
                "oauth_status": str(stored.get("oauth_status") or "not_checked") if item["auth"] == "oauth" else None,
            })
        return rows

    def save(self, profile: str, provider: str, data: dict[str, Any]) -> dict[str, Any]:
        provider = str(provider or "").strip().lower()
        if provider not in _PROVIDER_LABELS:
            raise ValueError("unsupported provider")
        profile = str(profile or "default").strip().lower()
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
        current = by_profile.setdefault(provider, {})
        for key in ("base_url", "default_model"):
            if key in data:
                current[key] = str(data.get(key) or "").strip()
        if provider in {"nous", "opencode"}:
            current["configured"] = bool(data.get("configured", current.get("configured", False)))
            current["oauth_status"] = str(data.get("oauth_status") or current.get("oauth_status") or "external_login_required")
        elif env_key:
            current["configured"] = bool(self._parse_env(self._profile_home(profile) / ".env").get(env_key))
        else:
            current["configured"] = bool(current.get("base_url"))
        self._write_meta(payload)
        return next(row for row in self.list(profile) if row["id"] == provider)

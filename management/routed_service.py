from __future__ import annotations

from typing import Any

from hermes_cli.providers import determine_api_mode, resolve_provider_full

from .service import ManagementCenter as _BaseManagementCenter, _safe_yaml


class ManagementCenter(_BaseManagementCenter):
    """ManagementCenter that persists a complete Hermes model route."""

    def _unset_config(self, profile: str, key: str) -> None:
        self.cli.run_text(
            self._profile_cli(profile, "config", "unset", key),
            env=self._env_for(profile),
        )

    def _sync_agent_route(self, profile: str, args: dict[str, Any]) -> None:
        if "provider" not in args and "model" not in args:
            return
        home = self._profile_home(profile)
        config = _safe_yaml(home / "config.yaml")
        model_cfg = config.get("model") if isinstance(config.get("model"), dict) else {}
        provider = str(args.get("provider") if args.get("provider") is not None else model_cfg.get("provider") or "").strip()
        model = str(args.get("model") if args.get("model") is not None else model_cfg.get("default") or "").strip()
        if not provider:
            raise ValueError("model.provider cannot be empty")
        if not model:
            raise ValueError("model.default cannot be empty")

        user_providers = config.get("providers") if isinstance(config.get("providers"), dict) else {}
        custom_providers = config.get("custom_providers") if isinstance(config.get("custom_providers"), list) else []
        pdef = resolve_provider_full(provider, user_providers=user_providers, custom_providers=custom_providers)
        if pdef is None:
            raise ValueError(f"unknown Hermes provider: {provider}")
        base_url = str(getattr(pdef, "base_url", "") or "").strip()
        api_mode = determine_api_mode(provider, base_url=base_url, model=model)

        self._set_config(profile, "model.provider", provider)
        self._set_config(profile, "model.default", model)
        if base_url:
            self._set_config(profile, "model.base_url", base_url)
        else:
            self._unset_config(profile, "model.base_url")
        if api_mode:
            self._set_config(profile, "model.api_mode", api_mode)
        else:
            self._unset_config(profile, "model.api_mode")

    def agent_create(self, args: dict[str, Any]) -> dict[str, Any]:
        result = super().agent_create(args)
        agent = result.get("agent") if isinstance(result, dict) else None
        name = str((agent or {}).get("name") or args.get("name") or "").strip().lower()
        if name:
            self._sync_agent_route(name, args)
            result["agent"] = self.agent_get(name)
        return result

    def agent_update(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        result = super().agent_update(name, args)
        agent = result.get("agent") if isinstance(result, dict) else None
        final_name = str((agent or {}).get("name") or args.get("name") or name).strip().lower()
        if final_name:
            self._sync_agent_route(final_name, args)
            result["agent"] = self.agent_get(final_name)
        return result

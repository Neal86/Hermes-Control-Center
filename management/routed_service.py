from __future__ import annotations

from typing import Any

from hermes_cli.providers import determine_api_mode, resolve_provider_full

from .service import ManagementCenter as _BaseManagementCenter, _safe_yaml


class ManagementCenter(_BaseManagementCenter):
    """ManagementCenter that validates and persists a complete Hermes model route."""

    def _unset_config(self, profile: str, key: str) -> None:
        self.cli.run_text(
            self._profile_cli(profile, "config", "unset", key),
            env=self._env_for(profile),
        )

    def _resolve_agent_route(self, profile: str, args: dict[str, Any]) -> dict[str, str] | None:
        if "provider" not in args and "model" not in args:
            return None
        home = self._profile_home(profile)
        config = _safe_yaml(home / "config.yaml")
        model_cfg = config.get("model") if isinstance(config.get("model"), dict) else {}
        provider = str(
            args.get("provider") if args.get("provider") is not None else model_cfg.get("provider") or ""
        ).strip()
        model = str(
            args.get("model") if args.get("model") is not None else model_cfg.get("default") or ""
        ).strip()
        if not provider:
            raise ValueError("model.provider cannot be empty")
        if not model:
            raise ValueError("model.default cannot be empty")

        user_providers = config.get("providers") if isinstance(config.get("providers"), dict) else {}
        custom_providers = config.get("custom_providers") if isinstance(config.get("custom_providers"), list) else []
        pdef = resolve_provider_full(
            provider,
            user_providers=user_providers,
            custom_providers=custom_providers,
        )
        if pdef is None:
            raise ValueError(f"unknown Hermes provider: {provider}")
        base_url = str(getattr(pdef, "base_url", "") or "").strip()
        api_mode = determine_api_mode(provider, base_url=base_url, model=model)
        return {
            "provider": provider,
            "model": model,
            "base_url": base_url,
            "api_mode": str(api_mode or ""),
        }

    def _apply_agent_route(self, profile: str, route: dict[str, str] | None) -> None:
        if route is None:
            return
        self._set_config(profile, "model.provider", route["provider"])
        self._set_config(profile, "model.default", route["model"])
        if route["base_url"]:
            self._set_config(profile, "model.base_url", route["base_url"])
        else:
            self._unset_config(profile, "model.base_url")
        if route["api_mode"]:
            self._set_config(profile, "model.api_mode", route["api_mode"])
        else:
            self._unset_config(profile, "model.api_mode")

    def agent_create(self, args: dict[str, Any]) -> dict[str, Any]:
        result = super().agent_create(args)
        agent = result.get("agent") if isinstance(result, dict) else None
        name = str((agent or {}).get("name") or args.get("name") or "").strip().lower()
        if not name:
            return result
        try:
            route = self._resolve_agent_route(name, args)
            self._apply_agent_route(name, route)
            result["agent"] = self.agent_get(name)
            return result
        except Exception:
            # The native profile may already have been created by the base layer.
            # Roll it back so a bad provider/model never leaves a half-created Agent.
            if name != "default":
                try:
                    self.cli.run_text([self.hermes, "profile", "delete", name, "--yes"], timeout=120)
                except Exception:
                    pass
            raise

    def agent_update(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        profile = self._normalize_profile(name)
        self._profile_home(profile)

        # Validate route changes before the base layer mutates model.provider/default.
        route = self._resolve_agent_route(profile, args)
        result = super().agent_update(name, args)
        agent = result.get("agent") if isinstance(result, dict) else None
        final_name = str((agent or {}).get("name") or args.get("name") or name).strip().lower()
        self._apply_agent_route(final_name, route)
        result["agent"] = self.agent_get(final_name)
        return result

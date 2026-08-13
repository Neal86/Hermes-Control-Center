"""Internal Windows WeChat platform runtime for Hermes Control Center."""

from .adapter import check_requirements, register, validate_config

__all__ = ["register", "check_requirements", "validate_config"]

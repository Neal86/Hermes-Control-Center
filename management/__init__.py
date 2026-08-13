"""Hermes native profile/project management services.

Keep package import lightweight so utility modules and tests can import
``management.service`` without eagerly importing Hermes runtime-only modules.
"""

__all__ = ["ManagementCenter"]


def __getattr__(name: str):
    if name == "ManagementCenter":
        from .routed_service import ManagementCenter

        return ManagementCenter
    raise AttributeError(name)

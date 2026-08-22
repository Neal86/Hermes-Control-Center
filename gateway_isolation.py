"""Backward-compatible import facade for the Control Center gateway policy."""

try:  # package import when loaded as the Hermes plugin
    from .hcc_gateway.lifecycle import install_independent_gateway_policy
except ImportError:  # direct source/test import
    from hcc_gateway.lifecycle import install_independent_gateway_policy

__all__ = ["install_independent_gateway_policy"]

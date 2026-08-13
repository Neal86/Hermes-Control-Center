from __future__ import annotations

import importlib
import importlib.machinery
import sys
import types
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def ensure_namespace(alias: str, relative_dir: str):
    existing = sys.modules.get(alias)
    if existing is not None:
        return existing

    package_dir = (PLUGIN_ROOT / relative_dir).resolve()
    if not package_dir.is_dir():
        raise RuntimeError(f"Backend package directory is missing: {package_dir}")

    module = types.ModuleType(alias)
    module.__file__ = str(package_dir / "__init__.py")
    module.__package__ = alias
    module.__path__ = [str(package_dir)]
    spec = importlib.machinery.ModuleSpec(alias, loader=None, is_package=True)
    spec.submodule_search_locations = [str(package_dir)]
    module.__spec__ = spec
    sys.modules[alias] = module
    return module


def load_module(alias: str, relative_dir: str, module_name: str):
    ensure_namespace(alias, relative_dir)
    return importlib.import_module(f"{alias}.{module_name}")

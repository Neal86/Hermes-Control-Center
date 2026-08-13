from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def load_package(alias: str, relative_dir: str):
    existing = sys.modules.get(alias)
    if existing is not None:
        return existing
    package_dir = PLUGIN_ROOT / relative_dir
    init_file = package_dir / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        alias,
        init_file,
        submodule_search_locations=[str(package_dir)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load backend package: {package_dir}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


def load_module(alias: str, relative_dir: str, module_name: str):
    load_package(alias, relative_dir)
    return importlib.import_module(f"{alias}.{module_name}")

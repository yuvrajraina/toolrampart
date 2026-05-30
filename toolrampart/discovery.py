from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path
from types import ModuleType

from .core import ToolRampart, default_rampart


def load_target(target: str | None) -> ToolRampart:
    if not target:
        return default_rampart

    if ":" not in target:
        import_module_or_package(target)
        return default_rampart

    module_name, attribute_name = target.split(":", 1)
    module = importlib.import_module(module_name)
    candidate = getattr(module, attribute_name)
    if not isinstance(candidate, ToolRampart):
        raise TypeError(f"{target!r} does not point to a ToolRampart instance")
    return candidate


def import_module_or_package(name: str) -> ModuleType:
    _ensure_cwd_importable()
    module = importlib.import_module(name)
    if hasattr(module, "__path__"):
        prefix = module.__name__ + "."
        for item in pkgutil.walk_packages(module.__path__, prefix):
            importlib.import_module(item.name)
    return module


def _ensure_cwd_importable() -> None:
    cwd = str(Path.cwd())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

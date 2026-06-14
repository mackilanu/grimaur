"""Loader for the executable `grimoire` script.

The script has no .py extension, so we load it via SourceFileLoader once
and re-export the resulting module
"""

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_grimaur() -> ModuleType:
	path = REPO_ROOT / "grimoire"
	spec = importlib.util.spec_from_file_location(
		"grimoire", path, loader=SourceFileLoader("grimoire", str(path))
	)
	if spec is None or spec.loader is None:
		raise ImportError(f"could not load grimoire module from {path}")
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


grimoire = load_grimaur()

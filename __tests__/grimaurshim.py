"""Loader for the executable `grimaur` script.

The script has no .py extension, so we load it via SourceFileLoader once
and re-export the resulting module
"""

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_grimaur():
	path = REPO_ROOT / "grimaur"
	spec = importlib.util.spec_from_file_location(
		"grimaur", path, loader=SourceFileLoader("grimaur", str(path))
	)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


grimaur = load_grimaur()

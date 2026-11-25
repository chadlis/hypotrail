"""Shared by the tests of the script that makes the edits of task 6 of the L2 demonstration, and by the handbook's tests of its table."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "docs" / "demo" / "edit_copy.py"


def script_values() -> dict:
    """{name: value} of each upper-case name the script defines, read by importing it, which edits nothing."""
    spec = importlib.util.spec_from_file_location("edit_copy", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {name: value for name, value in vars(module).items() if name.isupper()}

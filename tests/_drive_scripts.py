"""Loading and running the scripts of `.claude/skills/drive/` from the tests."""

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRIVE = ROOT / ".claude" / "skills" / "drive"
FIXTURES = DRIVE / "fixtures"


def load(name: str):
    """The module of `.claude/skills/drive/<name>.py`, loaded from its path (the directory is not a package)."""
    spec = importlib.util.spec_from_file_location(f"drive_{name}", DRIVE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(name: str, *arguments, stdin: str = "", env: dict | None = None, cwd=None):
    """The script run in isolated mode, as the settings and the skill run it."""
    return subprocess.run(
        [sys.executable, "-I", str(DRIVE / f"{name}.py"), *map(str, arguments)],
        input=stdin, capture_output=True, text=True, env=env, cwd=cwd,
    )

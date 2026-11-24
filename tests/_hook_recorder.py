"""Starts the hook script given as its first argument in this process, as `python3 -I` starts it, and records what that process does.

Used as `python3 -I tests/_hook_recorder.py SCRIPT ARGUMENTS...` by `tests/test_claude_code_hook.py`. At exit it prints, as the last
line of stderr, `RECORD ` and a JSON object: each path opened through `builtins.open`, `io.open` or `os.open` with its mode or flags,
each process started through `subprocess` or `os`, and each file or folder made, moved or removed through `os`. The listing is bounded by
those names: a file written or a process started another way (for example through `ctypes`) escapes it.
"""

import builtins
import io
import json
import os
import runpy
import subprocess
import sys

record = {"opened": [], "started": [], "changed": []}


def path_of(file):
    return None if isinstance(file, int) else os.path.abspath(os.fsdecode(file))


def recording_open(real):
    def wrapper(file, mode="r", *args, **kwargs):
        record["opened"].append({"path": path_of(file), "mode": mode, "writes": any(letter in mode for letter in "wax+")})
        return real(file, mode, *args, **kwargs)

    return wrapper


def recording_os_open(real):
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

    def wrapper(file, flags, *args, **kwargs):
        record["opened"].append({"path": path_of(file), "mode": flags, "writes": bool(flags & write_flags)})
        return real(file, flags, *args, **kwargs)

    return wrapper


def recording(kind, name, real):
    def wrapper(*args, **kwargs):
        record[kind].append({"call": name, "arguments": [str(each) for each in args[:2]]})
        return real(*args, **kwargs)

    return wrapper


builtins.open = recording_open(builtins.open)
io.open = recording_open(io.open)
os.open = recording_os_open(os.open)
real_execute_child = subprocess.Popen._execute_child


def execute_child(self, args, *rest, **kwargs):
    record["started"].append({"call": "subprocess", "arguments": [str(each) for each in args]})
    return real_execute_child(self, args, *rest, **kwargs)


subprocess.Popen._execute_child = execute_child
for name in ("system", "fork", "forkpty", "posix_spawn", "posix_spawnp", "execv", "execve", "execvp", "execvpe", "spawnv", "spawnve", "popen"):
    if hasattr(os, name):
        setattr(os, name, recording("started", name, getattr(os, name)))
for name in ("mkdir", "makedirs", "rename", "replace", "remove", "unlink", "rmdir", "link", "symlink", "truncate", "mkfifo", "utime", "chmod"):
    if hasattr(os, name):
        setattr(os, name, recording("changed", name, getattr(os, name)))

script, sys.argv = sys.argv[1], sys.argv[1:]
try:
    runpy.run_path(script, run_name="__main__")
finally:
    sys.stdout.flush()
    sys.stderr.write("\nRECORD " + json.dumps(record) + "\n")

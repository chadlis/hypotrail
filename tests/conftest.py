"""Test-suite guard: no test may reach the network.

Every test runs with outbound network access blocked. An attempt is recorded
and raises, and the test fails at teardown unless it asserted the attempt
itself. This is what keeps a model key in the environment from ever leading
to a live call from the default test command (AGENTS.md: live LLM calls are
opt-in and never run in CI). Proxy variables are removed for the same reason:
a proxy on loopback is a way out the loopback allowance would not see.
"""

import shutil
import socket
from pathlib import Path

import pytest


LOOPBACK = {"127.0.0.1", "::1", "localhost"}

# A proxy on loopback would carry a request out of the machine while the guard,
# which allows loopback, sees only the hop to the proxy. No test gets one.
PROXY_VARIABLES = [
    "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy",
]


class NetworkBlocked(RuntimeError):
    pass


class NetworkGuard:
    def __init__(self):
        self.attempts: list[str] = []
        self.acknowledged = False

    def record(self, what: str):
        self.attempts.append(what)
        raise NetworkBlocked(f"network access attempted in a test: {what}")

    def acknowledge(self):
        """A test that asserts the attempts itself calls this."""
        self.acknowledged = True


@pytest.fixture(autouse=True)
def network_guard(monkeypatch):
    guard = NetworkGuard()
    for name in PROXY_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    # "*" bypasses any proxy a client might still find, so a call goes direct
    # and meets the guard like any other.
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("no_proxy", "*")

    def blocked_connect(self, address, *args, **kwargs):
        # Unix sockets and loopback stay possible: they never leave the machine.
        if self.family == socket.AF_UNIX or address[0] in LOOPBACK:
            return real_connect(self, address, *args, **kwargs)
        guard.record(f"connect {address!r}")

    def blocked_getaddrinfo(host, *args, **kwargs):
        if host in LOOPBACK:
            return real_getaddrinfo(host, *args, **kwargs)
        guard.record(f"getaddrinfo {host!r}")

    real_connect = socket.socket.connect
    real_getaddrinfo = socket.getaddrinfo
    monkeypatch.setattr(socket.socket, "connect", blocked_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked_connect)
    monkeypatch.setattr(socket, "getaddrinfo", blocked_getaddrinfo)
    yield guard
    if guard.attempts and not guard.acknowledged:
        pytest.fail(f"network access attempted: {guard.attempts}")


@pytest.fixture
def kept_all_token_log(tmp_path):
    """The Inspect log of the kept `live-l12-plain` Attempt, copied (the kept trace is not touched)."""
    kept = Path(__file__).resolve().parent.parent / "docs" / "handbook" / "traces" / "live-l12-plain" / "inspect"
    shutil.copytree(kept, tmp_path / "inspect")
    return str(next((tmp_path / "inspect").glob("*.eval")))


class LiveDatabaseUsed(BaseException):  # not an Exception: no `except Exception` or `except OSError` can swallow it
    pass


@pytest.fixture
def guard(monkeypatch):
    """Arm with `guard(examples)`: from then on any use of that Workload's database file raises."""
    import builtins
    import io
    import os
    import sqlite3

    from _chinook_helpers import database_of

    def arm(examples):
        target = database_of(examples).resolve()

        def is_target(file) -> bool:
            if isinstance(file, int):
                return False
            try:
                return Path(os.fsdecode(file).removeprefix("file:").split("?")[0]).resolve() == target
            except (TypeError, ValueError):
                return False

        def guarded(real):
            def wrapper(file, *args, **kwargs):
                if is_target(file):
                    raise LiveDatabaseUsed(str(target))
                return real(file, *args, **kwargs)

            return wrapper

        monkeypatch.setattr(io, "open", guarded(io.open))
        monkeypatch.setattr(builtins, "open", guarded(builtins.open))
        monkeypatch.setattr(os, "open", guarded(os.open))
        monkeypatch.setattr(sqlite3, "connect", guarded(sqlite3.connect))

    return arm

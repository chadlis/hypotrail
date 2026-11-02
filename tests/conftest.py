"""Test-suite guard: no test may reach the network.

Every test runs with outbound network access blocked. An attempt is recorded
and raises, and the test fails at teardown unless it asserted the attempt
itself. This is what keeps a model key in the environment from ever leading
to a live call from the default test command (AGENTS.md: live LLM calls are
opt-in and never run in CI).
"""

import socket

import pytest


LOOPBACK = {"127.0.0.1", "::1", "localhost"}


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

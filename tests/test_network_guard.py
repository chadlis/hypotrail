"""The network guard must hold for a client that honours proxy variables.

A container may export HTTPS_PROXY=http://127.0.0.1:<port>. A client honouring
it connects to loopback, which the guard allows, and the proxy carries the
request to the internet. The guard therefore removes the proxy variables for
every test. The variables must be set before the test starts, so the check
runs a real pytest session in a subprocess with them already exported.
"""

import socket
import subprocess
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent

PROXY_VARIABLES = [
    "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy",
]

INNER_TEST = '''
import os
import urllib.error
import urllib.request

import pytest

from conftest import NetworkBlocked


@pytest.mark.parametrize("url", ["https://example.com/", "http://example.com/"])
def test_a_proxy_aware_client_cannot_leave_the_machine(network_guard, url):
    for name in %(names)r:
        assert name not in os.environ
    with pytest.raises((NetworkBlocked, urllib.error.URLError)):
        urllib.request.urlopen(url, timeout=5)
    assert network_guard.attempts, "the attempt went somewhere the guard cannot see"
    network_guard.acknowledge()
'''


class Listener:
    """A stand-in proxy on loopback that counts the connections it receives."""

    def __enter__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.connections = 0
        self._stop = False
        self._thread = threading.Thread(target=self._accept)
        self._thread.start()
        return self

    def _accept(self):
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except (TimeoutError, OSError):
                continue
            self.connections += 1
            conn.close()

    def __exit__(self, *exc):
        self._stop = True
        self._thread.join()
        self.sock.close()


def test_exported_proxy_variables_do_not_open_a_way_out(tmp_path):
    (tmp_path / "conftest.py").write_text((HERE / "conftest.py").read_text())
    (tmp_path / "test_inner.py").write_text(INNER_TEST % {"names": PROXY_VARIABLES})
    with Listener() as proxy:
        env = {"PATH": "/usr/bin:/bin", "NO_PROXY": "", "no_proxy": ""}
        for name in PROXY_VARIABLES:
            env[name] = f"http://127.0.0.1:{proxy.port}"
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp_path)],
            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120,
        )
    assert result.returncode == 0, result.stdout + result.stderr
    assert proxy.connections == 0

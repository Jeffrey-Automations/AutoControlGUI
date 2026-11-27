"""Every HTTP request handler in the package bounds its reads.

``BaseHTTPRequestHandler`` has no timeout of its own: a client that connects
and sends nothing holds one ``ThreadingHTTPServer`` thread for ever, and each
further silent connection holds another. The metrics exporter and the ACME
HTTP-01 server (bound to every interface on purpose) had none. No network
beyond loopback.
"""
import ast
import math
import socket
import time
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[3] / "je_auto_control"


def _handler_classes():
    """``(file, class name)`` of every class deriving ``BaseHTTPRequestHandler``."""
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "BaseHTTPRequestHandler" not in text:
            continue
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any(
                    (isinstance(base, ast.Name) and base.id == "BaseHTTPRequestHandler")
                    or (isinstance(base, ast.Attribute) and base.attr == "BaseHTTPRequestHandler")
                    for base in node.bases):
                found.append((path, node))
    return found


def _declares_timeout(node: ast.ClassDef) -> bool:
    for statement in node.body:
        targets = statement.targets if isinstance(statement, ast.Assign) else (
            [statement.target] if isinstance(statement, ast.AnnAssign) else [])
        if any(isinstance(target, ast.Name) and target.id == "timeout" for target in targets):
            return True
    return False


def test_the_scan_finds_the_known_handlers():
    names = {node.name for _path, node in _handler_classes()}
    assert {"_MetricsHandler", "_ChallengeHandler", "_WebhookHandler"} <= names


@pytest.mark.parametrize("path,node", _handler_classes(),
                         ids=lambda item: getattr(item, "name", None) or Path(item).stem)
def test_each_handler_declares_a_read_timeout(path, node):
    assert _declares_timeout(node), f"{path.name}:{node.name} has no 'timeout' class attribute"


def _metrics():
    from je_auto_control.utils.observability.exporter import PrometheusExporter, _MetricsHandler
    exporter = PrometheusExporter(host="127.0.0.1", port=0)
    return _MetricsHandler, exporter


def _challenge():
    from je_auto_control.utils.tls_acme.challenge import HttpChallengeServer, _ChallengeHandler
    server = HttpChallengeServer(host="127.0.0.1", port=0)
    return _ChallengeHandler, server


@pytest.mark.parametrize("build", [_metrics, _challenge], ids=["metrics", "acme"])
def test_a_silent_client_is_dropped(build, monkeypatch):
    handler, server = build()
    assert isinstance(handler.timeout, (int, float)) and math.isfinite(handler.timeout)
    assert 0 < handler.timeout <= 60
    monkeypatch.setattr(handler, "timeout", 0.3)
    port = server.start()
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5.0) as client:
            started = time.monotonic()
            assert client.recv(1024) == b""  # the server closed it; nothing was sent
            assert time.monotonic() - started < 5.0
    finally:
        server.stop()

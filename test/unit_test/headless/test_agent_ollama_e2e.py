"""Local-model tasks end to end against a loopback server that speaks Ollama's HTTP API. No real model, no Qt.

Each case drives ``run_task`` through the real runtime, ``OllamaTaskBackend`` and the shared
HTTP transport; only the model is replaced, by a ``ThreadingHTTPServer`` answering ``/api/show``
and ``/api/chat``. This is evidence for the backend's contract (model mismatch, refused
connection, timeout, cancellation, budget, completion verification), not for any installed model.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from je_auto_control.utils.agent_runtime import AgentRuntime, AgentTaskSpec
from je_auto_control.utils.agent_runtime.runner import run_task

MODEL = "fixture-local:latest"


class Target:
    def __init__(self):
        self.count = 0

    def ready(self, _spec):
        return True, ""

    def observe(self):
        return {"identity": "fixture", "count": self.count}

    def perform(self, _tool, _arguments):
        self.count += 1
        return {"value": self.count}

    def cleanup(self):
        return None


class Model:
    """What the fake server answers; ``chat`` yields one reply per request."""

    def __init__(self):
        self.show = {"capabilities": ["completion", "tools"]}
        self.show_status = 200
        self.replies = []
        self.delay = 0.0
        self.requests = []
        self.entered = threading.Event()

    def chat(self):
        if self.replies:
            return self.replies.pop(0)
        return {"message": {"role": "assistant", "content": "done"}}


def call(name="AC_screen_size", arguments=None):
    return {"message": {"role": "assistant", "tool_calls": [
        {"function": {"name": name, "arguments": arguments or {}}}]}}


@pytest.fixture
def ollama():
    model = Model()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):  # noqa: N802  # reason: the stdlib handler names methods after HTTP verbs
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            model.requests.append((self.path, body))
            if self.path == "/api/show":
                status, reply = model.show_status, model.show
            elif self.path == "/api/chat":
                model.entered.set()
                time.sleep(model.delay)
                status, reply = 200, model.chat()
            else:
                status, reply = 404, {"error": "not found"}
            raw = json.dumps(reply).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except OSError:
                return  # the client stopped waiting; nothing to deliver

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    try:
        yield model, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def spec(endpoint, **budget):
    return AgentTaskSpec.from_dict({
        "goal": "increment once", "target": "fixture", "mode": "ollama", "allowed_tools": ["AC_screen_size"],
        "options": {"model": MODEL, "endpoint": endpoint},
        "budget": {"model_seconds": 5, **budget},
        "success_criteria": [{"kind": "result_equals", "key": "value", "value": 1}]})


@pytest.fixture
def runtime(tmp_path):
    target = Target()
    owned = AgentRuntime(tmp_path / "tasks.sqlite", targets={"fixture": target})
    try:
        yield owned, target
    finally:
        owned.close()


def test_a_tool_call_then_a_stop_completes_only_after_independent_verification(ollama, runtime):
    model, endpoint = ollama
    owned, target = runtime
    model.replies = [call()]
    result = run_task(owned, owned.submit(spec(endpoint)).task_id)
    assert result.state == "succeeded", result.reason
    assert target.count == 1
    show, first = model.requests[0], model.requests[1]
    assert show == ("/api/show", {"model": MODEL})
    assert [tool["function"]["name"] for tool in first[1]["tools"]] == ["AC_screen_size"]
    assert first[1]["stream"] is False and first[1]["model"] == MODEL


def test_a_stop_before_the_goal_is_met_is_not_success(ollama, runtime):
    _model, endpoint = ollama
    owned, target = runtime
    result = run_task(owned, owned.submit(spec(endpoint)).task_id)
    assert result.state != "succeeded"
    assert target.count == 0


@pytest.mark.parametrize("show, status", [
    ({"capabilities": ["completion"]}, 200),                      # no tool calling
    ({"error": "model 'fixture-local:latest' not found"}, 404),  # not installed
    ({"capabilities": ["tools"], "remote_host": "https://x"}, 200),  # forwarded to a remote host
])
def test_a_model_that_does_not_match_never_reaches_the_target(ollama, runtime, show, status):
    model, endpoint = ollama
    owned, target = runtime
    model.show, model.show_status = show, status
    model.replies = [call()]
    result = run_task(owned, owned.submit(spec(endpoint)).task_id)
    assert result.state == "waiting_user"
    assert target.count == 0
    assert all(path == "/api/show" for path, _body in model.requests)


def test_a_refused_connection_never_reaches_the_target(runtime):
    owned, target = runtime
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()  # nothing listens here now
    result = run_task(owned, owned.submit(spec(f"http://127.0.0.1:{port}")).task_id)
    assert result.state == "waiting_user"
    assert target.count == 0


def test_a_model_slower_than_its_budget_times_out_without_an_action(ollama, runtime):
    model, endpoint = ollama
    owned, target = runtime
    model.delay, model.replies = 3.0, [call()]
    started = time.monotonic()
    result = run_task(owned, owned.submit(spec(endpoint, model_seconds=0.5, retries=0)).task_id)
    assert result.state == "waiting_user"
    assert target.count == 0
    assert time.monotonic() - started < 2.5


def test_cancelling_during_a_model_request_ends_the_task_without_an_action(ollama, runtime):
    model, endpoint = ollama
    owned, target = runtime
    model.delay, model.replies = 3.0, [call()]
    task = owned.submit(spec(endpoint)).task_id
    threading.Thread(target=lambda: model.entered.wait(5) and owned.cancel(task), daemon=True).start()
    started = time.monotonic()
    result = run_task(owned, task)
    assert result.state in {"cancelled", "cancelling"}
    assert target.count == 0
    assert time.monotonic() - started < 2.5


def test_a_model_that_never_stops_is_held_to_its_step_budget(ollama, runtime):
    model, endpoint = ollama
    owned, target = runtime
    model.replies = [call() for _ in range(50)]
    task = spec(endpoint, max_steps=3)
    result = run_task(owned, owned.submit(task).task_id)
    assert result.state != "succeeded"
    assert target.count <= 3


def test_an_unoffered_tool_from_the_model_is_refused(ollama, runtime):
    model, endpoint = ollama
    owned, target = runtime
    model.replies = [call("AC_shell_command", {"command": "whoami"})]
    result = run_task(owned, owned.submit(spec(endpoint)).task_id)
    assert result.state == "waiting_user"
    assert target.count == 0

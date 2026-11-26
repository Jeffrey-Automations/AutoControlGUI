"""Round-3 regression: the Anthropic *planner* LLM backend must catch
``anthropic.AnthropicError`` and honour the empty-string contract instead of
letting a 429/5xx/timeout escape ``complete``.

The ``anthropic`` SDK is not installed in CI, so a fake module carrying an
``AnthropicError`` base class is injected for the duration of each test.
"""
import sys
import types

import pytest

from je_auto_control.utils.executor.run_control import ExecutionStopped, stoppable_run
from je_auto_control.utils.llm.backends import anthropic_backend
from je_auto_control.utils.llm.backends.anthropic_backend import (
    AnthropicLLMBackend,
)


class _FakeAnthropicError(Exception):
    """Stand-in for ``anthropic.AnthropicError`` (a bare Exception)."""


class _FakeRateLimitError(_FakeAnthropicError):
    """Subclass, like the real ``anthropic.RateLimitError``."""


def _install_fake_anthropic(monkeypatch):
    module = types.ModuleType("anthropic")
    module.AnthropicError = _FakeAnthropicError
    monkeypatch.setitem(sys.modules, "anthropic", module)


def _backend(client):
    backend = AnthropicLLMBackend.__new__(AnthropicLLMBackend)
    backend.available = True
    backend._client = client
    return backend


def _client_raising(exc):
    class _Messages:
        def create(self, **kwargs):
            raise exc

    return types.SimpleNamespace(messages=_Messages())


def test_sdk_error_degrades_to_empty_string(monkeypatch):
    _install_fake_anthropic(monkeypatch)
    backend = _backend(_client_raising(_FakeRateLimitError("429 rate limited")))
    assert backend.complete("plan the next action") == ""


def test_successful_response_returns_joined_text(monkeypatch):
    _install_fake_anthropic(monkeypatch)
    block = types.SimpleNamespace(type="text", text="planned action")

    class _Messages:
        def create(self, **kwargs):
            return types.SimpleNamespace(content=[block])

    client = types.SimpleNamespace(messages=_Messages())
    assert _backend(client).complete("plan the next action") == "planned action"


class _FakeServerError(_FakeAnthropicError):
    """Like ``anthropic.InternalServerError``: carries the HTTP status."""

    status_code = 503


class _CountingMessages:
    def __init__(self, on_call=None):
        self.calls = 0
        self.on_call = on_call

    def create(self, **kwargs):
        self.calls += 1
        if self.on_call is not None:
            self.on_call()
        raise _FakeServerError("503 overloaded")


def test_the_sdk_client_is_built_without_its_own_retries(monkeypatch):
    _install_fake_anthropic(monkeypatch)
    seen = {}

    class _Anthropic:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    sys.modules["anthropic"].Anthropic = _Anthropic
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert AnthropicLLMBackend().available is True
    assert seen.get("max_retries") == 0


def test_a_retryable_error_is_retried_up_to_the_attempt_budget(monkeypatch):
    _install_fake_anthropic(monkeypatch)
    monkeypatch.setattr(anthropic_backend, "_RETRY_BACKOFF_S", (0.0,))
    messages = _CountingMessages()
    assert _backend(types.SimpleNamespace(messages=messages)).complete("plan") == ""
    assert messages.calls == anthropic_backend._MAX_ATTEMPTS  # noqa: SLF001


def test_a_stop_during_a_request_is_not_retried(monkeypatch):
    _install_fake_anthropic(monkeypatch)
    with pytest.raises(ExecutionStopped):
        with stoppable_run() as token:
            messages = _CountingMessages(on_call=token.stop)
            _backend(types.SimpleNamespace(messages=messages)).complete("plan")
    assert messages.calls == 1

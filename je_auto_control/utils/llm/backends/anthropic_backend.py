"""Anthropic (Claude) text-completion backend for the action planner."""
import os
from typing import Any, Dict, Optional

from je_auto_control.utils.exception.cancellation import cancellation_checkpoint
from je_auto_control.utils.executor.run_control import checkpoint, pause
from je_auto_control.utils.llm.backends.base import LLMBackend
from je_auto_control.utils.logging.logging_instance import autocontrol_logger

_DEFAULT_MODEL = "claude-opus-4-7"
_REQUEST_TIMEOUT_S = 60.0
# The SDK's own retries (two by default) cannot see a stop, so the client is
# built with none and the same budget is spent here, looking at a stop first.
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_S = (0.5, 1.0)
_RETRYABLE_STATUS = frozenset({408, 409, 429})


class AnthropicLLMBackend(LLMBackend):
    """Call ``claude-*`` chat models via the ``anthropic`` Python SDK."""

    name = "anthropic"

    def __init__(self) -> None:
        self._client = None
        try:
            import anthropic  # noqa: F401
        except ImportError:
            self.available = False
            return
        if not os.environ.get("ANTHROPIC_API_KEY"):
            self.available = False
            return
        try:
            from anthropic import Anthropic
            self._client = Anthropic(max_retries=0)
            self.available = True
        except (ImportError, ValueError, RuntimeError) as error:
            autocontrol_logger.warning(
                "Anthropic LLM client init failed: %r", error,
            )
            self.available = False

    def complete(self, prompt: str,
                 system: Optional[str] = None,
                 model: Optional[str] = None,
                 max_tokens: int = 2048) -> str:
        if not self.available or self._client is None:
            return ""
        chosen_model = (model
                        or os.environ.get("AUTOCONTROL_LLM_MODEL")
                        or _DEFAULT_MODEL)
        kwargs: Dict[str, Any] = {
            "model": chosen_model,
            "max_tokens": int(max_tokens),
            "timeout": _REQUEST_TIMEOUT_S,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        # Every anthropic SDK error subclasses ``anthropic.AnthropicError``
        # (a bare ``Exception``) — none derive from OSError/ValueError/
        # RuntimeError — so a 429/5xx/timeout would otherwise escape
        # ``complete`` instead of honouring the base contract's empty-string
        # degradation. Import is lazy (module never hard-depends on the SDK).
        import anthropic
        for attempt in range(_MAX_ATTEMPTS):
            try:
                return _join_text_blocks(self._client.messages.create(**kwargs))
            except (anthropic.AnthropicError, OSError, ValueError, RuntimeError) as error:
                if attempt + 1 >= _MAX_ATTEMPTS or not _is_retryable(anthropic, error):
                    autocontrol_logger.warning("Anthropic LLM request failed: %r", error)
                    return ""
                autocontrol_logger.info("Anthropic LLM request failed, retrying: %r", error)
            _wait_before_retry(attempt)
        return ""


def _wait_before_retry(attempt: int) -> None:
    """Back off before the next attempt; a stop or cancel raises instead of retrying."""
    cancellation_checkpoint()
    checkpoint()
    pause(_RETRY_BACKOFF_S[min(attempt, len(_RETRY_BACKOFF_S) - 1)])
    cancellation_checkpoint()
    checkpoint()


def _is_retryable(anthropic: Any, error: BaseException) -> bool:
    """Whether the SDK would have retried ``error``: a connection failure, timeout, 408/409/429 or 5xx."""
    if isinstance(error, getattr(anthropic, "APIConnectionError", ())):
        return True
    status = getattr(error, "status_code", None)
    return isinstance(status, int) and (status in _RETRYABLE_STATUS or status >= 500)


def _join_text_blocks(response: object) -> str:
    """Concatenate every text block in an Anthropic response."""
    parts = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text = getattr(block, "text", "") or ""
            if text:
                parts.append(text)
    return "".join(parts)

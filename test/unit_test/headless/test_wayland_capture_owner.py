"""A Wayland capture reaches only the managed operation that requested it. No compositor, no Qt."""
import pytest

from je_auto_control.linux_wayland import capture
from je_auto_control.linux_wayland._capture_owner import owned_capture
from je_auto_control.utils.agent_runtime.context import TaskOperation, operation_scope
from je_auto_control.utils.agent_runtime.errors import AgentTaskError
from je_auto_control.utils.agent_runtime.models import AgentTaskSpec
from je_auto_control.utils.exception.exceptions import AutoControlScreenException


def operation(checkpoint=lambda: None):
    spec = AgentTaskSpec.from_dict({"goal": "look", "target": "fixture", "allowed_tools": ["AC_screenshot"],
                                    "success_criteria": [{"kind": "actions_complete"}]})
    return TaskOperation(spec, checkpoint, None)


def test_outside_a_managed_operation_a_capture_is_a_plain_call():
    assert owned_capture(lambda: "image") == "image"


def test_a_live_operation_is_checked_before_and_after_its_capture():
    events = []
    with operation_scope(operation(lambda: events.append("checkpoint"))):
        assert owned_capture(lambda: events.append("capture") or "image") == "image"
    assert events == ["checkpoint", "capture", "checkpoint"]


def test_authority_lost_while_the_portal_waited_drops_the_image():
    revoked = []

    def checkpoint():
        if revoked:
            raise AgentTaskError("authority revoked")
    with operation_scope(operation(checkpoint)):
        with pytest.raises(AgentTaskError, match="revoked"):
            owned_capture(lambda: revoked.append(True) or "image")


def test_a_refused_operation_never_starts_a_capture():
    def checkpoint():
        raise AgentTaskError("stopped")
    with operation_scope(operation(checkpoint)):
        with pytest.raises(AgentTaskError):
            owned_capture(lambda: pytest.fail("captured"))


def test_an_image_for_a_replaced_operation_is_dropped():
    from je_auto_control.utils.agent_runtime import context
    tokens = []
    with operation_scope(operation()):
        try:
            with pytest.raises(AutoControlScreenException, match="no longer current"):
                owned_capture(lambda: tokens.append(context._CURRENT.set(operation())) or "image")
        finally:
            context._CURRENT.reset(tokens[0])


def test_every_capture_tier_goes_through_the_owner_check(monkeypatch):
    monkeypatch.setattr(capture, "_grab_png", lambda region: capture.Capture(b"png", False))
    with operation_scope(operation(lambda: (_ for _ in ()).throw(AgentTaskError("stopped")))):
        with pytest.raises(AgentTaskError, match="stopped"):
            capture.grab_png([0, 0, 1, 1])

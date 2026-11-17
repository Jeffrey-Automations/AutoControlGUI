"""Injected providers prove scoped reads without loading COM or selecting a desktop window."""
from concurrent.futures import ThreadPoolExecutor
from itertools import count

import pytest

from je_auto_control.utils.agent_runtime.errors import AgentObservationStale, AgentTaskError
from je_auto_control.utils.agent_runtime.partial_observation import PartialObservation
from je_auto_control.utils.agent_runtime.scoped_uia import ScopedUiaSource, UiaField
from je_auto_control.utils.agent_runtime.semantic_snapshot import SemanticSnapshot
from je_auto_control.utils.agent_runtime.uia_launch import BoundUiaWindow
from je_auto_control.utils.process_memory.models import ProcessIdentity


UNSUPPORTED = object()


class Node:
    _identities = count(1)

    def __init__(self, selector="", *, value="text", password=False, pid=42, enabled=True):
        self.properties = {30002: pid, 30020: 123, 30011: selector, 30019: password,
                           30005: value, 30045: value, 30010: enabled}
        self.children = []
        self.parent = None
        self.runtime = (1, next(self._identities))
        self.reads = []

    def add(self, *children):
        self.children.extend(children)
        for child in children:
            child.parent = self
        return self

    def GetCurrentPropertyValueEx(self, property_id, ignore_default):
        assert ignore_default is True
        self.reads.append(property_id)
        value = self.properties[property_id]
        if isinstance(value, BaseException):
            raise value
        return value

    def GetRuntimeId(self):
        return self.runtime


class Automation:
    def __init__(self, root):
        self.root = root
        self.RawViewWalker = self
        self.handles = []
        self.enumeration_error = None
        self.replacement = None

    def ElementFromHandle(self, hwnd):
        self.handles.append(hwnd)
        return self.replacement if len(self.handles) > 1 and self.replacement else self.root

    def CheckNotSupported(self, value):
        return value is UNSUPPORTED

    def GetFirstChildElement(self, node):
        if self.enumeration_error:
            raise self.enumeration_error
        return node.children[0] if node.children else None

    def GetNextSiblingElement(self, node):
        siblings = node.parent.children
        index = siblings.index(node) + 1
        return siblings[index] if index < len(siblings) else None

    def GetParentElement(self, node):
        return node.parent


def source(root, fields, *, verify=None, budget=4096):
    identity = ProcessIdentity("host", "session", 42, 1, "fixture", "1", "x64", 64)
    binding = BoundUiaWindow(identity, 123, verify or (lambda check: check()))
    automation = Automation(root)
    return ScopedUiaSource(binding, "fixture", fields, automation, budget=budget), automation


def test_complete_values_preserve_empty_and_false_without_claiming_revision():
    root = Node().add(Node("empty", value=""), Node("disabled", enabled=False))
    reader, automation = source(root, (UiaField("text", "empty", "value"),
                                      UiaField("enabled", "disabled", "enabled")))
    result = reader.capture(lambda: None)
    assert isinstance(result, SemanticSnapshot)
    assert dict(result.fields) == {"text": "", "enabled": False}
    assert result.revision is None and result.consistency == "best_effort"
    assert automation.handles == [123, 123]


def test_partial_retains_value_and_distinguishes_missing_ambiguous_and_protected():
    secret = Node("secret", value="never-return", password=True)
    root = Node().add(Node("ok"), Node("dup"), Node("dup"), secret)
    fields = tuple(UiaField(name, selector, "value") for name, selector in
                   (("valid", "ok"), ("missing", "absent"), ("duplicate", "dup"), ("secret", "secret")))
    reader, _ = source(root, fields)
    result = reader.capture(lambda: None)
    assert isinstance(result, PartialObservation)
    assert dict(result.fields) == {"valid": "text"}
    assert dict(result.failures) == {"missing": "not_found", "duplicate": "ambiguous", "secret": "protected"}
    assert 30045 not in secret.reads


@pytest.mark.parametrize("password", [UNSUPPORTED, OSError(), 0, None])
def test_unknown_password_never_reads_sensitive_property(password):
    node = Node("secret", password=password)
    reader, _ = source(Node().add(node), (UiaField("secret", "secret", "name"),))
    result = reader.capture(lambda: None)
    assert dict(result.failures) == {"secret": "protected"}
    assert 30005 not in node.reads


@pytest.mark.parametrize("value,reason", [(UNSUPPORTED, "unsupported"), (OSError(), "unreadable"),
                                        (False, "unreadable"), ("x" * 65537, "budget_exceeded")],
                         ids=["unsupported", "provider-error", "wrong-type", "oversize"])
def test_property_failures_are_not_empty_values(value, reason):
    reader, _ = source(Node().add(Node("field", value=value)), (UiaField("field", "field", "value"),))
    result = reader.capture(lambda: None)
    assert result.fields == ()
    assert dict(result.failures) == {"field": reason}


@pytest.mark.parametrize("budget,error,reason", [(1, None, "budget_exceeded"),
                                               (4096, OSError(), "unreadable")])
def test_incomplete_enumeration_cannot_establish_unique_or_missing(budget, error, reason):
    reader, automation = source(Node().add(Node("found")),
        (UiaField("found", "found", "value"), UiaField("missing", "absent", "value")), budget=budget)
    automation.enumeration_error = error
    result = reader.capture(lambda: None)
    assert result.fields == ()
    assert dict(result.failures) == {"found": reason, "missing": reason}


def test_foreign_process_child_rejected_before_selector_or_text_reads():
    foreign = Node("field", pid=99)
    reader, _ = source(Node().add(foreign), (UiaField("field", "field", "value"),))
    with pytest.raises(AgentObservationStale):
        reader.capture(lambda: None)
    assert foreign.reads == [30002]


def test_replaced_root_rejects_values_already_read():
    reader, automation = source(Node().add(Node("field")), (UiaField("field", "field", "value"),))
    automation.replacement = Node()
    automation.replacement.runtime = (9, 9)
    with pytest.raises(AgentObservationStale):
        reader.capture(lambda: None)


def test_owner_loss_after_read_is_not_partial():
    checks = []
    def verify(check):
        check()
        checks.append(True)
        if len(checks) == 2:
            raise AgentObservationStale("owner retired")
    reader, _ = source(Node().add(Node("field")), (UiaField("field", "field", "value"),), verify=verify)
    with pytest.raises(AgentObservationStale):
        reader.capture(lambda: None)


def test_checkpoint_errors_are_never_provider_failures():
    reader, automation = source(Node(), (UiaField("field", "field", "value"),))
    def cancelled():
        raise OSError("checkpoint cancellation")
    with pytest.raises(OSError, match="checkpoint cancellation"):
        reader.capture(cancelled)
    assert automation.handles == []


def test_com_object_never_crosses_owner_thread():
    reader, automation = source(Node(), (UiaField("field", "field", "value"),))
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(reader.capture, lambda: None)
        with pytest.raises(AgentTaskError):
            result.result()
    assert automation.handles == []


@pytest.mark.parametrize("runtime", [(2**31,), (-(2**31) - 1,), (True,)],
                         ids=["overflow", "underflow", "boolean"])
def test_runtime_id_requires_signed_32_bit_parts(runtime):
    root = Node().add(Node("field"))
    root.runtime = runtime
    reader, _ = source(root, (UiaField("field", "field", "value"),))
    result = reader.capture(lambda: None)
    assert result.fields == ()
    assert dict(result.failures) == {"field": "unreadable"}


def test_provider_automation_id_has_bounded_utf8_size():
    reader, _ = source(Node().add(Node("x" * 1025)), (UiaField("field", "field", "value"),))
    result = reader.capture(lambda: None)
    assert dict(result.failures) == {"field": "budget_exceeded"}


def test_foreign_child_is_rejected_before_following_its_siblings():
    foreign = Node("field", pid=99)
    reader, automation = source(Node().add(foreign), (UiaField("field", "field", "value"),))
    def forbidden(_node):
        pytest.fail("foreign child was used for a sibling query")
    automation.GetNextSiblingElement = forbidden
    with pytest.raises(AgentObservationStale):
        reader.capture(lambda: None)
    assert foreign.reads == [30002]


@pytest.mark.parametrize("changed_password", [True, UNSUPPORTED, OSError()],
                         ids=["became-password", "became-unknown", "became-unreadable"])
def test_password_change_during_value_read_discards_value(changed_password):
    node = Node("field")
    original = node.GetCurrentPropertyValueEx
    def changing(property_id, ignore_default):
        value = original(property_id, ignore_default)
        if property_id == 30045:
            node.properties[30019] = changed_password
        return value
    node.GetCurrentPropertyValueEx = changing
    reader, _ = source(Node().add(node), (UiaField("field", "field", "value"),))
    result = reader.capture(lambda: None)
    assert result.fields == ()
    assert dict(result.failures) == {"field": "protected"}


@pytest.mark.parametrize("change_at", ["selection", "value"])
def test_changed_selector_does_not_publish_value_for_original_field(change_at):
    node = Node("field")
    original = node.GetCurrentPropertyValueEx
    selector_reads = []
    def changing(property_id, ignore_default):
        if property_id == 30011:
            selector_reads.append(True)
            if change_at == "selection" and len(selector_reads) == 2:
                node.properties[30011] = "other"
        value = original(property_id, ignore_default)
        if change_at == "value" and property_id == 30045:
            node.properties[30011] = "other"
        return value
    node.GetCurrentPropertyValueEx = changing
    reader, _ = source(Node().add(node), (UiaField("field", "field", "value"),))
    result = reader.capture(lambda: None)
    assert result.fields == ()
    assert dict(result.failures) == {"field": "unreadable"}
    if change_at == "selection":
        assert 30045 not in node.reads


@pytest.mark.parametrize("change_at", ["before-value", "during-value"])
def test_same_process_reparenting_never_publishes_outside_window_value(change_at):
    node, outside = Node("field"), Node("outside")
    outside.properties[30020] = 456
    reader, automation = source(Node().add(node), (UiaField("field", "field", "value"),))
    first_child = automation.GetFirstChildElement
    read_property = node.GetCurrentPropertyValueEx
    def children(current):
        result = first_child(current)
        if current is node and change_at == "before-value":
            node.parent = outside
        return result
    def properties(property_id, ignore_default):
        value = read_property(property_id, ignore_default)
        if property_id == 30045 and change_at == "during-value":
            node.parent = outside
        return value
    automation.GetFirstChildElement = children
    node.GetCurrentPropertyValueEx = properties
    with pytest.raises(AgentObservationStale):
        reader.capture(lambda: None)
    if change_at == "before-value":
        assert 30045 not in node.reads


def test_child_reparented_during_enumeration_is_not_followed():
    node, outside = Node("field"), Node("outside")
    root = Node().add(node)
    reader, automation = source(root, (UiaField("field", "field", "value"),))
    def children(current):
        assert current is root
        node.parent = outside
        return node
    def forbidden(_node):
        pytest.fail("reparented child used for sibling navigation")
    automation.GetFirstChildElement = children
    automation.GetNextSiblingElement = forbidden
    with pytest.raises(AgentObservationStale):
        reader.capture(lambda: None)
    assert 30011 not in node.reads and 30045 not in node.reads


@pytest.mark.parametrize("cycle", [True, False], ids=["cycle", "depth"])
def test_ancestry_must_reach_root_within_budget(cycle):
    node = Node("field")
    root = Node().add(node)
    if cycle:
        node.parent = node
    else:
        node.parent = Node().add(Node()).children[0]
    reader, _ = source(root, (UiaField("field", "field", "value"),), budget=2)
    result = reader.capture(lambda: None)
    assert result.fields == ()
    assert dict(result.failures) == {"field": "budget_exceeded"}
    assert 30045 not in node.reads


def test_root_identity_is_pinned_across_captures_before_new_values_are_read():
    reader, automation = source(Node().add(Node("field")), (UiaField("field", "field", "value"),))
    reader.capture(lambda: None)
    replacement_field = Node("field")
    automation.root = Node().add(replacement_field)
    with pytest.raises(AgentObservationStale):
        reader.capture(lambda: None)
    assert replacement_field.reads == []


def test_partial_field_capture_also_pins_root_identity():
    reader, automation = source(Node(), (UiaField("missing", "missing", "value"),))
    assert isinstance(reader.capture(lambda: None), PartialObservation)
    automation.root = Node()
    with pytest.raises(AgentObservationStale):
        reader.capture(lambda: None)


def test_unreadable_initial_root_does_not_establish_lifetime_baseline():
    root = Node()
    root.runtime = ()
    reader, automation = source(root, (UiaField("field", "field", "value"),))
    assert isinstance(reader.capture(lambda: None), PartialObservation)
    automation.root = Node().add(Node("field"))
    assert isinstance(reader.capture(lambda: None), SemanticSnapshot)

"""Prove payload-page attribution through actual bounded reader logic and fake mappings."""
from dataclasses import replace
import json
import struct

import pytest

from je_auto_control.utils.process_memory.models import MemoryRegion
from headless.test_native_memory_acceptance import acceptance, build, injected
from headless.test_process_memory_pe_image import BASE


def page_target(layout):
    target, kernel, channel, provider, prepared = injected()
    trace = acceptance.PageTrace(layout)
    payload = BASE + 0x3FF8
    provider.memory.extend(bytes(0x2000))
    struct.pack_into("<I12s", provider.memory, 0x3FF8, 17, b"ready")
    struct.pack_into("<Q", provider.memory, 0x2218, payload)
    channel.bootstrap["payload_address"] = payload
    query = provider.query_region
    first = MemoryRegion(BASE + 0x3000, 4096, BASE + 0x3000, 2, True, True, False)
    protection, committed, readable, guard = acceptance.PAGE_LAYOUTS[layout]
    second = MemoryRegion(BASE + 0x4000, 4096, BASE + 0x3000,
                          protection, committed, readable, guard)

    def region(address):
        if BASE + 0x3000 <= address < BASE + 0x4000:
            return first
        if BASE + 0x4000 <= address < BASE + 0x5000:
            return second
        return query(address)

    provider.query_region = region
    original = channel.request
    operations = []

    def request(operation, value, **kwargs):
        operations.append(operation)
        assert operation == "bootstrap" or (operation == "control" and value == {"command": "snapshot"})
        return original(operation, value, **kwargs)

    channel.request = request
    launcher = acceptance._PageLauncher(
        prepared.image, trace, kernel=kernel, last_error=lambda: kernel.error,
        caller_bits=64, channel_factory=lambda _: channel)
    target._owners = replace(target._owners, launcher=launcher)
    target._provider_factory = lambda _: acceptance._PageProvider(provider, trace)
    return target, channel, provider, prepared, trace, operations


def run(target, prepared, trace):
    return acceptance.run_smoke(prepared, target_factory=lambda _: target, page_trace=trace)


@pytest.mark.parametrize("layout", tuple(acceptance.PAGE_LAYOUTS))
def test_layout_evidence_comes_from_payload_queries_without_any_mutation(layout):
    target, channel, provider, prepared, trace, operations = page_target(layout)
    result = run(target, prepared, trace)
    assert result["execution"] == "passed", result
    assert result["checks"]["payload_page_evidence"] is True
    assert result["page_layout"] == layout and result["fault_matrix"] == "not_verified"
    assert "runtime_completion" not in result["checks"]
    assert operations == ["bootstrap", "control"] and channel.retired and provider.closed == 1
    assert (BASE + 0x3FF8, 8) in provider.reads
    assert ((BASE + 0x4000, 8) in provider.reads) == (layout == "split")


@pytest.mark.parametrize("where", ["image", "header", "sequence"])
def test_matching_error_elsewhere_cannot_satisfy_page_case(where):
    target, channel, provider, prepared, trace, _ = page_target("noaccess")
    original = provider.query_region
    bad = BASE + {"image": 0, "header": 0x2200, "sequence": 0x2400}[where]

    def query(address):
        region = original(address)
        return replace(region, readable=False, protection=1) if address == bad else region

    provider.query_region = query
    result = run(target, prepared, trace)
    assert result["execution"] == "failed" and not result["checks"]
    assert not trace.matches() and channel.retired


@pytest.mark.parametrize("changes", [{"allocation": BASE}, {"guard": False},
                                     {"size": 8192}, {"committed": False}])
def test_wrong_fault_page_metadata_is_not_accepted(changes):
    target, _, provider, prepared, trace, _ = page_target("guard")
    original = provider.query_region

    def query(address):
        region = original(address)
        return replace(region, **changes) if address == BASE + 0x4000 else region

    provider.query_region = query
    assert run(target, prepared, trace)["execution"] == "failed"


def test_partial_prefix_read_does_not_supply_page_evidence():
    target, _, provider, prepared, trace, _ = page_target("guard")
    original = provider.read

    def read(address, size):
        value = original(address, size)
        return value[:-1] if address == BASE + 0x3FF8 else value

    provider.read = read
    result = run(target, prepared, trace)
    assert result["execution"] == "failed" and not trace.matches()


def test_evidence_never_combines_distinct_handles():
    trace = acceptance.PageTrace("guard")
    from je_auto_control.utils.process_memory.fixture_probe import FixtureBinding
    trace.bind(FixtureBinding(42, 64, 4096, 16376, 8192, b"x" * 16))
    trace.begin()
    first = trace.opened()
    first.query(16376, MemoryRegion(12288, 4096, 12288, 2, True, True, False))
    first.read(16376, 8, completed=True)
    second = trace.opened()
    second.query(16384, MemoryRegion(16384, 4096, 12288, 0x104, True, True, True))
    assert not trace.matches()


def test_metadata_change_is_sticky_even_if_original_mapping_returns():
    attempt = acceptance._PageAttempt("guard", 16376)
    first = MemoryRegion(12288, 4096, 12288, 2, True, True, False)
    attempt.query(16376, first)
    attempt.query(16376, replace(first, protection=4))
    attempt.query(16376, first)
    attempt.read(16376, 8, completed=True)
    attempt.query(16384, MemoryRegion(16384, 4096, 12288, 0x104, True, True, True))
    assert not attempt.matches()


def test_page_selection_does_not_enable_native_execution(tmp_path, monkeypatch, capsys):
    digest = build(tmp_path)
    monkeypatch.setattr(acceptance, "run_smoke", lambda *a, **k: pytest.fail("native execution"))
    assert acceptance.main(["--build", str(tmp_path), "--sha256", digest,
                            "--page-layout", "guard"]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["execution"] == "not_run" and value["page_layout"] == "guard"


def test_page_success_with_unconfirmed_cleanup_still_fails():
    target, channel, _, prepared, trace, _ = page_target("noaccess")
    channel.fail_close = True
    try:
        result = run(target, prepared, trace)
        assert result["checks"]["payload_page_evidence"] is True
        assert result["execution"] == "failed" and not result["cleanup_confirmed"]
    finally:
        channel.fail_close = False
        target.cleanup()


def prior_split_trace():
    from je_auto_control.utils.process_memory.fixture_probe import FixtureBinding
    trace = acceptance.PageTrace("split")
    trace.bind(FixtureBinding(42, 64, 4096, 16376, 8192, b"x" * 16))
    trace.begin()
    attempt = trace.opened()
    attempt.query(16376, MemoryRegion(12288, 4096, 12288, 2, True, True, False))
    attempt.read(16376, 8, completed=True)
    attempt.query(16384, MemoryRegion(16384, 4096, 12288, 4, True, True, False))
    attempt.read(16384, 8, completed=True)
    assert trace.matches()
    return trace


def test_previous_observation_cannot_supply_page_evidence_for_an_untraced_target():
    trace = prior_split_trace()
    target, _, channel, provider, prepared = injected()
    result = run(target, prepared, trace)
    assert result["execution"] == "failed" and result["checks"] == {}
    assert provider.reads == [] and channel.retired


def test_page_evidence_is_consumed_once():
    trace = prior_split_trace()
    assert trace.consume() and not trace.consume()
    with pytest.raises(ValueError, match="not fresh"):
        trace.begin()
    with pytest.raises(ValueError):
        trace.opened()

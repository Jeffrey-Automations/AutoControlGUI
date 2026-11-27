"""Headless tests for HTTP record/replay cassette. Pure stdlib, no network."""
import json

import pytest

import je_auto_control as ac
from je_auto_control.utils.http_cassette import Cassette, CassetteMissError
from je_auto_control.utils.http_client import build_call


def _fake_inner(call):
    return {"status": 200, "ok": True, "headers": {}, "text": '{"id": 1}',
            "json": {"id": 1}, "url": call["url"]}


def test_record_then_replay():
    cassette = Cassette()
    call = build_call("https://api.example.com/users/1", "GET")
    cassette.recording_transport(_fake_inner)(call)
    assert len(cassette.interactions) == 1
    replayed = cassette.replay_transport()(
        build_call("https://api.example.com/users/1", "GET"))
    assert replayed["json"] == {"id": 1}


def test_replay_miss_raises():
    cassette = Cassette()
    cassette.recording_transport(_fake_inner)(
        build_call("https://api.example.com/a", "GET"))
    replay = cassette.replay_transport()
    unrecorded = build_call("https://api.example.com/b", "GET")
    with pytest.raises(CassetteMissError):
        replay(unrecorded)


def test_save_and_load_round_trip(tmp_path):
    cassette = Cassette()
    cassette.recording_transport(_fake_inner)(
        build_call("https://api.example.com/x", "GET"))
    path = str(tmp_path / "cas.json")
    cassette.save(path)
    loaded = Cassette.load(path)
    assert loaded.replay(
        build_call("https://api.example.com/x", "GET"))["status"] == 200


def test_match_on_body():
    cassette = Cassette()
    cassette.recording_transport(_fake_inner)(
        build_call("https://api.example.com/x", "POST", json_body={"a": 1}))
    transport = cassette.replay_transport(match_on=("method", "url", "body"))
    assert transport(build_call("https://api.example.com/x", "POST",
                                json_body={"a": 1}))["status"] == 200
    other_body = build_call("https://api.example.com/x", "POST",
                            json_body={"a": 2})
    with pytest.raises(CassetteMissError):
        transport(other_body)


def test_recording_passes_through_response():
    cassette = Cassette()
    response = cassette.recording_transport(_fake_inner)(
        build_call("https://api.example.com/u", "GET"))
    assert response["json"] == {"id": 1}      # returns the live response


# --- wiring ---------------------------------------------------------------

def test_executor_round_trip():
    cassette = {"interactions": [{
        "request": {"method": "GET", "url": "https://api.example.com/p",
                    "headers": {}, "body": None},
        "response": {"status": 200, "ok": True, "json": {"ok": True}}}]}
    rec = ac.execute_action([[
        "AC_http_replay",
        {"cassette": json.dumps(cassette), "url": "https://api.example.com/p"},
    ]])
    response = next(v for v in rec.values() if isinstance(v, dict))["response"]
    assert response["status"] == 200
    assert response["json"] == {"ok": True}


def test_http_request_still_works_after_refactor():
    # the transport-seam refactor must not change http_request's surface
    assert callable(ac.http_request)


def test_wiring():
    assert "AC_http_replay" in ac.executor.known_commands()
    from je_auto_control.utils.mcp_server.tools import build_default_tool_registry
    assert "ac_http_replay" in {t.name for t in build_default_tool_registry()}
    from je_auto_control.gui.script_builder.command_schema import _build_specs
    assert "AC_http_replay" in {s.command for s in _build_specs()}


def test_facade_exports():
    for attr in ("Cassette", "CassetteMissError"):
        assert hasattr(ac, attr)
        assert attr in ac.__all__


# --- want_bytes: the undecoded body is recorded, masked, and replayed as bytes

def _bytes_inner(content):
    def inner(call):
        return {"status": 200, "ok": True, "headers": {}, "text": content.decode("utf-8", "replace"),
                "json": None, "url": call["url"], "content": content}
    return inner


def test_a_binary_body_saves_and_replays_as_the_same_bytes(tmp_path):
    raw = bytes(range(256))
    cassette = Cassette()
    call = build_call("https://api.example.com/logo.png", "GET")
    live = cassette.recording_transport(_bytes_inner(raw))(call)
    assert live["content"] == raw   # the live caller still gets bytes
    path = cassette.save(str(tmp_path / "cas.json"))
    replayed = Cassette.load(path).replay(build_call("https://api.example.com/logo.png", "GET"))
    assert replayed["content"] == raw


def test_a_json_byte_body_is_masked_like_a_text_body(tmp_path):
    secret = "fixture-only-token"  # NOSONAR S2068 reason: masking test fixture, not a credential
    raw = json.dumps({"access_token": secret, "id": 7}).encode("utf-8")
    cassette = Cassette()
    cassette.recording_transport(_bytes_inner(raw))(build_call("https://api.example.com/t", "POST"))
    path = cassette.save(str(tmp_path / "cas.json"))
    saved = (tmp_path / "cas.json").read_text(encoding="utf-8")
    assert secret not in saved
    content = Cassette.load(path).replay(build_call("https://api.example.com/t", "POST"))["content"]
    assert json.loads(content) == {"access_token": "<redacted>", "id": 7}

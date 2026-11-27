"""Headless tests for the JWT codec. Pure stdlib, no Qt imports."""
import json

import pytest

import je_auto_control as ac
from je_auto_control.utils.jwt import (
    ClaimsPolicy, ExpiredTokenError, InvalidSignatureError, JwtError,
    decode_jwt, encode_jwt)

# Build the test key at runtime so secret scanners don't flag a literal.
KEY = "test-" + "k" * 16
OTHER_KEY = "other-" + "k" * 16


def test_round_trip():
    token = encode_jwt({"sub": "u1", "role": "admin"}, KEY)
    assert token.count(".") == 2
    claims = decode_jwt(token, KEY, now=1000)
    assert claims["sub"] == "u1"
    assert claims["role"] == "admin"


def test_expired_token():
    token = encode_jwt({"sub": "u1", "exp": 1000}, KEY)
    with pytest.raises(ExpiredTokenError):
        decode_jwt(token, KEY, now=2000)
    # leeway lets a just-expired token through
    policy = ClaimsPolicy(leeway=10)
    assert decode_jwt(token, KEY, policy, now=1005)["sub"] == "u1"


def test_not_yet_valid():
    token = encode_jwt({"sub": "u1", "nbf": 1000}, KEY)
    with pytest.raises(JwtError):
        decode_jwt(token, KEY, now=500)
    assert decode_jwt(token, KEY, now=1500)["sub"] == "u1"


def test_bad_signature_rejected():
    token = encode_jwt({"sub": "u1"}, KEY)
    with pytest.raises(InvalidSignatureError):
        decode_jwt(token, OTHER_KEY, now=1000)


def test_alg_none_rejected():
    import base64

    def seg(data):
        raw = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    forged = f"{seg({'alg': 'none', 'typ': 'JWT'})}.{seg({'sub': 'admin'})}."
    with pytest.raises(JwtError):
        decode_jwt(forged, KEY, now=1000)


def test_algorithm_allowlist_blocks_other_alg():
    token = encode_jwt({"sub": "u1"}, KEY, alg="HS512")
    hs256_only = ClaimsPolicy(algorithms=("HS256",))
    with pytest.raises(JwtError):
        decode_jwt(token, KEY, hs256_only, now=1000)
    policy = ClaimsPolicy(algorithms=("HS512",))
    assert decode_jwt(token, KEY, policy, now=1000)["sub"] == "u1"


def test_audience_and_issuer():
    token = encode_jwt({"sub": "u1", "aud": "api", "iss": "me"}, KEY)
    policy = ClaimsPolicy(audience="api", issuer="me")
    assert decode_jwt(token, KEY, policy, now=1000)["sub"] == "u1"
    other_audience = ClaimsPolicy(audience="other")
    other_issuer = ClaimsPolicy(issuer="someone-else")
    with pytest.raises(JwtError):
        decode_jwt(token, KEY, other_audience, now=1000)
    with pytest.raises(JwtError):
        decode_jwt(token, KEY, other_issuer, now=1000)


def test_audience_list_membership():
    token = encode_jwt({"sub": "u1", "aud": ["api", "web"]}, KEY)
    assert decode_jwt(token, KEY, ClaimsPolicy(audience="web"), now=1000)["sub"] == "u1"


def test_malformed_token():
    with pytest.raises(JwtError):
        decode_jwt("not-a-jwt", KEY, now=1000)


def test_unsupported_algorithm_on_encode():
    with pytest.raises(JwtError):
        encode_jwt({"sub": "u1"}, KEY, alg="RS256")


# --- wiring ---------------------------------------------------------------

def test_executor_round_trip():
    enc = ac.execute_action([[
        "AC_jwt_encode", {"claims": json.dumps({"sub": "u1"}), "key": KEY},
    ]])
    token = next(v for v in enc.values() if isinstance(v, dict))["token"]
    dec = ac.execute_action([["AC_jwt_decode", {"token": token, "key": KEY}]])
    payload = next(v for v in dec.values() if isinstance(v, dict))
    assert payload["ok"] is True
    assert payload["claims"]["sub"] == "u1"


def test_executor_reports_invalid():
    enc = ac.execute_action([[
        "AC_jwt_encode", {"claims": json.dumps({"sub": "u1"}), "key": KEY},
    ]])
    token = next(v for v in enc.values() if isinstance(v, dict))["token"]
    dec = ac.execute_action([[
        "AC_jwt_decode", {"token": token, "key": OTHER_KEY}]])
    payload = next(v for v in dec.values() if isinstance(v, dict))
    assert payload["ok"] is False
    assert "error" in payload


def test_wiring():
    known = ac.executor.known_commands()
    assert {"AC_jwt_encode", "AC_jwt_decode"} <= known
    from je_auto_control.utils.mcp_server.tools import build_default_tool_registry
    names = {t.name for t in build_default_tool_registry()}
    assert {"ac_jwt_encode", "ac_jwt_decode"} <= names
    from je_auto_control.gui.script_builder.command_schema import _build_specs
    cmds = {s.command for s in _build_specs()}
    assert {"AC_jwt_encode", "AC_jwt_decode"} <= cmds


def test_facade_exports():
    for attr in ("encode_jwt", "decode_jwt", "ClaimsPolicy", "JwtError",
                 "ExpiredTokenError", "InvalidSignatureError"):
        assert hasattr(ac, attr)
        assert attr in ac.__all__


# --- ac_jwt_decode takes the helper's leeway, validated ----------------------

def _mcp_decode(arguments):
    from je_auto_control.utils.mcp_server.server import MCPServer
    from je_auto_control.utils.mcp_server.tools._factories import jwt_tools
    server = MCPServer(tools=jwt_tools())
    reply = server.handle_line(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                           "params": {"name": "ac_jwt_decode", "arguments": arguments}}))
    return json.loads(reply)["result"]


def test_the_mcp_tool_passes_leeway_to_the_helper():
    import time
    token = encode_jwt({"sub": "u1", "exp": int(time.time()) - 5}, KEY)
    assert json.loads(_mcp_decode({"token": token, "key": KEY})["content"][0]["text"])["ok"] is False
    result = _mcp_decode({"token": token, "key": KEY, "leeway": 60})
    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"])["claims"]["sub"] == "u1"


@pytest.mark.parametrize("leeway", [float("nan"), float("inf"), -1, 3601, True, "10"])
def test_a_leeway_that_would_disable_the_expiry_check_is_refused(leeway):
    from je_auto_control.utils.mcp_server.tools import _handlers_operations as h_ops
    token = encode_jwt({"sub": "u1", "exp": 1000}, KEY)   # long expired
    with pytest.raises(JwtError, match="leeway"):
        h_ops.jwt_decode(token, KEY, leeway=leeway)


def test_the_mcp_schema_declares_the_leeway_bounds():
    from je_auto_control.utils.mcp_server.tools._factories import jwt_tools
    [decode] = [tool for tool in jwt_tools() if tool.name == "ac_jwt_decode"]
    assert decode.input_schema["properties"]["leeway"] == {
        "type": "number", "minimum": 0, "maximum": 3600}


@pytest.mark.parametrize("leeway", [float("nan"), float("inf"), -1.0, True, "5"])
def test_the_library_policy_refuses_a_leeway_that_would_disable_expiry(leeway):
    from je_auto_control.utils.jwt.jwt_codec import ClaimsPolicy, JwtError
    with pytest.raises(JwtError):
        ClaimsPolicy(leeway=leeway)


def test_ac_jwt_decode_refuses_a_nan_leeway():
    from je_auto_control.utils.executor.action_executor import executor
    from je_auto_control.utils.jwt.jwt_codec import JwtError, encode_jwt
    token = encode_jwt({"exp": 1}, "k" * 32)
    with pytest.raises(JwtError):
        executor.event_dict["AC_jwt_decode"](token, "k" * 32, leeway=float("nan"))

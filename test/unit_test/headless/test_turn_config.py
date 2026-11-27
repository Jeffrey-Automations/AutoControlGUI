"""Tests for the coturn config bundle generator (round 22)."""
from je_auto_control.utils.remote_desktop.turn_config import (
    main as turn_main,
    render_docker_compose, render_readme, render_systemd_unit,
    render_turnserver_conf, write_bundle,
)


def test_turnserver_conf_contains_required_fields():
    body = render_turnserver_conf(
        realm="example.com", listen_port=3478, tls_port=5349,
        user="alice", secret="HUNTER2",
    )
    assert "realm=example.com" in body
    assert "listening-port=3478" in body
    assert "user=alice:HUNTER2" in body
    assert "lt-cred-mech" in body


def test_turnserver_conf_with_tls_includes_cert_lines():
    body = render_turnserver_conf(
        realm="r", listen_port=3478, tls_port=5349,
        user="u", secret="s",
        tls_cert="/etc/letsencrypt/cert.pem",
        tls_key="/etc/letsencrypt/key.pem",
    )
    assert "tls-listening-port=5349" in body
    assert "cert=/etc/letsencrypt/cert.pem" in body
    assert "pkey=/etc/letsencrypt/key.pem" in body


def test_turnserver_conf_omits_tls_lines_when_no_cert():
    body = render_turnserver_conf(
        realm="r", listen_port=3478, tls_port=5349, user="u", secret="s",
    )
    assert "tls-listening-port" not in body
    assert "cert=" not in body


def test_systemd_unit_references_conf_path():
    unit = render_systemd_unit(conf_path="/etc/turnserver.conf")
    assert "ExecStart=/usr/bin/turnserver -c /etc/turnserver.conf" in unit
    assert "[Service]" in unit
    assert "[Install]" in unit


def test_docker_compose_uses_host_network():
    """coturn relays UDP — bridge mode is wrong; must be host networking."""
    compose = render_docker_compose(
        conf_path="/srv/turnserver.conf", listen_port=3478, tls_port=5349,
    )
    assert "network_mode: host" in compose
    assert "/srv/turnserver.conf:/etc/coturn/turnserver.conf:ro" in compose


def test_readme_picks_turns_scheme_when_tls():
    body = render_readme(
        realm="example.com", listen_port=3478, tls_port=5349,
        user="alice", secret="HUNTER2", tls=True,
    )
    assert "turns:example.com:5349" in body


def test_readme_picks_turn_scheme_when_no_tls():
    body = render_readme(
        realm="example.com", listen_port=3478, tls_port=5349,
        user="alice", secret="HUNTER2", tls=False,
    )
    assert "turn:example.com:3478" in body


def test_write_bundle_creates_all_four_files(tmp_path):
    out = tmp_path / "bundle"
    write_bundle(
        out, realm="r", user="u", secret="s",
        listen_port=3478, tls_port=5349,
        tls_cert=None, tls_key=None, external_ip=None,
    )
    files = sorted(p.name for p in out.iterdir())
    assert files == [
        "README.txt", "coturn.service", "docker-compose.yml", "turnserver.conf",
    ]


def test_cli_main_writes_bundle(tmp_path):
    out = tmp_path / "bundle"
    rc = turn_main([
        "--realm", "turn.example.com",
        "--user", "alice", "--secret", "SECRET123",
        "--output-dir", str(out),
    ])
    assert rc == 0
    body = (out / "turnserver.conf").read_text(encoding="utf-8")
    assert "realm=turn.example.com" in body
    assert "user=alice:SECRET123" in body


def test_cli_main_auto_generates_secret_when_missing(tmp_path):
    out = tmp_path / "bundle"
    rc = turn_main([
        "--realm", "r", "--user", "u",
        "--output-dir", str(out),
    ])
    assert rc == 0
    body = (out / "turnserver.conf").read_text(encoding="utf-8")
    # Auto-generated tokens are URL-safe random, so the user line is present
    # but with an opaque non-empty secret.
    user_line = next(
        line for line in body.splitlines() if line.startswith("user=u:")
    )
    secret = user_line.split(":", 1)[1]
    assert len(secret) >= 16  # token_urlsafe(24) → ~32 chars


def _bundle(out):
    write_bundle(
        out, realm="r", user="u", secret="TOPSECRET",
        listen_port=3478, tls_port=5349,
        tls_cert=None, tls_key=None, external_ip=None,
    )


def _only_owner_can_read(path) -> bool:
    import os
    import stat
    import sys
    if sys.platform == "win32":
        from je_auto_control.utils.action_signing._private_file import _windows_dacl_sddl
        # Protected (inherits nothing) and one entry: the current user.
        dacl = _windows_dacl_sddl(path).partition("D:")[2]
        return dacl.startswith("P") and dacl.count("(") == 1
    return stat.S_IMODE(os.stat(path).st_mode) & 0o077 == 0


def test_files_holding_the_turn_secret_are_readable_by_their_owner_only(tmp_path):
    out = tmp_path / "bundle"
    out.mkdir()
    (out / "turnserver.conf").write_text("old", encoding="utf-8")   # replaced, not reused
    _bundle(out)
    for name in ("turnserver.conf", "README.txt"):
        assert "TOPSECRET" in (out / name).read_text(encoding="utf-8")
        assert _only_owner_can_read(out / name), name


def test_a_failed_secret_write_keeps_the_previous_file_and_leaves_no_temp(tmp_path, monkeypatch):
    import pytest
    from je_auto_control.utils.action_signing import _private_file
    out = tmp_path / "bundle"
    out.mkdir()
    (out / "turnserver.conf").write_text("previous", encoding="utf-8")

    def refuse(*_args, **_kwargs):
        raise OSError("disk full")

    # The bundle's secret files go through the shared owner-only writer.
    monkeypatch.setattr(_private_file.os, "replace", refuse)
    with pytest.raises(OSError, match="disk full"):
        _bundle(out)
    assert (out / "turnserver.conf").read_text(encoding="utf-8") == "previous"
    assert sorted(p.name for p in out.iterdir()) == ["turnserver.conf"]

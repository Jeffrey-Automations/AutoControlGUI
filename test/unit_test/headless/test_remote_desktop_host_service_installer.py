"""Phase 3.1: host_service installer output tests."""
import json

import pytest

# These imports go through host_service which lazy-imports aiortc.
# Skip if WebRTC extras are missing — install commands themselves work
# without aiortc, but the module-level pull-through fails without it.
pytest.importorskip("aiortc")
pytest.importorskip("av")

from je_auto_control.utils.remote_desktop import host_service  # noqa: E402


def test_write_default_config_creates_stub(tmp_path):
    target = tmp_path / "service.json"
    host_service.write_default_config(target)
    assert target.exists()
    raw = json.loads(target.read_text(encoding="utf-8"))
    assert raw["token"] == "CHANGE_ME_BEFORE_USE"  # nosec B105  # test fixture
    assert "server_url" in raw
    assert "host_id" in raw


def test_generate_systemd_unit(tmp_path):
    config = tmp_path / "service.json"
    host_service.write_default_config(config)
    output = tmp_path / "rd-host.service"
    host_service._generate_systemd_unit(config, output)
    text = output.read_text(encoding="utf-8")
    assert "[Service]" in text
    assert "ExecStart=" in text
    assert _exec_start_argv(text)[-1] == str(config)
    assert "Restart=on-failure" in text


def test_generate_launchd_plist(tmp_path):
    config = tmp_path / "service.json"
    host_service.write_default_config(config)
    output = tmp_path / "rd-host.plist"
    host_service._generate_launchd_plist(config, output)
    text = output.read_text(encoding="utf-8")
    assert "<key>Label</key>" in text
    assert "<key>RunAtLoad</key>" in text
    assert str(config) in text


def test_uninstall_systemd_removes_file(tmp_path):
    unit = tmp_path / "rd-host.service"
    unit.write_text("[Unit]\nDescription=stub\n", encoding="utf-8")
    rc = host_service._uninstall_systemd_unit(unit)
    assert rc == 0
    assert not unit.exists()


def test_uninstall_launchd_removes_file(tmp_path):
    plist = tmp_path / "rd-host.plist"
    plist.write_text("<plist/>", encoding="utf-8")
    rc = host_service._uninstall_launchd_plist(plist)
    assert rc == 0
    assert not plist.exists()


def test_uninstall_returns_error_for_missing_unit(tmp_path):
    nonexistent = tmp_path / "nope.service"
    assert host_service._uninstall_systemd_unit(nonexistent) == 1


def test_arg_parser_includes_uninstall_commands():
    parser = host_service._build_arg_parser()
    # argparse stores subparser names in choices on the dest action.
    sub_action = next(
        a for a in parser._actions if a.dest == "command"
    )
    choices = set(sub_action.choices.keys())
    assert "uninstall-windows-service" in choices
    assert "uninstall-launchd" in choices
    assert "uninstall-systemd" in choices


def _exec_start_argv(unit_text):
    """Split ExecStart= the way systemd does: specifiers, quoted words with C escapes, then ``$$``."""
    line = next(row for row in unit_text.splitlines() if row.startswith("ExecStart="))
    line = line[len("ExecStart="):].replace("%%", "%")
    words, word, quoted, index = [], None, False, 0
    while index < len(line):
        char = line[index]
        if char == '"':
            quoted, word = not quoted, word or ""
        elif char == "\\" and quoted:
            index += 1
            word += line[index]
        elif char == " " and not quoted:
            if word is not None:
                words.append(word)
            word = None
        else:
            word = (word or "") + char
        index += 1
    assert not quoted, "unbalanced quote"
    if word is not None:
        words.append(word)
    return [item.replace("$$", "$") for item in words]


_AWKWARD = 'dir with space/quo"te/back\\slash/100% $HOME ${X} & <tag>'


def test_unit_generators_quote_and_escape_awkward_paths(tmp_path, monkeypatch):
    import plistlib
    python = str(tmp_path / _AWKWARD / "python3")
    config = tmp_path / _AWKWARD / "service.json"
    monkeypatch.setattr(host_service.sys, "executable", python)
    unit, plist = tmp_path / "rd-host.service", tmp_path / "rd-host.plist"
    host_service._generate_systemd_unit(config, unit)
    host_service._generate_launchd_plist(config, plist)
    expected = [python, "-m", "je_auto_control.utils.remote_desktop.host_service", "run", "--config", str(config)]
    assert _exec_start_argv(unit.read_text(encoding="utf-8")) == expected
    assert plistlib.loads(plist.read_bytes())["ProgramArguments"] == expected


def test_launchd_plist_keeps_the_whitespace_xml_can_hold(tmp_path):
    import plistlib
    config = tmp_path / "line\nbreak\rreturn\ttab" / "service.json"
    plist = tmp_path / "rd-host.plist"
    host_service._generate_launchd_plist(config, plist)
    assert plistlib.loads(plist.read_bytes())["ProgramArguments"][-1] == str(config)


@pytest.mark.parametrize("generator,bad", [
    *[("_generate_systemd_unit", bad) for bad in ("line\nbreak", "tab\t", "nul\x00", "bell\x07", "del\x7f",
                                                  "surrogate\udcff")],
    *[("_generate_launchd_plist", bad) for bad in ("nul\x00", "bell\x07", "surrogate\udcff", "nonchar￿")],
])
def test_unit_generators_reject_paths_the_format_cannot_hold(tmp_path, generator, bad):
    from je_auto_control.utils.exception.exceptions import AutoControlException
    output = tmp_path / "unit"
    with pytest.raises(AutoControlException, match="cannot"):
        getattr(host_service, generator)(tmp_path / bad / "service.json", output)
    assert not output.exists()


@pytest.mark.parametrize("command", ["generate-systemd", "generate-launchd"])
def test_generate_commands_report_an_unrepresentable_path_without_a_traceback(tmp_path, command, capsys):
    output = tmp_path / "unit"
    bad_config = str(tmp_path / "bad") + chr(7)
    assert host_service.main([command, str(output), "--config", bad_config]) == 2
    assert "Cannot write" in capsys.readouterr().err
    assert not output.exists()

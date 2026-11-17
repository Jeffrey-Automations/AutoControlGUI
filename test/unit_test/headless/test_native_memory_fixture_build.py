"""Verify fixture build provenance and no-execution behavior with injected build tools."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

BUILD = Path(__file__).resolve().parents[2] / "fixtures" / "native_memory" / "build_fixture.py"
_spec = importlib.util.spec_from_file_location("native_fixture_build", BUILD)
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)


@pytest.fixture
def configured(tmp_path, monkeypatch):
    msvc, sdk = tmp_path / "msvc", tmp_path / "sdk"
    compiler = msvc / "bin" / "Hostx64" / "x64" / "cl.exe"
    compiler.parent.mkdir(parents=True)
    compiler.write_bytes(b"compiler")
    compiler.with_name("dumpbin.exe").write_bytes(b"inspector")
    for directory in [msvc / "include", msvc / "lib" / "x64",
                      *(sdk / "Include" / "1" / name for name in ("ucrt", "shared", "um")),
                      *(sdk / "Lib" / "1" / name / "x64" for name in ("ucrt", "um"))]:
        directory.mkdir(parents=True)
    source = tmp_path / "fixture.c"
    source.write_bytes(b"reviewed-source")
    monkeypatch.setattr(builder, "__file__", str(tmp_path / "build_fixture.py"))
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if Path(command[0]).name == "cl.exe":
            Path(kwargs["cwd"], "memory_fixture.exe").write_bytes(b"built-image")
            source.write_bytes(b"concurrent-source-change")
            return SimpleNamespace(returncode=0, stdout="compiled", stderr="")
        return SimpleNamespace(returncode=0, stdout="8664 machine (x64)\n    bcrypt.dll\n    KERNEL32.dll\n", stderr="")

    monkeypatch.setattr(builder.subprocess, "run", run)
    return msvc, sdk, tmp_path / "out", calls


def test_build_uses_source_snapshot_scrubs_flags_and_never_runs_fixture(configured, monkeypatch):
    msvc, sdk, output, calls = configured
    for name in ("CL", "_CL_", "LINK", "_LINK_", "INCLUDE", "LIB", "LIBPATH"):
        monkeypatch.setenv(name, "unreviewed-option")
    manifest = json.loads(builder.build(msvc, sdk, "1", output).read_text())
    assert [Path(command[0]).name for command, _ in calls] == ["cl.exe", "dumpbin.exe"]
    compile_command, options = calls[0]
    assert str(output / "fixture.c") in compile_command
    assert "/MT" in compile_command and "/WX" in compile_command
    assert not {"CL", "_CL_", "LINK", "_LINK_", "INCLUDE", "LIB", "LIBPATH"} & options["env"].keys()
    assert manifest["source_sha256"] == hashlib.sha256(b"reviewed-source").hexdigest()
    assert manifest["image_sha256"] == hashlib.sha256(b"built-image").hexdigest()
    assert manifest["imported_dlls"] == ["bcrypt.dll", "kernel32.dll"]
    assert manifest["execution"] == "not_run" and manifest["native_acceptance"] == "not_verified"
    assert manifest["dependency_trust"] == "not_verified"


def test_existing_build_directory_is_never_overwritten(configured):
    msvc, sdk, output, calls = configured
    output.mkdir()
    artifact = output / "memory_fixture.exe"
    artifact.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        builder.build(msvc, sdk, "1", output)
    assert artifact.read_bytes() == b"existing" and not calls


def test_unexpected_imports_cannot_publish_manifest(configured, monkeypatch):
    msvc, sdk, output, _calls = configured
    original = builder.subprocess.run

    def altered(command, **kwargs):
        result = original(command, **kwargs)
        if Path(command[0]).name == "dumpbin.exe":
            result.stdout += "    python314.dll\n"
        return result

    monkeypatch.setattr(builder.subprocess, "run", altered)
    with pytest.raises(RuntimeError, match="dependencies"):
        builder.build(msvc, sdk, "1", output)
    assert not (output / "manifest.json").exists()


def test_changed_compile_snapshot_cannot_publish_manifest(configured, monkeypatch):
    msvc, sdk, output, _calls = configured
    original = builder.subprocess.run

    def altered(command, **kwargs):
        result = original(command, **kwargs)
        if Path(command[0]).name == "cl.exe":
            (output / "fixture.c").write_bytes(b"changed snapshot")
        return result

    monkeypatch.setattr(builder.subprocess, "run", altered)
    with pytest.raises(RuntimeError, match="source changed"):
        builder.build(msvc, sdk, "1", output)
    assert not (output / "manifest.json").exists()


def test_compile_failure_retains_diagnostic_log_and_no_manifest(configured, monkeypatch):
    msvc, sdk, output, _calls = configured
    monkeypatch.setattr(builder.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=1, stdout="compile failure", stderr="diagnostic"))
    with pytest.raises(RuntimeError, match="compilation failed"):
        builder.build(msvc, sdk, "1", output)
    assert (output / "build.log").read_text() == "compile failurediagnostic"
    assert not (output / "manifest.json").exists()

"""Build, hash and inventory the native fixture without executing it."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


ARTIFACTS = {
    "memory": ("fixture.c", "memory_fixture.exe", ("bcrypt.dll", "kernel32.dll"), ("bcrypt.lib",)),
    "uia": ("uia_fixture.c", "uia_fixture.exe", ("kernel32.dll", "user32.dll"), ("user32.lib",)),
}


def digest(path: Path) -> str:
    """Hash one build input or output without treating the digest as execution evidence."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect_image(compiler: Path, executable: Path,
                  environment: dict[str, str], *, kind: str = "memory") -> tuple[Path, list[str]]:
    """Inventory the linked image without starting its entry point."""
    output = executable.parent
    inspector = compiler.with_name("dumpbin.exe")
    report = subprocess.run([str(inspector), "/headers", "/imports", str(executable)],
                            cwd=output, env=environment, capture_output=True,
                            text=True, timeout=30, check=True)
    (output / "image-report.txt").write_text(report.stdout, encoding="utf-8")
    imports = sorted({name.lower() for name in re.findall(
        r"^\s+([A-Za-z0-9_.-]+\.dll)\s*$", report.stdout, flags=re.MULTILINE | re.IGNORECASE)})
    if imports != list(ARTIFACTS[kind][2]) or "8664 machine (x64)" not in report.stdout:
        raise RuntimeError("native fixture image has unexpected architecture or dependencies")
    return inspector, imports


def toolchain(msvc: Path, sdk: Path, version: str) -> tuple[Path, list[Path], list[Path]]:
    """Locate explicit compiler, include and library paths before creating output."""
    msvc, sdk = msvc.resolve(), sdk.resolve()
    compiler = msvc / "bin" / "Hostx64" / "x64" / "cl.exe"
    includes = [msvc / "include",
                *(sdk / "Include" / version / name for name in ("ucrt", "shared", "um"))]
    libraries = [msvc / "lib" / "x64",
                 *(sdk / "Lib" / version / name / "x64" for name in ("ucrt", "um"))]
    if not compiler.is_file() or not all(path.is_dir() for path in [*includes, *libraries]):
        raise ValueError("required x64 MSVC/SDK files are unavailable")
    return compiler, includes, libraries


def compile_image(tools: tuple[Path, list[Path], list[Path]], source_copy: Path,
                  *, kind: str = "memory") -> dict[str, str]:
    """Compile the captured source using explicit search paths and scrubbed build options."""
    compiler, includes, libraries = tools
    output = source_copy.parent
    executable = output / ARTIFACTS[kind][1]
    command = [str(compiler), "/nologo", "/W4", "/WX", "/O2", "/MT", "/GS", "/guard:cf",
               *(f"/I{path}" for path in includes), str(source_copy),
               f"/Fo{output / 'fixture.obj'}",
               f"/Fe{executable}", "/link", *(f"/LIBPATH:{path}" for path in libraries),
               *ARTIFACTS[kind][3], "/DYNAMICBASE", "/NXCOMPAT", "/HIGHENTROPYVA", "/INCREMENTAL:NO"]
    environment = os.environ.copy()
    for variable in ("CL", "_CL_", "LINK", "_LINK_", "INCLUDE", "LIB", "LIBPATH"):
        environment.pop(variable, None)
    environment["PATH"] = str(compiler.parent) + os.pathsep + environment.get("PATH", "")
    result = subprocess.run(command, cwd=output, env=environment, capture_output=True,
                            text=True, timeout=120, check=False)
    (output / "build.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"native fixture compilation failed; see {output / 'build.log'}")
    return environment


def build(msvc: Path, sdk: Path, version: str, output: Path, *, kind: str = "memory") -> Path:
    """Compile x64 with static CRT into a new directory; never run the resulting image."""
    if kind not in ARTIFACTS:
        raise ValueError("unknown native fixture kind")
    source = Path(__file__).with_name(ARTIFACTS[kind][0]).resolve()
    tools = toolchain(msvc, sdk, version)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source_copy = output / source.name
    source_copy.write_bytes(source.read_bytes())
    source_hash = digest(source_copy)
    environment = compile_image(tools, source_copy, kind=kind)
    compiler = tools[0]
    executable = output / ARTIFACTS[kind][1]
    inspector, imports = inspect_image(compiler, executable, environment, kind=kind)
    if digest(source_copy) != source_hash:
        raise RuntimeError("native fixture source changed during compilation")
    manifest = {"schema": 1, "architecture": "x64", "crt": "static",
                "source_sha256": source_hash, "image_sha256": digest(executable),
                "compiler_sha256": digest(compiler), "sdk_version": version,
                "inspector_sha256": digest(inspector), "imported_dlls": imports,
                "compiler_flags": ["/W4", "/WX", "/O2", "/MT", "/GS", "/guard:cf"],
                "execution": "not_run", "native_acceptance": "not_verified",
                "dependency_trust": "not_verified"}
    if kind == "uia":
        manifest.update(schema=2, fixture_kind="uia", executable=executable.name,
                        uia_exposure="not_verified", foreground_noninterference="not_verified")
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--msvc", type=Path, required=True)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--sdk-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--kind", choices=tuple(ARTIFACTS), default="memory")
    options = parser.parse_args()
    print(build(options.msvc, options.sdk, options.sdk_version, options.output, kind=options.kind))

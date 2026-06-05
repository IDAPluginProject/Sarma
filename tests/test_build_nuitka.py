from __future__ import annotations

import importlib.util
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_nuitka", ROOT / "scripts" / "build_nuitka.py"
)
assert SPEC is not None
assert SPEC.loader is not None
build_nuitka = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_nuitka)


def _args(target_platform: str) -> Namespace:
    return Namespace(
        target_platform=target_platform,
        windows_runtime_dlls="yes",
        mingw64=False,
        macos_target_arch="native",
    )


def test_linux_arm64_uses_clang_and_lld(monkeypatch) -> None:
    monkeypatch.setattr(build_nuitka.platform, "machine", lambda: "aarch64")
    args = _args("linux")

    assert build_nuitka._platform_options(args) == [
        "--static-libpython=no",
        "--clang",
    ]

    env = build_nuitka._build_environment(args)
    assert env is not None
    assert env["CC"] == "clang"
    assert env["CXX"] == "clang++"
    assert "-fuse-ld=lld" in env["LDFLAGS"].split()


def test_linux_x86_64_does_not_force_clang(monkeypatch) -> None:
    monkeypatch.setattr(build_nuitka.platform, "machine", lambda: "x86_64")
    args = _args("linux")

    assert build_nuitka._platform_options(args) == ["--static-libpython=no"]
    assert build_nuitka._build_environment(args) is None

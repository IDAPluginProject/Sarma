"""Build, smoke test, and package a native Sarma release artifact."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NUITKA_ROOT = ROOT / "dist" / "nuitka"


def _host_platform() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    raise SystemExit(f"Unsupported platform: {sys.platform}")


def _host_arch() -> str:
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        return "x86_64"
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    return machine or "unknown"


def _default_formats(platform_name: str) -> str:
    if platform_name == "windows":
        return "msi"
    if platform_name == "macos":
        return "pkg"
    if platform_name == "linux":
        return "deb,pkg"
    raise SystemExit(f"Unsupported package platform: {platform_name}")


def _formats(formats: str) -> set[str]:
    return {item.strip().lower() for item in formats.split(",") if item.strip()}


def _prepend_path(path: Path) -> None:
    os.environ["PATH"] = str(path) + os.pathsep + os.environ.get("PATH", "")


def _find_wix() -> str | None:
    wix = shutil.which("wix")
    if wix:
        return wix
    tools_dir = Path.home() / ".dotnet" / "tools"
    candidate = tools_dir / "wix.exe"
    if candidate.is_file():
        _prepend_path(tools_dir)
        return str(candidate)
    return None


def _require_command(command: str, install_hint: str) -> None:
    if shutil.which(command):
        return
    raise SystemExit(f"Missing required command: {command}. {install_hint}")


def _check_package_tools(platform_name: str, formats: str) -> None:
    requested = _formats(formats)
    if platform_name == "windows" and "msi" in requested and not _find_wix():
        dotnet_hint = (
            "Install the .NET SDK first if 'dotnet' is missing: "
            "winget install --id Microsoft.DotNet.SDK.8 --exact --source winget. "
        )
        raise SystemExit(
            "Missing required command: wix. "
            f"{dotnet_hint}"
            "Then install WiX Toolset: dotnet tool install --global wix. "
            "Or run: scripts\\install_windows_packaging_tools.ps1"
        )
    if platform_name == "macos" and "pkg" in requested:
        _require_command("pkgbuild", "Install Apple command line tools first.")
    if platform_name == "linux":
        if "deb" in requested:
            _require_command("dpkg-deb", "Install dpkg packaging tools first.")
        if "pkg" in requested:
            _require_command("zstd", "Install zstd first.")


def _nuitka_platform_dir(platform_name: str, arch: str) -> Path:
    machine = {
        ("windows", "x86_64"): "amd64",
        ("linux", "x86_64"): "x86_64",
        ("linux", "arm64"): "aarch64",
        ("macos", "arm64"): "arm64",
        ("macos", "x86_64"): "x86_64",
    }.get((platform_name, arch), arch)
    return NUITKA_ROOT / f"{platform_name}-{machine}"


def _binary_path(platform_name: str, arch: str) -> Path:
    binary_name = "sarma.exe" if platform_name == "windows" else "sarma"
    binary = _nuitka_platform_dir(platform_name, arch) / binary_name
    if binary.is_file():
        return binary

    candidates = sorted(
        _nuitka_platform_dir(platform_name, arch).rglob(binary_name),
        key=lambda item: len(item.parts),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return binary


def _run(command: list[str]) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.check_call(command, cwd=ROOT)


def _run_tests() -> None:
    _run([sys.executable, "-m", "compileall", "-q", "src", "tests", "scripts"])
    _run([
        sys.executable,
        "-m",
        "pytest",
        "tests/test_build_nuitka.py",
        "tests/test_runtime_boundaries.py",
        "-q",
    ])


def _build(args: argparse.Namespace, platform_name: str, arch: str) -> None:
    command = [
        sys.executable,
        "scripts/build_nuitka.py",
        "--target-platform",
        platform_name,
        "--mode",
        args.mode,
        "--jobs",
        str(args.jobs),
    ]
    if platform_name == "macos":
        command.extend(["--macos-target-arch", arch])
    if args.show_command:
        command.append("--show-command")
    _run(command)


def _smoke_test(platform_name: str, arch: str) -> None:
    binary = _binary_path(platform_name, arch)
    if not binary.is_file():
        raise SystemExit(f"Built binary not found: {binary}")
    _run([str(binary), "--help"])


def _package(platform_name: str, arch: str, formats: str) -> None:
    _run([
        sys.executable,
        "scripts/package_native.py",
        "--platform",
        platform_name,
        "--arch",
        arch,
        "--formats",
        formats,
    ])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the native release build pipeline for the current host."
    )
    parser.add_argument(
        "--platform",
        choices=("auto", "windows", "linux", "macos"),
        default="auto",
        help="Target platform. Must match the host unless --skip-build is used.",
    )
    parser.add_argument(
        "--arch",
        choices=("auto", "x86_64", "arm64"),
        default="auto",
        help="Target architecture. Defaults to host architecture.",
    )
    parser.add_argument(
        "--formats",
        default=None,
        help="Comma-separated package formats. Defaults by platform.",
    )
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    parser.add_argument(
        "--mode",
        choices=("onefile", "standalone"),
        default="onefile",
        help="Nuitka build mode.",
    )
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-smoke", action="store_true")
    parser.add_argument("--skip-package", action="store_true")
    parser.add_argument("--show-command", action="store_true")
    args = parser.parse_args()

    platform_name = _host_platform() if args.platform == "auto" else args.platform
    arch = _host_arch() if args.arch == "auto" else args.arch
    formats = args.formats or _default_formats(platform_name)

    if not args.skip_package:
        _check_package_tools(platform_name, formats)
    if not args.skip_tests:
        _run_tests()
    if not args.skip_build:
        _build(args, platform_name, arch)
    if not args.skip_smoke:
        _smoke_test(platform_name, arch)
    if not args.skip_package:
        _package(platform_name, arch, formats)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

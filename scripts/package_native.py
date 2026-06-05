"""Package Nuitka-built Sarma binaries into native installers."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NUITKA_ROOT = ROOT / "dist" / "nuitka"
DEFAULT_PACKAGE_DIR = ROOT / "dist" / "packages"
APP_ID = "org.sarma.cli"
UPGRADE_CODE = "7f8ccf7f-80e8-4d09-b7e2-ef0d41a2b74b"


def _project_version() -> str:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(pyproject["project"]["version"])


def _host_platform() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    raise SystemExit(f"Unsupported package platform: {sys.platform}")


def _host_arch() -> str:
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        return "x86_64"
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    return machine or "unknown"


def _nuitka_platform_dir(platform_name: str, arch: str) -> Path:
    machine = {
        ("windows", "x86_64"): "amd64",
        ("linux", "x86_64"): "x86_64",
        ("linux", "arm64"): "aarch64",
        ("macos", "arm64"): "arm64",
    }.get((platform_name, arch), arch)
    return DEFAULT_NUITKA_ROOT / f"{platform_name}-{machine}"


def _find_binary(nuitka_dir: Path, platform_name: str) -> Path:
    name = "sarma.exe" if platform_name == "windows" else "sarma"
    candidates = sorted(nuitka_dir.rglob(name), key=lambda item: len(item.parts))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit(f"No {name} found under {nuitka_dir}. Build with Nuitka first.")


def _copy_executable(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    if os.name != "nt":
        mode = dst.stat().st_mode
        dst.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _archive_name(version: str, platform_name: str, arch: str, suffix: str) -> str:
    return f"sarma-{version}-{platform_name}-{arch}{suffix}"


def package_archive(binary: Path, out_dir: Path, version: str, platform_name: str, arch: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    if platform_name == "windows":
        out = out_dir / _archive_name(version, platform_name, arch, ".zip")
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(binary, "sarma.exe")
            zf.write(ROOT / "LICENSE", "LICENSE")
            zf.write(ROOT / "README.md", "README.md")
        return out

    out = out_dir / _archive_name(version, platform_name, arch, ".tar.gz")
    with tarfile.open(out, "w:gz") as tf:
        tf.add(binary, "sarma")
        tf.add(ROOT / "LICENSE", "LICENSE")
        tf.add(ROOT / "README.md", "README.md")
    return out


def package_deb(binary: Path, out_dir: Path, version: str, arch: str) -> Path:
    deb_arch = {"x86_64": "amd64", "arm64": "arm64"}.get(arch, arch)
    package_root = out_dir / "work" / f"deb-{deb_arch}"
    if package_root.exists():
        shutil.rmtree(package_root)
    control_dir = package_root / "DEBIAN"
    bin_dir = package_root / "usr" / "local" / "bin"
    control_dir.mkdir(parents=True)
    _copy_executable(binary, bin_dir / "sarma")
    (control_dir / "control").write_text(
        "\n".join([
            "Package: sarma",
            f"Version: {version}",
            "Section: utils",
            "Priority: optional",
            f"Architecture: {deb_arch}",
            "Maintainer: Sarma Contributors",
            "Description: Sarma vulnerability audit terminal agent",
            "",
        ]),
        encoding="utf-8",
    )
    out = out_dir / _archive_name(version, "linux", arch, ".deb")
    subprocess.check_call(["dpkg-deb", "--build", str(package_root), str(out)])
    return out


def package_arch_pkg(binary: Path, out_dir: Path, version: str, arch: str) -> Path:
    pkg_arch = {"x86_64": "x86_64", "arm64": "aarch64"}.get(arch, arch)
    package_root = out_dir / "work" / f"archpkg-{pkg_arch}"
    if package_root.exists():
        shutil.rmtree(package_root)
    bin_dir = package_root / "usr" / "local" / "bin"
    _copy_executable(binary, bin_dir / "sarma")
    (package_root / ".PKGINFO").write_text(
        "\n".join([
            "pkgname = sarma",
            f"pkgver = {version}-1",
            "pkgdesc = Sarma vulnerability audit terminal agent",
            "url = https://github.com/Captain-AI-Hub/Sarma",
            "builddate = 0",
            "packager = Sarma Contributors",
            f"arch = {pkg_arch}",
            "license = MIT",
            "",
        ]),
        encoding="utf-8",
    )
    tar_path = out_dir / "work" / _archive_name(version, "linux", arch, ".pkg.tar")
    out = out_dir / _archive_name(version, "linux", arch, ".pkg.tar.zst")
    with tarfile.open(tar_path, "w") as tf:
        for path in sorted(package_root.rglob("*")):
            tf.add(path, path.relative_to(package_root).as_posix())
    subprocess.check_call(["zstd", "-f", "-19", str(tar_path), "-o", str(out)])
    tar_path.unlink(missing_ok=True)
    return out


def package_pkg(binary: Path, out_dir: Path, version: str, arch: str) -> Path:
    root = out_dir / "work" / f"pkg-{arch}"
    if root.exists():
        shutil.rmtree(root)
    _copy_executable(binary, root / "usr" / "local" / "bin" / "sarma")
    out = out_dir / _archive_name(version, "macos", arch, ".pkg")
    subprocess.check_call([
        "pkgbuild",
        "--root",
        str(root),
        "--identifier",
        APP_ID,
        "--version",
        version,
        "--install-location",
        "/",
        str(out),
    ])
    return out


def package_msi(binary: Path, out_dir: Path, version: str, arch: str) -> Path:
    wix = shutil.which("wix")
    if not wix:
        raise SystemExit("wix not found. Install WiX Toolset first: dotnet tool install --global wix")
    work = out_dir / "work" / f"msi-{arch}"
    work.mkdir(parents=True, exist_ok=True)
    wxs = work / "sarma.wxs"
    source = str(binary).replace("\\", "\\\\")
    wxs.write_text(
        f"""<Wix xmlns="http://wixtoolset.org/schemas/v4/wxs">
  <Package Name="Sarma" Manufacturer="Sarma Contributors" Version="{version}" UpgradeCode="{UPGRADE_CODE}" Scope="perMachine">
    <MajorUpgrade DowngradeErrorMessage="A newer version of Sarma is already installed." />
    <MediaTemplate EmbedCab="yes" />
    <StandardDirectory Id="ProgramFiles64Folder">
      <Directory Id="INSTALLFOLDER" Name="Sarma">
        <Component Id="SarmaExeComponent" Guid="*">
          <File Id="SarmaExe" Source="{source}" KeyPath="yes" />
          <Environment Id="AddSarmaToPath" Name="PATH" Value="[INSTALLFOLDER]" Permanent="no" Part="last" Action="set" System="yes" />
        </Component>
      </Directory>
    </StandardDirectory>
    <Feature Id="MainFeature" Title="Sarma" Level="1">
      <ComponentRef Id="SarmaExeComponent" />
    </Feature>
  </Package>
</Wix>
""",
        encoding="utf-8",
    )
    out = out_dir / _archive_name(version, "windows", arch, ".msi")
    subprocess.check_call([wix, "build", str(wxs), "-arch", "x64", "-out", str(out)])
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Package Sarma Nuitka artifacts.")
    parser.add_argument("--platform", choices=("auto", "windows", "linux", "macos"), default="auto")
    parser.add_argument("--arch", default="auto")
    parser.add_argument("--nuitka-dir", default=None)
    parser.add_argument("--out-dir", default=str(DEFAULT_PACKAGE_DIR))
    parser.add_argument(
        "--formats",
        required=True,
        help="Comma-separated formats: archive, deb, pkg, msi.",
    )
    args = parser.parse_args()

    platform_name = _host_platform() if args.platform == "auto" else args.platform
    arch = _host_arch() if args.arch == "auto" else args.arch
    version = _project_version()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    nuitka_dir = Path(args.nuitka_dir).resolve() if args.nuitka_dir else _nuitka_platform_dir(platform_name, arch)
    binary = _find_binary(nuitka_dir, platform_name)

    formats = tuple(
        item.strip().lower() for item in args.formats.split(",") if item.strip()
    )
    if not formats:
        raise SystemExit("--formats must include at least one package format.")
    built: list[Path] = []
    for fmt in formats:
        if fmt == "archive":
            built.append(package_archive(binary, out_dir, version, platform_name, arch))
        elif fmt == "deb":
            built.append(package_deb(binary, out_dir, version, arch))
        elif fmt == "pkg":
            if platform_name == "macos":
                built.append(package_pkg(binary, out_dir, version, arch))
            elif platform_name == "linux":
                built.append(package_arch_pkg(binary, out_dir, version, arch))
            else:
                raise SystemExit("pkg format is supported on macos and linux only.")
        elif fmt == "msi":
            built.append(package_msi(binary, out_dir, version, arch))
        else:
            raise SystemExit(f"Unknown package format: {fmt}")

    for path in built:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

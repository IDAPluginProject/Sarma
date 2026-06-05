"""Build Sarma with Nuitka.

Nuitka does not provide practical cross-compilation for this CLI. Build each
artifact on the target OS:

    uv run --group build python scripts/build_nuitka.py
    uv run --group build python scripts/build_nuitka.py --mode standalone
"""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "src" / "main.py"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "nuitka"
CSS_FILE = ROOT / "src" / "sarma_cli" / "tui" / "main_app.css"

INCLUDE_PACKAGES = (
    "sarma_cli",
    "langchain",
    "langchain_core",
    "langchain_openai",
    "langchain_anthropic",
    "langchain_mcp_adapters",
    "langgraph",
    "langgraph_checkpoint",
    "deepagents",
    "textual",
    "rich",
    "pydantic",
    "click",
)

INCLUDE_DISTRIBUTION_METADATA = (
    "langchain",
    "langchain-core",
    "langchain-openai",
    "langchain-anthropic",
    "langchain-mcp-adapters",
    "langgraph",
    "langgraph-checkpoint",
    "deepagents",
    "textual",
    "rich",
    "pydantic",
    "click",
)


def _host_platform() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    raise SystemExit(f"Unsupported platform for Nuitka build: {sys.platform}")


def _project_version() -> str:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]
    parts = version.split(".")
    while len(parts) < 4:
        parts.append("0")
    return ".".join(parts[:4])


def _module_exists(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _metadata_exists(distribution_name: str) -> bool:
    try:
        importlib.metadata.version(distribution_name)
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


def _distribution_related_modules(distribution_name: str) -> tuple[str, ...]:
    """Return import package names provided by a distribution.

    Nuitka requires included distribution metadata to have a related included
    package. Local source distributions such as ``sarma-cli`` may not appear in
    ``packages_distributions()``, so they must be skipped instead of passed as a
    hyphenated package name.
    """
    package_map = importlib.metadata.packages_distributions()
    related = [
        package
        for package, distributions in package_map.items()
        if distribution_name in distributions
    ]
    return tuple(sorted(related))


def _module_or_exit(module_name: str, install_hint: str) -> None:
    if _module_exists(module_name):
        return
    raise SystemExit(
        f"Missing Python module '{module_name}'. {install_hint}"
    )


def _platform_output_dir(target_platform: str) -> Path:
    machine = platform.machine().lower() or "unknown"
    return DEFAULT_OUTPUT_DIR / f"{target_platform}-{machine}"


def _platform_options(args: argparse.Namespace) -> list[str]:
    options: list[str] = []
    if args.target_platform == "windows":
        options.extend([
            "--windows-console-mode=force",
            f"--include-windows-runtime-dlls={args.windows_runtime_dlls}",
        ])
        if args.mingw64:
            options.append("--mingw64")
    elif args.target_platform == "macos":
        macos_arch = args.macos_target_arch
        if macos_arch == "native":
            machine = platform.machine().lower()
            macos_arch = "arm64" if machine in {"arm64", "aarch64"} else "x86_64"
        options.append(f"--macos-target-arch={macos_arch}")
    elif args.target_platform == "linux":
        # Keep the binary CLI-shaped; desktop/app-bundle options are not useful
        # for Sarma's terminal UI.
        options.append("--static-libpython=no")
    return options


def _nuitka_command(args: argparse.Namespace) -> list[str]:
    output_dir = Path(args.output_dir).resolve()
    output_name = "sarma"
    command = [
        sys.executable,
        "-m",
        "nuitka",
        "--standalone",
        f"--output-dir={output_dir}",
        f"--output-filename={output_name}",
        f"--jobs={args.jobs}",
        f"--lto={args.lto}",
        "--product-name=Sarma",
        f"--file-version={_project_version()}",
        f"--product-version={_project_version()}",
        "--remove-output",
        "--noinclude-pytest-mode=nofollow",
        "--noinclude-unittest-mode=nofollow",
        "--nofollow-import-to=pytest",
        "--nofollow-import-to=_pytest",
        "--nofollow-import-to=*.tests",
        "--nofollow-import-to=langsmith.testing",
    ]

    if args.mode == "onefile":
        command.append("--onefile")

    if args.assume_downloads:
        command.append("--assume-yes-for-downloads")

    command.extend(_platform_options(args))

    included_packages: set[str] = set()
    for package_name in INCLUDE_PACKAGES:
        if _module_exists(package_name):
            command.append(f"--include-package={package_name}")
            included_packages.add(package_name)

    for distribution_name in INCLUDE_DISTRIBUTION_METADATA:
        if not _metadata_exists(distribution_name):
            continue
        related_modules = _distribution_related_modules(distribution_name)
        if any(module in included_packages for module in related_modules):
            command.append(f"--include-distribution-metadata={distribution_name}")

    if CSS_FILE.is_file():
        command.append(
            f"--include-data-file={CSS_FILE}=sarma_cli/tui/main_app.css"
        )

    command.append(str(ENTRY))
    return command


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the sarma executable with Nuitka."
    )
    parser.add_argument(
        "--mode",
        choices=("onefile", "standalone"),
        default="onefile",
        help="Build mode. onefile creates a single executable; standalone creates a folder.",
    )
    parser.add_argument(
        "--target-platform",
        choices=("auto", "windows", "linux", "macos"),
        default="auto",
        help="Target platform. Cross-compilation is not supported; default uses host OS.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Nuitka output directory. Defaults to dist/nuitka/<platform>-<arch>.",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=os.cpu_count() or 4,
        help="Parallel C compilation jobs.",
    )
    parser.add_argument(
        "--lto",
        choices=("auto", "yes", "no"),
        default="auto",
        help="Nuitka link-time optimization setting.",
    )
    parser.add_argument(
        "--no-assume-downloads",
        dest="assume_downloads",
        action="store_false",
        help="Do not let Nuitka auto-confirm helper downloads.",
    )
    parser.add_argument(
        "--show-command",
        action="store_true",
        help="Print the Nuitka command before running it.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the Nuitka command and exit without building.",
    )
    parser.add_argument(
        "--mingw64",
        action="store_true",
        help="Windows only: ask Nuitka to use MinGW64 instead of MSVC.",
    )
    parser.add_argument(
        "--windows-runtime-dlls",
        choices=("auto", "yes", "no"),
        default="yes",
        help=(
            "Windows only: include Microsoft C runtime DLLs. Defaults to yes "
            "because Nuitka auto detection can miss an installed redistributable."
        ),
    )
    parser.add_argument(
        "--macos-target-arch",
        choices=("native", "x86_64", "arm64"),
        default="native",
        help="macos only: target architecture for the generated executable.",
    )
    parser.set_defaults(assume_downloads=True)
    args = parser.parse_args()

    host_platform = _host_platform()
    if args.target_platform == "auto":
        args.target_platform = host_platform
    elif args.target_platform != host_platform:
        raise SystemExit(
            "Nuitka cross-compilation is not supported here. "
            f"Host is {host_platform}, target is {args.target_platform}."
        )

    if args.output_dir is None:
        args.output_dir = str(_platform_output_dir(args.target_platform))

    if not ENTRY.is_file():
        raise SystemExit(f"Missing entrypoint: {ENTRY}")

    if not args.dry_run:
        _module_or_exit(
            "nuitka",
            "Run through the wrapper scripts or use: "
            "uv run --group build python scripts/build_nuitka.py",
        )

    if shutil.which("ccache") is None and os.name != "nt":
        print("ccache not found; build will still work but may be slower.")

    command = _nuitka_command(args)
    if args.show_command or args.dry_run:
        print(" ".join(command))
    if args.dry_run:
        return 0

    return subprocess.call(command, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Update bundled plugins (ida_mcp, soff) from upstream sources.

Usage:
    python update_plugins.py [--ida-mcp] [--soff] [--all]

ida_mcp: Syncs from Captain-AI-Hub/IDA-MCP repo (main branch).
soff:    Downloads latest release binaries from Captain-AI-Hub/soff.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

RESOURCES_DIR = Path(__file__).resolve().parent
IDA_MCP_DIR = RESOURCES_DIR / "ida_mcp"
SOFF_DIR = RESOURCES_DIR / "soff"

IDA_MCP_REPO = "Captain-AI-Hub/IDA-MCP"
SOFF_REPO = "Captain-AI-Hub/soff"

# soff binary assets we bundle (IDA plugins only, not desktop/cli)
SOFF_ASSETS = [
    "soff-linux-x64.so",
    "soff-macos-arm64.dylib",
    "soff-windows-x64.dll",
]


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=True, **kwargs)


def _gh_api(endpoint: str) -> dict:
    """Call GitHub API via gh CLI."""
    result = subprocess.run(
        ["gh", "api", endpoint],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# ida_mcp update
# ---------------------------------------------------------------------------

def update_ida_mcp(branch: str = "main") -> None:
    """Sync ida_mcp/ from the IDA-MCP repository source tree."""
    print(f"\n[ida_mcp] Updating from {IDA_MCP_REPO} ({branch})...")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        clone_dir = tmp_path / "IDA-MCP"

        _run(["git", "clone", "--depth=1", "--branch", branch,
              f"https://github.com/{IDA_MCP_REPO}.git", str(clone_dir)])

        src = clone_dir / "ida_mcp"
        plugin_entry = clone_dir / "ida_mcp.py"

        if not src.exists():
            print(f"  ERROR: {src} not found in cloned repo.")
            sys.exit(1)

        # Remove old contents (preserve .gitignore)
        gitignore = IDA_MCP_DIR / ".gitignore"
        gitignore_content = gitignore.read_text() if gitignore.exists() else None

        for item in IDA_MCP_DIR.iterdir():
            if item.name == ".gitignore":
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

        # Copy new source
        shutil.copytree(src, IDA_MCP_DIR / "ida_mcp", dirs_exist_ok=True)
        if plugin_entry.exists():
            shutil.copy2(plugin_entry, IDA_MCP_DIR / "ida_mcp.py")

        # Restore .gitignore
        if gitignore_content:
            gitignore.write_text(gitignore_content)

    # Show version info
    version_file = IDA_MCP_DIR / "ida_mcp" / "__init__.py"
    if version_file.exists():
        for line in version_file.read_text().splitlines():
            if "__version__" in line:
                print(f"  Updated to {line.strip()}")
                break

    print("[ida_mcp] Done.")


# ---------------------------------------------------------------------------
# soff update
# ---------------------------------------------------------------------------

def update_soff() -> None:
    """Download latest soff IDA plugin binaries from GitHub releases."""
    print(f"\n[soff] Fetching latest release from {SOFF_REPO}...")

    release = _gh_api(f"repos/{SOFF_REPO}/releases/latest")
    tag = release.get("tag_name", "unknown")
    print(f"  Latest release: {tag}")

    assets = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}

    SOFF_DIR.mkdir(parents=True, exist_ok=True)

    for asset_name in SOFF_ASSETS:
        url = assets.get(asset_name)
        if not url:
            print(f"  SKIP: {asset_name} (not found in release)")
            continue

        dest = SOFF_DIR / asset_name
        print(f"  Downloading {asset_name}...")
        urllib.request.urlretrieve(url, str(dest))
        print(f"  Saved → {dest.relative_to(RESOURCES_DIR)}")

    # Write version marker
    (SOFF_DIR / ".version").write_text(tag + "\n")
    print(f"[soff] Done — {tag}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Update bundled Sarma plugins.")
    parser.add_argument("--ida-mcp", action="store_true", help="Update ida_mcp from source.")
    parser.add_argument("--soff", action="store_true", help="Update soff binaries from release.")
    parser.add_argument("--all", action="store_true", help="Update all plugins.")
    parser.add_argument("--branch", default="main", help="IDA-MCP branch (default: main).")
    args = parser.parse_args()

    if not (args.ida_mcp or args.soff or args.all):
        args.all = True

    if args.all or args.ida_mcp:
        update_ida_mcp(branch=args.branch)

    if args.all or args.soff:
        update_soff()

    print("\nAll updates complete.")


if __name__ == "__main__":
    main()

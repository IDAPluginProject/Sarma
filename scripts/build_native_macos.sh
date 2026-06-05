#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

if ! command -v uv >/dev/null 2>&1; then
    echo "Missing required command: uv"
    echo "Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

cd "$ROOT_DIR"
exec uv run --group dev --group build python scripts/build_native_release.py \
    --platform macos \
    "$@"

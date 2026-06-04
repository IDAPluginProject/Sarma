#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
INSTALL_DIR=${INSTALL_DIR:-/usr/local/bin}
BUILD_ROOT=${BUILD_ROOT:-"$ROOT_DIR/dist/nuitka"}

case "$(uname -s)" in
    Linux|Darwin) ;;
    *)
        echo "install.sh supports Linux and macos only. Use install.ps1 on Windows."
        exit 1
        ;;
esac

find_sarma() {
    find "$BUILD_ROOT" -type f -name sarma -perm -111 2>/dev/null | sort | tail -n 1
}

BIN_PATH=${SARMA_BIN:-$(find_sarma)}
if [ -z "${BIN_PATH:-}" ] || [ ! -f "$BIN_PATH" ]; then
    echo "No sarma executable found under $BUILD_ROOT."
    echo "Build first: scripts/build_nuitka.sh"
    exit 1
fi

if [ ! -d "$INSTALL_DIR" ]; then
    echo "Install directory does not exist: $INSTALL_DIR"
    exit 1
fi

DEST="$INSTALL_DIR/sarma"
if [ -w "$INSTALL_DIR" ]; then
    install -m 0755 "$BIN_PATH" "$DEST"
else
    sudo install -m 0755 "$BIN_PATH" "$DEST"
fi

echo "Installed $DEST"

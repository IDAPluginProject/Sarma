"""Sarma CLI launcher — run directly with `python main.py`."""

import sys
from pathlib import Path

# Ensure ide/ is on sys.path for shared/app module reuse.
_IDE_ROOT = Path(__file__).resolve().parent.parent / "ide"
if str(_IDE_ROOT) not in sys.path:
    sys.path.insert(0, str(_IDE_ROOT))

# Ensure sarma_cli package is importable.
_CLI_ROOT = Path(__file__).resolve().parent
if str(_CLI_ROOT) not in sys.path:
    sys.path.insert(0, str(_CLI_ROOT))

from sarma_cli.__main__ import main

if __name__ == "__main__":
    main()

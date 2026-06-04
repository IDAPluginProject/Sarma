"""Line-based input history for the full-screen TUI."""

from __future__ import annotations

from pathlib import Path

from sarma_cli import paths

MAX_HISTORY_ENTRIES = 500


def history_path() -> Path:
    return paths.input_history_file()


def load_input_history(path: Path | None = None) -> list[str]:
    target = path or history_path()
    if not target.exists():
        return []
    lines = [
        line.strip()
        for line in target.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return _dedupe_keep_order(lines)[-MAX_HISTORY_ENTRIES:]


def append_input_history(line: str, path: Path | None = None) -> None:
    entry = line.strip()
    if not entry:
        return
    target = path or history_path()
    entries = load_input_history(target)
    if entries and entries[-1] == entry:
        return
    entries.append(entry)
    entries = _dedupe_keep_order(entries)[-MAX_HISTORY_ENTRIES:]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(entries) + "\n", encoding="utf-8")


def _dedupe_keep_order(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        if line in seen:
            result.remove(line)
        seen.add(line)
        result.append(line)
    return result

from __future__ import annotations

from pathlib import Path
from typing import Dict


def _read_if_exists(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def read_task_bundle(tasks_dir: Path) -> Dict[str, str]:
    tasks_dir = tasks_dir.resolve()
    return {
        "task.md": _read_if_exists(tasks_dir / "task.md"),
        "context.md": _read_if_exists(tasks_dir / "context.md"),
        "mid-task-changes.md": _read_if_exists(tasks_dir / "mid-task-changes.md"),
    }

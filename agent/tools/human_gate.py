from __future__ import annotations

import time
from pathlib import Path


def wait_for_continue(tasks_dir: Path, *, poll_sec: float = 2.0) -> None:
    """
    Blocks until tasks/continue.txt contains the word 'continue' (case-insensitive).
    Human can also delete/clear the file to keep it paused.
    """
    tasks_dir = tasks_dir.resolve()
    signal = tasks_dir / "continue.txt"

    while True:
        if signal.exists():
            txt = signal.read_text(encoding="utf-8", errors="replace").strip().lower()
            if "continue" in txt:
                # reset for next time
                try:
                    signal.write_text("", encoding="utf-8")
                except Exception:
                    pass
                return
        time.sleep(poll_sec)

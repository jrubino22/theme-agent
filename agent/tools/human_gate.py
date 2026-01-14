from __future__ import annotations

import time
from pathlib import Path


def wait_for_continue(tasks_dir: Path, *, poll_sec: float = 2.0) -> str:
    """
    Blocks until tasks/continue.txt contains the word 'continue' (case-insensitive).
    Returns any additional text in the file as human notes.
    """
    tasks_dir = tasks_dir.resolve()
    signal = tasks_dir / "continue.md"

    while True:
        if signal.exists():
            raw = signal.read_text(encoding="utf-8", errors="replace").strip()
            low = raw.lower()
            if "continue" in low:
                # everything except the word "continue" becomes notes
                notes = raw.replace("continue", "").replace("CONTINUE", "").strip()

                try:
                    signal.write_text("", encoding="utf-8")
                except Exception:
                    pass

                return notes
        time.sleep(poll_sec)

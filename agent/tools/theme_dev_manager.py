from __future__ import annotations

import os
import re
import selectors
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class ThemeDevError(RuntimeError):
    pass


# How long we wait for a "ready" signal from shopify theme dev
DEFAULT_READY_TIMEOUT_SEC = int(os.environ.get("THEME_DEV_READY_TIMEOUT_SEC", "90"))

# Patterns that indicate the dev server is up / serving
READY_PATTERNS = [
    re.compile(r"\bPreview\b", re.IGNORECASE),
    re.compile(r"\bListening\b", re.IGNORECASE),
    re.compile(r"\bLocal\b", re.IGNORECASE),
    re.compile(r"\b127\.0\.0\.1\b"),
    re.compile(r"\blocalhost\b", re.IGNORECASE),
    re.compile(r"http://", re.IGNORECASE),
    re.compile(r"https://", re.IGNORECASE),
    re.compile(r"\bServing\b", re.IGNORECASE),
    re.compile(r"\bCompiled\b", re.IGNORECASE),
]


@dataclass
class ThemeDevProcess:
    proc: subprocess.Popen

    def stop(self) -> None:
        try:
            self.proc.terminate()
        except Exception:
            pass


def start_theme_dev(*, theme_root: Path, host: str = "0.0.0.0", port: int = 9292) -> ThemeDevProcess:
    """
    Start `shopify theme dev` in the given theme_root.
    """
    cmd = [
        "shopify",
        "theme",
        "dev",
        "--path",
        str(theme_root),
        "--host",
        host,
        "--port",
        str(port),
    ]

    # NOTE: Shopify CLI often writes important info to stderr.
    proc = subprocess.Popen(
        cmd,
        cwd=str(theme_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    if proc.stdout is None or proc.stderr is None:
        raise ThemeDevError("Failed to start shopify theme dev (missing stdout/stderr pipes).")

    return ThemeDevProcess(proc=proc)


def read_theme_dev_output(dev: ThemeDevProcess, *, timeout_sec: int = DEFAULT_READY_TIMEOUT_SEC) -> str:
    """
    Read output from both stdout and stderr until we detect the dev server is ready,
    or until timeout. Echoes lines as they arrive for debugging.
    """
    proc = dev.proc
    assert proc.stdout is not None
    assert proc.stderr is not None

    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ, data="stdout")
    sel.register(proc.stderr, selectors.EVENT_READ, data="stderr")

    start = time.time()
    buf_lines: list[str] = []

    def _is_ready(line: str) -> bool:
        return any(p.search(line) for p in READY_PATTERNS)

    # Loop until ready, exit, or timeout
    while True:
        # If process exited, stop and raise with captured output
        rc = proc.poll()
        if rc is not None:
            tail = "".join(buf_lines[-80:])
            raise ThemeDevError(f"shopify theme dev exited early (code={rc}). Output tail:\n{tail}")

        if (time.time() - start) > timeout_sec:
            tail = "".join(buf_lines[-80:])
            raise ThemeDevError(
                f"Timed out waiting for shopify theme dev to become ready after {timeout_sec}s.\n"
                f"Output tail:\n{tail}"
            )

        events = sel.select(timeout=0.5)
        if not events:
            continue

        for key, _ in events:
            stream_name = key.data  # "stdout" or "stderr"
            f = key.fileobj

            line = f.readline()
            if not line:
                continue

            # store + echo
            buf_lines.append(f"[{stream_name}] {line}")
            print(f"[theme-dev {stream_name}] {line}", end="")

            if _is_ready(line):
                # Give it a tiny moment to keep printing the full URLs
                time.sleep(0.2)
                # Drain any immediately-available lines
                drain_until = time.time() + 0.5
                while time.time() < drain_until:
                    more = sel.select(timeout=0.05)
                    if not more:
                        break
                    for k2, _ in more:
                        f2 = k2.fileobj
                        stream2 = k2.data
                        ln2 = f2.readline()
                        if ln2:
                            buf_lines.append(f"[{stream2}] {ln2}")
                            print(f"[theme-dev {stream2}] {ln2}", end="")
                return "".join(buf_lines)

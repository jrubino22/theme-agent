from __future__ import annotations

import os
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List


class ThemeDevError(RuntimeError):
    pass


def _shopify_env_guard() -> None:
    if not os.environ.get("SHOPIFY_FLAG_STORE"):
        raise ThemeDevError("SHOPIFY_FLAG_STORE is required to run shopify theme dev.")


def _wait_for_port(host: str, port: int, timeout_sec: int = 60) -> None:
    start = time.time()
    while time.time() - start < timeout_sec:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except Exception:
            time.sleep(1)
    raise ThemeDevError(f"Timed out waiting for theme dev server on {host}:{port}")


@dataclass
class ThemeDevProcess:
    proc: subprocess.Popen
    host: str
    port: int

    def stop(self) -> None:
        try:
            self.proc.terminate()
        except Exception:
            pass


def start_theme_dev(*, theme_root: Path, host: str = "0.0.0.0", port: int = 9292) -> ThemeDevProcess:
    _shopify_env_guard()

    cmd: List[str] = ["shopify", "theme", "dev", "--host", host, "--port", str(port)]

    # Important: use env from container; BROWSER=echo prevents browser open attempts.
    proc = subprocess.Popen(
        cmd,
        cwd=str(theme_root),
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    # Wait until the service is reachable from inside the container.
    # For the agent + playwright inside same container, use 127.0.0.1.
    _wait_for_port("127.0.0.1", port, timeout_sec=90)

    return ThemeDevProcess(proc=proc, host=host, port=port)


def read_theme_dev_output(dev: ThemeDevProcess, max_lines: int = 200) -> str:
    if not dev.proc.stdout:
        return ""
    lines = []
    for _ in range(max_lines):
        line = dev.proc.stdout.readline()
        if not line:
            break
        lines.append(line)
    return "".join(lines)

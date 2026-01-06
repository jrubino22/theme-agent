from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, Optional, List

@dataclass(frozen=True)
class CmdResult:
    cmd: List[str]
    returncode: int
    stdout: str
    stderr: str

class CommandNotAllowed(Exception):
    pass

def _normalize(cmd: Sequence[str]) -> str:
    # Used for allowlist matching
    return " ".join(cmd)

def run_allowed(
    cmd: Sequence[str],
    cwd: Path,
    allowed_prefixes: Sequence[Sequence[str]],
    timeout_sec: int = 120,
    env: Optional[dict] = None,
) -> CmdResult:
    cmd = list(cmd)

    ok = any(cmd[: len(prefix)] == list(prefix) for prefix in allowed_prefixes)
    if not ok:
        raise CommandNotAllowed(
            f"Command not allowed: {_normalize(cmd)}\n"
            f"Allowed prefixes:\n- " + "\n- ".join(_normalize(p) for p in allowed_prefixes)
        )

    p = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        env=env,
    )
    return CmdResult(cmd=cmd, returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)

def parse_cmdline(cmdline: str) -> List[str]:
    return shlex.split(cmdline)

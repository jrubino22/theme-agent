from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from agent.tools.cmd import run_allowed


def run_theme_check(
    theme_root: Path,
    *,
    artifacts_dir: Path,
    allowed_cmds: List[List[str]],
    timeout_sec: int = 180,
) -> Dict[str, str | bool]:
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    cmd = ["shopify", "theme", "check"]
    res = run_allowed(cmd, cwd=theme_root, allowed_prefixes=allowed_cmds, timeout_sec=timeout_sec)

    (artifacts_dir / "theme_check_stdout.txt").write_text(res.stdout, encoding="utf-8")
    (artifacts_dir / "theme_check_stderr.txt").write_text(res.stderr, encoding="utf-8")

    ok = res.returncode == 0
    summary = "ok" if ok else f"failed (rc={res.returncode})"
    return {"ok": ok, "summary": summary}

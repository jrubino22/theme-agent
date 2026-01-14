from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from agent.tools.cmd import run_allowed


def run_playwright_verify(
    *,
    theme_root: Path,
    artifacts_dir: Path,
    allowed_cmds: List[List[str]],
    timeout_sec: int,
    base_url: str,
    routes: List[str],
    asserts_path: Optional[str] = None,
    design_dir: Optional[str] = None,
) -> Dict[str, str | bool]:
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "node",
        "/app/agent/verify/verify.js",
        "--base-url",
        base_url,
        "--out-dir",
        str(artifacts_dir / "playwright"),
    ]
    if routes:
        cmd += ["--routes", ",".join(routes)]
    if asserts_path:
        cmd += ["--asserts", asserts_path]
    if design_dir:
        cmd += ["--design-dir", design_dir]

    res = run_allowed(cmd, cwd="/app/agent/verify", allowed_prefixes=allowed_cmds, timeout_sec=timeout_sec)
    (artifacts_dir / "playwright_stdout.txt").write_text(res.stdout, encoding="utf-8")
    (artifacts_dir / "playwright_stderr.txt").write_text(res.stderr, encoding="utf-8")

    ok = res.returncode == 0
    summary = "ok" if ok else f"failed (rc={res.returncode})"
    return {"ok": ok, "summary": summary}

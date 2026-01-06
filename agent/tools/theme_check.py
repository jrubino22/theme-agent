from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, Sequence

from agent.tools.cmd import run_allowed

def run_theme_check(workdir: Path, allowed_prefixes: Sequence[Sequence[str]]) -> Dict[str, Any]:
    """
    Runs `shopify theme check` in a theme directory.
    Returns structured results + raw output for artifacts.
    """
    # Quick sanity: show version in logs
    ver = run_allowed(["shopify", "version"], cwd=workdir, allowed_prefixes=allowed_prefixes, timeout_sec=60)

    res = run_allowed(
        ["shopify", "theme", "check"],
        cwd=workdir,
        allowed_prefixes=allowed_prefixes,
        timeout_sec=600,
    )

    return {
        "shopify_version_stdout": ver.stdout.strip(),
        "shopify_version_stderr": ver.stderr.strip(),
        "returncode": res.returncode,
        "stdout": res.stdout,
        "stderr": res.stderr,
    }
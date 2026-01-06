from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Dict, Any

def _run_rg_files_with_matches(workdir: Path, pattern: str, max_results: int) -> List[str]:
    try:
        p = subprocess.run(
            ["rg", "--files-with-matches", "--hidden", 
            "--glob", "!.git/*", 
            "--glob", "!.cursor/*",
            "--glob", "!node_modules/*",
            pattern, str(workdir)],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        raise RuntimeError("ripgrep (rg) not found. Install: brew install ripgrep")

    # rg returns 0 if matches, 1 if no matches, >1 for error
    if p.returncode not in (0, 1):
        return []
    files = [line.strip() for line in p.stdout.splitlines() if line.strip()]
    return files[:max_results]

def theme_structure_check(workdir: Path) -> Dict[str, Any]:
    required = ["sections", "snippets", "templates", "config"]
    present = {name: (workdir / name).is_dir() for name in required}
    return {
        "looks_like_theme": all(present.values()),
        "required_present": present,
    }

def top_level_dirs(workdir: Path) -> List[str]:
    return sorted([p.name for p in workdir.iterdir() if p.is_dir()])

def rg_hits(workdir: Path, patterns: List[str], max_files_per_pattern: int = 30) -> List[Dict[str, str]]:
    hits: List[Dict[str, str]] = []
    for pat in patterns:
        for f in _run_rg_files_with_matches(workdir, pat, max_files_per_pattern):
            hits.append({"pattern": pat, "file": f})
    return hits

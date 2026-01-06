from __future__ import annotations

import re
from typing import Dict

ERR_RE = re.compile(r"\[\s*error\s*\]", re.IGNORECASE)
WARN_RE = re.compile(r"\[\s*warning\s*\]", re.IGNORECASE)

def count_theme_check(stdout: str, stderr: str = "") -> Dict[str, int]:
    text = (stdout or "") + "\n" + (stderr or "")
    errors = len(ERR_RE.findall(text))
    warnings = len(WARN_RE.findall(text))
    return {"errors": errors, "warnings": warnings}

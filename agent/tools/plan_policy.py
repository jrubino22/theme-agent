from __future__ import annotations

from typing import Any, Dict, List, Set

DISALLOWED_PREFIXES = [
    ".git/",
    ".github/",
    ".cursor/",
    ".vscode/",
]

DISALLOWED_EXACT = {
    "config/settings_data.json",
}

ALLOWED_TOP_LEVEL_DIRS: Set[str] = {
    "assets",
    "blocks",
    "config",
    "layout",
    "locales",
    "sections",
    "snippets",
    "templates",
}

ALLOWED_OP_TYPES = {
    "insert_after",
    "insert_before",
    "replace_once",
    "create_file",
    "apply_patch",
}

# Extension rules for create_file
ALLOWED_CREATE_EXTS_BY_DIR = {
    "sections": {".liquid"},
    "snippets": {".liquid"},
    "blocks": {".liquid"},
    "layout": {".liquid"},
    "templates": {".json", ".liquid"},
    "assets": {".js", ".css", ".json", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".woff", ".woff2"},
    "config": {".json"},   # be careful, still blocked for settings_data.json via DISALLOWED_EXACT
    "locales": {".json"},
}


class PlanError(Exception):
    pass


def _norm_rel_path(p: str) -> str:
    p = p.replace("\\", "/").lstrip("/")
    while "//" in p:
        p = p.replace("//", "/")
    return p


def _is_safe_theme_path(rel: str) -> bool:
    rel = _norm_rel_path(rel)

    # traversal
    if rel.startswith("../") or "/../" in rel or rel in ("..", ""):
        return False

    top = rel.split("/", 1)[0]
    if top not in ALLOWED_TOP_LEVEL_DIRS:
        return False

    for pref in DISALLOWED_PREFIXES:
        if rel.startswith(pref):
            return False

    if rel in DISALLOWED_EXACT:
        return False

    return True


def _validate_create_ext(rel: str) -> None:
    rel = _norm_rel_path(rel)
    top = rel.split("/", 1)[0]
    exts = ALLOWED_CREATE_EXTS_BY_DIR.get(top)
    if not exts:
        raise PlanError(f"create_file not allowed in dir: {top}")
    dot = rel.rfind(".")
    ext = rel[dot:] if dot != -1 else ""
    if ext not in exts:
        raise PlanError(f"create_file extension not allowed for {top}: {ext or '(none)'}")


def validate_plan(
    plan: Dict[str, Any],
    *,
    max_ops: int = 30,
    max_creates: int = 12,
    max_total_written_chars: int = 250_000,
    require_reuse_analysis_for_creates: bool = True,
) -> Dict[str, Any]:
    """
    Validates plan structure and rejects unsafe operations.
    Returns normalized plan (paths normalized).
    """
    if not isinstance(plan, dict):
        raise PlanError("Plan must be a JSON object")

    ops = plan.get("ops")
    if not isinstance(ops, list) or not ops:
        raise PlanError("Plan must include non-empty 'ops' list")

    if len(ops) > max_ops:
        raise PlanError(f"Plan has too many ops ({len(ops)} > {max_ops})")

    creates = 0
    total_written = 0
    normalized_ops: List[Dict[str, Any]] = []

    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            raise PlanError(f"Op #{i} must be an object")

        t = op.get("type")
        if t not in ALLOWED_OP_TYPES:
            raise PlanError(f"Op #{i} has unsupported type: {t}")

        if t in {"insert_after", "insert_before", "replace_once", "create_file"}:
            path = op.get("path")
            if not isinstance(path, str) or not path.strip():
                raise PlanError(f"Op #{i} missing valid 'path'")
            path_norm = _norm_rel_path(path)
            if not _is_safe_theme_path(path_norm):
                raise PlanError(f"Op #{i} path is not allowed: {path_norm}")

            # Per-type checks
            if t == "create_file":
                creates += 1
                _validate_create_ext(path_norm)
                content = op.get("content")
                if not isinstance(content, str):
                    raise PlanError(f"Op #{i} missing valid 'content'")
                total_written += len(content)
            elif t == "replace_once":
                anchor = op.get("anchor")
                replacement = op.get("replacement")
                if not isinstance(anchor, str) or not anchor:
                    raise PlanError(f"Op #{i} missing valid 'anchor'")
                if not isinstance(replacement, str):
                    raise PlanError(f"Op #{i} missing valid 'replacement'")
                total_written += len(replacement)
                expect = op.get("expect_anchor_count", 1)
                if not isinstance(expect, int) or expect < 1:
                    raise PlanError(f"Op #{i} expect_anchor_count must be positive int")
            else:
                anchor = op.get("anchor")
                content = op.get("content")
                if not isinstance(anchor, str) or not anchor:
                    raise PlanError(f"Op #{i} missing valid 'anchor'")
                if not isinstance(content, str):
                    raise PlanError(f"Op #{i} missing valid 'content'")
                total_written += len(content)
                expect = op.get("expect_anchor_count", 1)
                if not isinstance(expect, int) or expect < 1:
                    raise PlanError(f"Op #{i} expect_anchor_count must be positive int")

            normalized = dict(op)
            normalized["path"] = path_norm
            normalized_ops.append(normalized)

        elif t == "apply_patch":
            patch = op.get("patch")
            if not isinstance(patch, str) or not patch.strip():
                raise PlanError(f"Op #{i} missing valid 'patch'")
            # We'll validate patch touches only safe paths at apply-time too.
            total_written += len(patch)

            normalized_ops.append(dict(op))

    if creates > max_creates:
        raise PlanError(f"Plan creates too many files ({creates} > {max_creates})")

    if total_written > max_total_written_chars:
        raise PlanError(
            f"Plan writes too much content ({total_written} chars > {max_total_written_chars})"
        )

    if require_reuse_analysis_for_creates and creates > 0:
        ra = plan.get("reuse_analysis")
        if not isinstance(ra, dict):
            raise PlanError("Plan includes create_file ops but missing 'reuse_analysis' object")
        just = ra.get("new_files_justification", "")
        if not isinstance(just, str) or len(just.strip()) < 120:
            raise PlanError(
                "Plan includes create_file ops but 'reuse_analysis.new_files_justification' is too short"
            )

    plan_norm = dict(plan)
    plan_norm["ops"] = normalized_ops
    return plan_norm

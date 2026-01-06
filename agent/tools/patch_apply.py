from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Set

from agent.tools.patch_unified import apply_unified_patch, PatchError


class ApplyError(Exception):
    pass


@dataclass
class ApplyResult:
    changed_files: List[str]
    created_files: List[str]
    applied_ops: List[Dict[str, Any]]


def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _write_text(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _count_occurrences(text: str, needle: str) -> int:
    return text.count(needle) if needle else 0


def _insert_after(text: str, anchor: str, content: str) -> str:
    idx = text.find(anchor)
    if idx == -1:
        raise ApplyError("Anchor not found")
    insert_at = idx + len(anchor)
    return text[:insert_at] + content + text[insert_at:]


def _insert_before(text: str, anchor: str, content: str) -> str:
    idx = text.find(anchor)
    if idx == -1:
        raise ApplyError("Anchor not found")
    return text[:idx] + content + text[idx:]


def _replace_once(text: str, anchor: str, replacement: str) -> str:
    idx = text.find(anchor)
    if idx == -1:
        raise ApplyError("Anchor not found")
    return text.replace(anchor, replacement, 1)


def apply_plan_ops(plan: Dict[str, Any], theme_root: Path) -> ApplyResult:
    ops = plan["ops"]
    changed: Set[str] = set()
    created: Set[str] = set()
    applied: List[Dict[str, Any]] = []

    for i, op in enumerate(ops):
        t = op["type"]

        if t == "apply_patch":
            patch = op["patch"]
            try:
                patched = apply_unified_patch(patch, theme_root)
            except PatchError as e:
                raise ApplyError(f"Op #{i} apply_patch failed: {e}") from e

            for rel in patched:
                changed.add(rel)

            applied.append({"type": t, "reason": op.get("reason", "")})
            continue

        # ops with explicit path
        rel = op["path"]
        target = (theme_root / rel).resolve()

        if t == "create_file":
            if target.exists():
                raise ApplyError(f"Op #{i}: create_file target already exists: {rel}")
            content = op["content"]
            _write_text(target, content)
            created.add(rel)
            changed.add(rel)
            applied.append({"type": t, "path": rel, "reason": op.get("reason", "")})
            continue

        # must exist for modify ops
        if not target.exists() or not target.is_file():
            raise ApplyError(f"Op #{i}: file does not exist: {rel}")

        original = _read_text(target)
        anchor = op["anchor"]
        expect = int(op.get("expect_anchor_count", 1))
        found = _count_occurrences(original, anchor)
        if found != expect:
            raise ApplyError(f"Op #{i} anchor occurrence mismatch in {rel} (found {found}, expected {expect})")

        if t == "insert_after":
            new_text = _insert_after(original, anchor, op["content"])
        elif t == "insert_before":
            new_text = _insert_before(original, anchor, op["content"])
        elif t == "replace_once":
            new_text = _replace_once(original, anchor, op["replacement"])
        else:
            raise ApplyError(f"Op #{i}: unsupported op type: {t}")

        if new_text != original:
            _write_text(target, new_text)
            changed.add(rel)

        applied.append(
            {
                "type": t,
                "path": rel,
                "anchor": anchor,
                "reason": op.get("reason", ""),
            }
        )

    return ApplyResult(
        changed_files=sorted(changed),
        created_files=sorted(created),
        applied_ops=applied,
    )

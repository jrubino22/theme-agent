from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from agent.tools.plan_policy import _norm_rel_path, _is_safe_theme_path


class PatchError(Exception):
    pass


@dataclass
class Hunk:
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    lines: List[str]  # includes leading ' ', '+', '-'


@dataclass
class FilePatch:
    path_old: str
    path_new: str
    hunks: List[Hunk]


def _parse_hunk_header(line: str) -> Tuple[int, int, int, int]:
    # @@ -a,b +c,d @@
    # b or d can be omitted => 1
    try:
        header = line.strip()
        if not header.startswith("@@"):
            raise ValueError("not a hunk header")
        mid = header.split("@@")[1].strip()  # "-a,b +c,d"
        left, right = mid.split(" ", 1)
        old = left.lstrip("-")
        new = right.strip().split(" ")[0].lstrip("+")
        old_start, old_len = (old.split(",") + ["1"])[:2]
        new_start, new_len = (new.split(",") + ["1"])[:2]
        return int(old_start), int(old_len), int(new_start), int(new_len)
    except Exception as e:
        raise PatchError(f"Bad hunk header: {line}") from e


def parse_unified_diff(patch_text: str) -> List[FilePatch]:
    lines = patch_text.splitlines()
    i = 0
    patches: List[FilePatch] = []

    current: Optional[FilePatch] = None
    current_hunks: List[Hunk] = []
    current_hunk: Optional[Hunk] = None

    def flush_hunk():
        nonlocal current_hunk, current_hunks
        if current_hunk is not None:
            current_hunks.append(current_hunk)
            current_hunk = None

    def flush_file():
        nonlocal current, current_hunks
        if current is not None:
            flush_hunk()
            current.hunks = current_hunks
            patches.append(current)
            current = None
            current_hunks = []

    while i < len(lines):
        line = lines[i]

        if line.startswith("diff --git "):
            flush_file()
            # diff --git a/path b/path
            parts = line.split()
            if len(parts) >= 4:
                a = parts[2]
                b = parts[3]
                path_old = a[2:] if a.startswith("a/") else a
                path_new = b[2:] if b.startswith("b/") else b
                current = FilePatch(path_old=path_old, path_new=path_new, hunks=[])
            else:
                raise PatchError(f"Malformed diff header: {line}")
            i += 1
            continue

        if current is None:
            # ignore preamble noise
            i += 1
            continue

        if line.startswith("--- "):
            i += 1
            continue

        if line.startswith("+++ "):
            i += 1
            continue

        if line.startswith("@@"):
            flush_hunk()
            old_start, old_len, new_start, new_len = _parse_hunk_header(line)
            current_hunk = Hunk(old_start, old_len, new_start, new_len, lines=[])
            i += 1
            continue

        if current_hunk is not None:
            if line.startswith((" ", "+", "-")):
                current_hunk.lines.append(line)
                i += 1
                continue
            # end of hunk on unexpected marker
            flush_hunk()
            continue

        i += 1

    flush_file()
    return patches


def _apply_hunks_to_text(original: str, hunks: List[Hunk]) -> str:
    src = original.splitlines(keepends=False)
    out: List[str] = []
    src_idx = 0  # 0-based

    for h in hunks:
        # h.old_start is 1-based
        target_idx = max(h.old_start - 1, 0)

        # copy unchanged lines up to hunk start
        while src_idx < target_idx:
            out.append(src[src_idx])
            src_idx += 1

        # apply hunk lines
        for hl in h.lines:
            if not hl:
                continue
            tag = hl[0]
            content = hl[1:]

            if tag == " ":
                # context must match
                if src_idx >= len(src) or src[src_idx] != content:
                    raise PatchError("Context mismatch while applying patch")
                out.append(src[src_idx])
                src_idx += 1
            elif tag == "-":
                # removed line must match
                if src_idx >= len(src) or src[src_idx] != content:
                    raise PatchError("Delete mismatch while applying patch")
                src_idx += 1
            elif tag == "+":
                out.append(content)
            else:
                raise PatchError(f"Unknown hunk tag: {tag}")

    # copy remainder
    while src_idx < len(src):
        out.append(src[src_idx])
        src_idx += 1

    return "\n".join(out) + ("\n" if original.endswith("\n") else "")


def apply_unified_patch(patch_text: str, theme_root: Path) -> List[str]:
    """
    Applies a unified diff patch to files under theme_root.
    Returns list of modified file paths (relative).
    """
    file_patches = parse_unified_diff(patch_text)
    changed: List[str] = []

    for fp in file_patches:
        rel = _norm_rel_path(fp.path_new)
        if not _is_safe_theme_path(rel):
            raise PatchError(f"Patch touches disallowed path: {rel}")

        target = (theme_root / rel).resolve()
        if not target.exists() or not target.is_file():
            raise PatchError(f"Patch target file missing: {rel}")

        original = target.read_text(encoding="utf-8")
        new_text = _apply_hunks_to_text(original, fp.hunks)

        if new_text != original:
            target.write_text(new_text, encoding="utf-8")
            changed.append(rel)

    return changed

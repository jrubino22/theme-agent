from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Any

THEME_DIRS = ["sections", "snippets", "templates", "assets", "config", "locales"]

ENTRYPOINT_GUESSES = {
    "header": [
        "sections/header.liquid",
        "sections/main-header.liquid",
        "snippets/header.liquid",
    ],
    "footer": [
        "sections/footer.liquid",
        "sections/main-footer.liquid",
        "snippets/footer.liquid",
    ],
    "product": [
        "templates/product.json",
        "templates/product.liquid",
        "sections/main-product.liquid",
        "sections/product-main.liquid",
    ],
    "collection": [
        "templates/collection.json",
        "templates/collection.liquid",
        "sections/main-collection.liquid",
        "sections/collection-main.liquid",
    ],
    "cart": [
        "templates/cart.json",
        "templates/cart.liquid",
        "sections/main-cart.liquid",
        "sections/cart-items.liquid",
        "snippets/cart-drawer.liquid",
        "snippets/cart.liquid",
    ],
}

def _safe_rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except Exception:
        return str(path)

def _list_files(root: Path, subdir: str, exts: Optional[List[str]] = None, limit: int = 5000) -> List[str]:
    d = root / subdir
    if not d.exists():
        return []
    out: List[str] = []
    for p in d.rglob("*"):
        if not p.is_file():
            continue
        if exts and p.suffix.lower() not in exts:
            continue
        out.append(_safe_rel(p, root))
        if len(out) >= limit:
            break
    return sorted(out)

def _read_first_kb(root: Path, relpath: str, kb: int = 8) -> str:
    p = root / relpath
    if not p.exists() or not p.is_file():
        return ""
    data = p.read_bytes()
    return data[: kb * 1024].decode("utf-8", errors="replace")

def _find_entrypoints(root: Path) -> Dict[str, List[str]]:
    found: Dict[str, List[str]] = {}
    for key, candidates in ENTRYPOINT_GUESSES.items():
        hits = []
        for rel in candidates:
            if (root / rel).exists():
                hits.append(rel)
        found[key] = hits
    return found

def _count_section_schema_blocks(root: Path) -> Dict[str, int]:
    """
    Count how many section files likely contain schema blocks.
    This is a quick proxy for "how section-driven is this theme".
    """
    sections = _list_files(root, "sections", exts=[".liquid"], limit=10000)
    count = 0
    for rel in sections:
        head = _read_first_kb(root, rel, kb=16)
        if "{% schema %}" in head or "\"settings\"" in head or "\"blocks\"" in head:
            count += 1
    return {"sections_total": len(sections), "sections_with_schema_like_content": count}

def summarize_theme(root: Path) -> Dict[str, Any]:
    """
    Pure read-only summary of a Shopify theme folder.
    """
    summary: Dict[str, Any] = {
        "root": str(root),
        "dirs_present": {d: (root / d).is_dir() for d in THEME_DIRS},
        "file_counts": {
            "sections_liquid": len(_list_files(root, "sections", exts=[".liquid"])),
            "snippets_liquid": len(_list_files(root, "snippets", exts=[".liquid"])),
            "templates_json": len(_list_files(root, "templates", exts=[".json"])),
            "templates_liquid": len(_list_files(root, "templates", exts=[".liquid"])),
            "assets_js": len(_list_files(root, "assets", exts=[".js", ".mjs"])),
            "assets_css": len(_list_files(root, "assets", exts=[".css"])),
        },
        "entrypoints": _find_entrypoints(root),
        "schema_stats": _count_section_schema_blocks(root),
        "notable_files": {
            "settings_schema": "config/settings_schema.json" if (root / "config/settings_schema.json").exists() else None,
            "settings_data": "config/settings_data.json" if (root / "config/settings_data.json").exists() else None,
        },
        "inventory": {
            "sections": _list_files(root, "sections", exts=[".liquid"], limit=5000),
            "snippets": _list_files(root, "snippets", exts=[".liquid"], limit=5000),
            "blocks": _list_files(root, "blocks", exts=[".liquid"], limit=5000),
            "templates": _list_files(root, "templates", exts=[".json", ".liquid"], limit=5000),
            "assets_js": _list_files(root, "assets", exts=[".js", ".mjs"], limit=5000),
            "assets_css": _list_files(root, "assets", exts=[".css"], limit=5000),
        },
    }
    return summary

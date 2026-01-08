from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List


ALLOWED_TOP_DIRS = {
    "sections",
    "snippets",
    "blocks",
    "templates",
    "layout",
    "assets",
    "config",
    "locales",
}

# Block adding image/video assets directly to the theme.
# CSS/JS in assets/ is fine; images should be added via Shopify admin/theme editor.
BLOCKED_ASSET_EXTS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".svg",
    ".mp4", ".mov", ".webm", ".mp3", ".wav",
    ".pdf",
}

class ThemeScopeError(RuntimeError):
    pass


@dataclass
class ThemeFS:
    root: Path

    def __post_init__(self) -> None:
        self.root = self.root.resolve()
        if not self.root.is_dir():
            raise ThemeScopeError(f"Theme root does not exist or is not a directory: {self.root}")

    def _resolve_rel(self, rel_path: str) -> Path:
        rel_path = rel_path.strip().lstrip("/")

        if rel_path.startswith("..") or "/../" in rel_path or "\\..\\" in rel_path:
            raise ThemeScopeError(f"Path traversal not allowed: {rel_path}")

        p = (self.root / rel_path).resolve()

        try:
            p.relative_to(self.root)
        except Exception:
            raise ThemeScopeError(f"Path escapes theme root: {rel_path}")

        parts = Path(rel_path).parts
        if not parts:
            raise ThemeScopeError("Empty path not allowed.")

        top = parts[0]
        if top not in ALLOWED_TOP_DIRS:
            raise ThemeScopeError(
                f"Blocked outside theme dirs. Got '{top}/'. Allowed: {sorted(ALLOWED_TOP_DIRS)}"
            )

        return p

    def _block_asset_binary_types(self, rel_path: str) -> None:
        rel = Path(rel_path.strip().lstrip("/"))
        if len(rel.parts) > 0 and rel.parts[0] == "assets":
            ext = rel.suffix.lower()
            if ext in BLOCKED_ASSET_EXTS:
                raise ThemeScopeError(
                    f"Blocked writing binary/content assets to theme: {rel_path}. "
                    f"Use section settings, metafields, or Shopify admin content instead."
                )

    def read_text(self, rel_path: str) -> str:
        p = self._resolve_rel(rel_path)
        if not p.exists():
            raise ThemeScopeError(f"File not found: {rel_path}")
        return p.read_text(encoding="utf-8", errors="replace")

    def write_text(self, rel_path: str, content: str) -> None:
        self._block_asset_binary_types(rel_path)

        # Also block obvious base64 image dumps in CSS/HTML.
        if "data:image/" in content and len(content) > 50_000:
            raise ThemeScopeError(
                "Blocked writing large inline image data URIs. "
                "Use Shopify admin/theme editor assets and settings instead."
            )

        p = self._resolve_rel(rel_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def list_files(self, glob: str = "**/*") -> List[str]:
        files: List[str] = []
        for top in ALLOWED_TOP_DIRS:
            base = self.root / top
            if not base.exists():
                continue
            for p in base.glob(glob):
                if p.is_file():
                    files.append(str(p.relative_to(self.root)))
        files.sort()
        return files

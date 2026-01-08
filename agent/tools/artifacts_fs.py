from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path


class ArtifactScopeError(RuntimeError):
    pass


@dataclass
class ArtifactFS:
    root: Path

    def __post_init__(self) -> None:
        self.root = self.root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve_rel(self, rel_path: str) -> Path:
        rel_path = rel_path.strip().lstrip("/")
        if rel_path.startswith("..") or "/../" in rel_path or "\\..\\" in rel_path:
            raise ArtifactScopeError(f"Path traversal not allowed: {rel_path}")

        p = (self.root / rel_path).resolve()
        try:
            p.relative_to(self.root)
        except Exception:
            raise ArtifactScopeError(f"Path escapes artifacts root: {rel_path}")
        return p

    def write_text(self, rel_path: str, content: str) -> str:
        p = self._resolve_rel(rel_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return str(p)

    def write_base64(self, rel_path: str, b64: str) -> str:
        p = self._resolve_rel(rel_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        raw = base64.b64decode(b64)
        p.write_bytes(raw)
        return str(p)

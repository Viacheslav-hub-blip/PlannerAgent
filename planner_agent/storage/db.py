"""Filesystem storage bootstrap for the MVP."""

from __future__ import annotations

from pathlib import Path


def ensure_storage(root: str | Path = ".") -> dict[str, Path]:
    base = Path(root).resolve()
    paths = {
        "skills": base / "skills",
        "memory": base / "memory",
        "runs": base / "runs",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


__all__ = ["ensure_storage"]

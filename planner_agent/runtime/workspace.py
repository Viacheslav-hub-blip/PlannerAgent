"""Workspace path helpers."""

from __future__ import annotations

from pathlib import Path


def ensure_workspace(root: str | Path) -> Path:
    path = Path(root).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_subpath(path: str | Path, root: str | Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


__all__ = ["ensure_workspace", "is_subpath"]

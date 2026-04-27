#!/usr/bin/env python3
"""Path containment helpers for sextant-optimize run artifacts."""

from __future__ import annotations

from pathlib import Path


class PathSafetyError(ValueError):
    """Raised when a path escapes its allowed containment root."""


def canonical_path(path: str | Path, *, base: str | Path | None = None) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        if base is None:
            base = Path.cwd()
        candidate = Path(base) / candidate
    return candidate.resolve(strict=False)


def ensure_contained(root: str | Path, candidate: str | Path) -> Path:
    canonical_root = canonical_path(root)
    canonical_candidate = canonical_path(candidate, base=canonical_root)
    try:
        canonical_candidate.relative_to(canonical_root)
    except ValueError as error:
        raise PathSafetyError(
            f"path escapes allowed root: {candidate!s} is not under {canonical_root!s}"
        ) from error
    return canonical_candidate


def child_path(root: str | Path, relative_path: str | Path) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise PathSafetyError(f"expected relative path under run root, got {candidate!s}")
    return ensure_contained(root, candidate)


def artifact_path(run_dir: str | Path, artifact: str | Path) -> Path:
    return child_path(run_dir, artifact)

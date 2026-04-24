"""Project-root and `.mercator/` directory resolution.

The CLI walks upward from the current working directory looking for either an
existing `.mercator/` (post-init) or a recognised stack manifest (pre-init).
Whichever it finds first defines the project root.

**Backwards-compatibility**: during the `codemap → mercator` rename cycle,
projects that still have a `.codemap/` directory are detected and used as
the storage root (read-only-compatible). A one-shot `mercator migrate`
command renames `.codemap/` → `.mercator/` + rewrites internal references.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


# Files that mark the root of a stack-specific project.
STACK_MARKERS = (
    "Cargo.toml",              # Rust
    "package.json",            # TS/JS
    "pyproject.toml",          # Python
    "setup.py",                # Python (legacy)
    "go.mod",                  # Go
    "go.work",                 # Go workspace
    "pubspec.yaml",            # Dart/Flutter
)

# Directory markers (Unity has no single file; detect via multiple dirs).
UNITY_DIR_MARKERS = ("Assets", "ProjectSettings", "Packages")

# Storage directory name. Preferred is `.mercator/`; `.codemap/` is kept as a
# recognised legacy alias during the deprecation window.
STORAGE_DIR = ".mercator"
LEGACY_STORAGE_DIR = ".codemap"


def find_project_root(start: Optional[Path] = None) -> Path:
    """Walk upward from `start` (or cwd) to find the project root.

    Returns the first ancestor that has either `.mercator/` (preferred),
    `.codemap/` (legacy), or any stack marker. Falls back to `start` itself
    if nothing matches.
    """
    start = (start or Path.cwd()).resolve()
    for candidate in (start, *start.parents):
        if (candidate / STORAGE_DIR).is_dir():
            return candidate
        if (candidate / LEGACY_STORAGE_DIR).is_dir():
            return candidate
        if any((candidate / m).exists() for m in STACK_MARKERS):
            return candidate
        # Unity heuristic: all three markers present.
        if all((candidate / m).exists() for m in UNITY_DIR_MARKERS):
            return candidate
    return start


def mercator_dir(project_root: Path) -> Path:
    """Return the storage-dir path, preferring `.mercator/` but falling
    back to `.codemap/` if only the legacy dir exists.

    New directories are always created as `.mercator/`. Reads tolerate the
    legacy name so the migration is non-destructive.
    """
    new = project_root / STORAGE_DIR
    if new.is_dir():
        return new
    legacy = project_root / LEGACY_STORAGE_DIR
    if legacy.is_dir():
        return legacy
    return new


# Deprecated alias — kept for the transitional release so any external code
# that imported `codemap.paths.codemap_dir` still resolves. Prefer
# `mercator_dir`.
codemap_dir = mercator_dir


def ensure_mercator_dir(project_root: Path) -> Path:
    d = mercator_dir(project_root)
    # If only the legacy dir exists, we keep writing into it so subsequent
    # reads through `mercator_dir()` stay consistent — but do NOT rename
    # implicitly. Explicit rename is `mercator migrate`.
    d.mkdir(parents=True, exist_ok=True)
    (d / "contracts").mkdir(exist_ok=True)
    (d / "symbols").mkdir(exist_ok=True)
    (d / "assets").mkdir(exist_ok=True)
    return d


# Deprecated alias.
ensure_codemap_dir = ensure_mercator_dir

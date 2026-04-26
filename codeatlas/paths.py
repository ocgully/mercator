"""Project-root and `.codeatlas/` directory resolution.

The CLI walks upward from the current working directory looking for either an
existing `.codeatlas/` (post-init), `.mercator/` (legacy), `.codemap/`
(double-legacy), or a recognised stack manifest (pre-init). Whichever it
finds first defines the project root.

**Backwards-compatibility**: projects that still have a `.mercator/` directory
(or even `.codemap/`) from earlier releases are detected and used as the
storage root. A one-shot `codeatlas migrate-from-mercator` command renames
the dir to `.codeatlas/` and rewrites internal references.
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

# Storage directory name. Preferred is `.codeatlas/`. `.mercator/` and
# `.codemap/` are kept as recognised legacy aliases during the deprecation
# window. The order in LEGACY_STORAGE_DIRS defines fallback priority.
STORAGE_DIR = ".codeatlas"
LEGACY_STORAGE_DIRS = (".mercator", ".codemap")
# Back-compat single-name constant (some external code reads this).
LEGACY_STORAGE_DIR = LEGACY_STORAGE_DIRS[0]


def find_project_root(start: Optional[Path] = None) -> Path:
    """Walk upward from `start` (or cwd) to find the project root.

    Returns the first ancestor that has either `.codeatlas/` (preferred),
    one of the legacy storage dirs, or any stack marker. Falls back to
    `start` itself if nothing matches.
    """
    start = (start or Path.cwd()).resolve()
    for candidate in (start, *start.parents):
        if (candidate / STORAGE_DIR).is_dir():
            return candidate
        if any((candidate / d).is_dir() for d in LEGACY_STORAGE_DIRS):
            return candidate
        if any((candidate / m).exists() for m in STACK_MARKERS):
            return candidate
        # Unity heuristic: all three markers present.
        if all((candidate / m).exists() for m in UNITY_DIR_MARKERS):
            return candidate
    return start


_OVERRIDE: Optional[Path] = None


def set_storage_override(path: Optional[Path]) -> None:
    """Redirect where codeatlas reads and writes its storage dir.

    Used by the `--storage-dir` CLI flag so you can explore a project
    without planting `.codeatlas/` inside it. Path can be absolute or
    relative; it's treated as the full storage dir (NOT a parent that
    gets a `.codeatlas/` appended).
    """
    global _OVERRIDE
    _OVERRIDE = path.resolve() if path is not None else None


def codeatlas_dir(project_root: Path) -> Path:
    """Return the storage-dir path, preferring `.codeatlas/` but falling
    back to a legacy dir (`.mercator/`, `.codemap/`) if only that exists.

    Honours `set_storage_override(...)` — when an override is set, that
    path is returned verbatim regardless of project_root.
    """
    if _OVERRIDE is not None:
        return _OVERRIDE
    new = project_root / STORAGE_DIR
    if new.is_dir():
        return new
    for legacy_name in LEGACY_STORAGE_DIRS:
        legacy = project_root / legacy_name
        if legacy.is_dir():
            return legacy
    return new


# Deprecated aliases — kept for the transitional releases so external code
# that imported `mercator.paths.mercator_dir` (or older `codemap_dir`) still
# resolves. Prefer `codeatlas_dir`.
mercator_dir = codeatlas_dir
codemap_dir = codeatlas_dir


def ensure_codeatlas_dir(project_root: Path) -> Path:
    d = codeatlas_dir(project_root)
    # If only a legacy dir exists, we keep writing into it so subsequent
    # reads through `codeatlas_dir()` stay consistent — but do NOT rename
    # implicitly. Explicit rename is `codeatlas migrate-from-mercator`.
    d.mkdir(parents=True, exist_ok=True)
    return d


def project_storage_dir(repo_storage: Path, project_id: str) -> Path:
    """Return the per-project storage path: `<repo_storage>/projects/<id>/`.

    This is where every project's Layer 1+2+3+4 artefacts live under the
    new (always-nested) layout. A repo with one project still nests — the
    atlas decides how to render based on the count.
    """
    return repo_storage / "projects" / project_id


def ensure_project_storage_dir(repo_storage: Path, project_id: str) -> Path:
    d = project_storage_dir(repo_storage, project_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "contracts").mkdir(exist_ok=True)
    (d / "symbols").mkdir(exist_ok=True)
    (d / "assets").mkdir(exist_ok=True)
    return d


# Deprecated aliases.
ensure_mercator_dir = ensure_codeatlas_dir
ensure_codemap_dir = ensure_codeatlas_dir

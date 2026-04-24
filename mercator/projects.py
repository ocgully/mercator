"""Project discovery — walk a repo, find stack manifests, group into projects.

A **project** is a self-contained build unit identified by one (or more
adjacent) stack manifest files. A repo has 1..N projects. Detection is
file-based and explicit: we look for the same markers as `mercator.detect`,
but anywhere under the repo root rather than only at the root.

Outputs `.mercator/projects.json`:

    {
      "schema_version": "1",
      "repo_root": ".",
      "projects": [
        { "id": "mercator-cli", "stack": "python",
          "root": ".", "manifest": "pyproject.toml",
          "category": "tool", "tags": [], "manifest_name": "mercator" },
        ...
      ],
      "skipped": [...]   # informational: paths skipped by the walker
    }

Stack manifests grouping rule: when multiple manifests live in the same
directory (e.g. `package.json` + `tsconfig.json` + `pyproject.toml` for a
hybrid project), the highest-precedence stack wins (matching `detect.py`'s
order). One project per directory.

Repo-level overrides live in `.mercator/repo.toml`:

    # Coarse-grained directory filters
    include = ["apps/*", "services/*"]   # only project roots matching
    exclude = ["legacy/**"]              # blanket-skip these paths

    # Per-project overrides keyed by detected ID
    [projects."apps-web"]
    name = "web"
    category = "app"
    tags = ["public", "tier-1"]

Stdlib-only.
"""
from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Set, Tuple

from mercator import SCHEMA_VERSION


# Directories the walker never descends into. These are well-known build
# outputs / vendored copies / scratch dirs that contain stray manifests
# which are NOT real projects.
SKIP_DIRS: Set[str] = {
    # VCS + tooling
    ".git", ".hg", ".svn", ".jj",
    # Build outputs
    "target", "build", "dist", "out",
    "node_modules", ".yarn", ".pnpm-store",
    "__pycache__", "site-packages",
    ".tox", ".nox",
    # Caches
    ".cache", ".turbo", ".next", ".nuxt", ".parcel-cache",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".gradle", ".m2",
    # Virtualenvs
    ".venv", "venv", "env",
    # Coverage
    "coverage", "htmlcov", ".coverage",
    # Vendored / examples / fixtures (default — repo.toml can re-include)
    "vendor", "third_party", "third-party",
    "examples", "fixtures", "samples",
    # IDE
    ".idea", ".vscode",
    # Mercator's own
    ".mercator", ".codemap",
    # Temporary
    "tmp", "temp",
}


# Manifest precedence — first match wins when several markers exist in the
# same directory. Mirrors `detect.detect()` order so single-stack repos
# behave identically.
MANIFEST_PRECEDENCE: List[Tuple[str, str]] = [
    ("rust",    "Cargo.toml"),
    ("dart",    "pubspec.yaml"),
    ("ts",      "package.json"),
    ("python",  "pyproject.toml"),
    ("python",  "setup.py"),
    ("go",      "go.mod"),
    ("go",      "go.work"),
]

# Unity needs all three markers, separately handled.
UNITY_MARKERS = ("Assets", "ProjectSettings", "Packages")


# Path-prefix → category convention. Applied in order; first match wins.
PATH_CATEGORY_RULES: List[Tuple[str, str]] = [
    ("apps/",     "app"),
    ("app/",      "app"),
    ("services/", "service"),
    ("svc/",      "service"),
    ("packages/", "lib"),
    ("libs/",     "lib"),
    ("lib/",      "lib"),
    ("tools/",    "tool"),
    ("cli/",      "tool"),
    ("docs/",     "docs"),
    ("infra/",    "infra"),
    ("deploy/",   "infra"),
    ("scripts/",  "tool"),
    ("web/",      "app"),
]


# ---------------------------------------------------------------------------
# repo.toml — minimal reader (TOML for newer Pythons, fallback)
# ---------------------------------------------------------------------------

def _read_repo_toml(repo_root: Path) -> dict:
    path = repo_root / ".mercator" / "repo.toml"
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    try:
        import tomllib  # 3.11+
        return tomllib.loads(text)
    except ImportError:
        pass
    try:
        import tomli  # type: ignore[import-not-found]
        return tomli.loads(text)
    except ImportError:
        pass
    # No TOML parser available — fail open with empty config.
    return {}


# ---------------------------------------------------------------------------
# Walk
# ---------------------------------------------------------------------------

def _is_unity_dir(d: Path) -> bool:
    return all((d / m).exists() for m in UNITY_MARKERS)


def _detect_manifest(d: Path) -> Optional[Tuple[str, str]]:
    """Return (stack, manifest_filename) for directory d, or None."""
    if _is_unity_dir(d):
        return ("unity", "ProjectSettings/ProjectSettings.asset")
    for stack, manifest in MANIFEST_PRECEDENCE:
        if (d / manifest).is_file():
            return (stack, manifest)
    return None


def _walk_for_manifests(
    repo_root: Path,
    extra_skip: Set[str],
    include_globs: List[str],
    exclude_globs: List[str],
    max_depth: int,
) -> Tuple[List[Tuple[Path, Tuple[str, str]]], List[str]]:
    """Walk repo_root and return [(dir, (stack, manifest))] + a skipped list.

    `include_globs`: when non-empty, only directories whose relative path
        matches at least one glob are kept. Always evaluated against the
        POSIX-style repo-relative path.
    `exclude_globs`: directories matching any glob are skipped (subtree-pruned).
    `max_depth`: hard cap to keep the walk fast on huge trees.
    """
    found: List[Tuple[Path, Tuple[str, str]]] = []
    skipped: List[str] = []
    repo_root = repo_root.resolve()

    def _match_any(rel: str, globs: List[str]) -> bool:
        return any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(rel + "/", g)
                   for g in globs)

    stack: List[Tuple[Path, int]] = [(repo_root, 0)]
    visited_inodes: Set[int] = set()
    while stack:
        d, depth = stack.pop()
        if depth > max_depth:
            continue
        try:
            st = d.stat()
            if st.st_ino:
                if st.st_ino in visited_inodes:
                    continue  # symlink loop guard
                visited_inodes.add(st.st_ino)
        except OSError:
            continue

        try:
            rel_path = d.relative_to(repo_root).as_posix() or "."
        except ValueError:
            continue

        # Apply skip/exclude.
        if d.name in SKIP_DIRS or d.name in extra_skip:
            skipped.append(rel_path)
            continue
        if exclude_globs and _match_any(rel_path, exclude_globs):
            skipped.append(rel_path)
            continue

        # Detect a manifest at this level.
        detected = _detect_manifest(d)
        if detected is not None:
            keep = True
            if include_globs:
                keep = _match_any(rel_path, include_globs) or rel_path == "."
            if keep:
                found.append((d, detected))
                # Don't descend into a detected project's tree — its sub-dirs
                # belong to that project's internal system breakdown, not to
                # new sibling projects. This is the key heuristic that keeps
                # detection clean: a Cargo workspace with 30 crates produces
                # ONE project, not 30.
                continue

        # Otherwise, descend into children.
        try:
            children = sorted([c for c in d.iterdir() if c.is_dir()])
        except OSError:
            continue
        for c in children:
            stack.append((c, depth + 1))

    return found, skipped


# ---------------------------------------------------------------------------
# Project ID + name derivation
# ---------------------------------------------------------------------------

def _slug(s: str) -> str:
    """Path → safe project-id slug. Lowercase, kebab-case, no separators."""
    s = s.replace("\\", "/").strip("/")
    s = re.sub(r"[^A-Za-z0-9._/-]+", "-", s)
    s = s.replace("/", "-")
    s = re.sub(r"-+", "-", s).strip("-")
    return s.lower() or "root"


def _read_manifest_name(project_dir: Path, stack: str, manifest: str) -> Optional[str]:
    """Best-effort: read the project's own declared name from its manifest.

    Used as a fallback project-ID seed when the path-based ID is just '.'
    (single-project monorepo at root).
    """
    try:
        if stack == "rust":
            text = (project_dir / "Cargo.toml").read_text(encoding="utf-8")
            # Try `[package].name` and `[workspace.package].name`.
            m = re.search(r'^\s*name\s*=\s*"([^"]+)"', text, re.MULTILINE)
            return m.group(1) if m else None
        if stack == "ts":
            data = json.loads((project_dir / "package.json").read_text(encoding="utf-8"))
            return data.get("name") if isinstance(data, dict) else None
        if stack == "python":
            try:
                import tomllib
                pj = tomllib.loads((project_dir / "pyproject.toml").read_text(encoding="utf-8"))
            except (ImportError, OSError, ValueError):
                return None
            return ((pj.get("project") or {}).get("name") or
                    (pj.get("tool", {}).get("poetry") or {}).get("name"))
        if stack == "dart":
            text = (project_dir / "pubspec.yaml").read_text(encoding="utf-8")
            m = re.search(r"^name:\s*([A-Za-z0-9_]+)", text, re.MULTILINE)
            return m.group(1) if m else None
        if stack == "go":
            for fname in ("go.mod", "go.work"):
                f = project_dir / fname
                if f.is_file():
                    text = f.read_text(encoding="utf-8")
                    m = re.search(r"^module\s+(\S+)", text, re.MULTILINE)
                    if m:
                        # Module path → last segment.
                        return m.group(1).rsplit("/", 1)[-1]
        if stack == "unity":
            return project_dir.name or None
    except (OSError, UnicodeDecodeError):
        return None
    return None


def _category_from_path(rel_path: str) -> Optional[str]:
    p = rel_path + "/"
    for prefix, cat in PATH_CATEGORY_RULES:
        if p.startswith(prefix):
            return cat
    return None


def _category_from_manifest_hint(stack: str, project_dir: Path, manifest: str) -> Optional[str]:
    """Look at the manifest itself for a category hint."""
    try:
        if stack == "rust":
            text = (project_dir / "Cargo.toml").read_text(encoding="utf-8")
            if re.search(r'^\s*\[\[bin\]\]', text, re.MULTILINE):
                return "tool"
            if re.search(r'^\s*\[lib\]', text, re.MULTILINE):
                return "lib"
        if stack == "ts":
            data = json.loads((project_dir / "package.json").read_text(encoding="utf-8"))
            if isinstance(data, dict):
                if data.get("private") is True:
                    return "app"
                if "bin" in data:
                    return "tool"
        if stack == "python":
            try:
                import tomllib
                pj = tomllib.loads((project_dir / "pyproject.toml").read_text(encoding="utf-8"))
            except (ImportError, OSError, ValueError):
                return None
            project = pj.get("project") or {}
            if "scripts" in project or "gui-scripts" in project:
                return "tool"
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return None


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def detect_projects(repo_root: Path, *, max_depth: int = 8) -> dict:
    """Detect every project in `repo_root` and return a projects.json dict."""
    repo_root = repo_root.resolve()
    overrides = _read_repo_toml(repo_root)

    include_globs: List[str] = list(overrides.get("include") or [])
    exclude_globs: List[str] = list(overrides.get("exclude") or [])
    extra_skip: Set[str] = set(overrides.get("skip_dirs") or [])

    found, skipped = _walk_for_manifests(
        repo_root, extra_skip, include_globs, exclude_globs, max_depth
    )

    projects: List[dict] = []
    used_ids: Set[str] = set()

    # Per-project override map keyed by *detected* (path-derived) ID. Allows
    # users to rename / recategorise without edits to detection code.
    per_project_overrides = overrides.get("projects") or {}

    for project_dir, (stack, manifest) in sorted(found, key=lambda x: x[0]):
        rel_dir = project_dir.relative_to(repo_root).as_posix() or "."
        manifest_name = _read_manifest_name(project_dir, stack, manifest)

        if rel_dir == ".":
            # Root project — prefer the manifest name when available, else
            # the repo dir name.
            seed = manifest_name or repo_root.name or "root"
            base_id = _slug(seed)
        else:
            base_id = _slug(rel_dir)

        # Disambiguate collisions deterministically.
        pid = base_id
        n = 2
        while pid in used_ids:
            pid = f"{base_id}-{n}"
            n += 1
        used_ids.add(pid)

        category = (
            _category_from_path(rel_dir)
            or _category_from_manifest_hint(stack, project_dir, manifest)
            or "lib"  # neutral default
        )
        tags: List[str] = []

        # Apply repo.toml override.
        ov = per_project_overrides.get(pid) or {}
        display_name = ov.get("name") or manifest_name or base_id
        category = ov.get("category") or category
        tags = list(ov.get("tags") or tags)

        rel_manifest = (
            "/".join([rel_dir, manifest]).lstrip("/") if rel_dir != "." else manifest
        )
        projects.append({
            "id": pid,
            "name": display_name,
            "stack": stack,
            "root": rel_dir,
            "manifest": rel_manifest,
            "manifest_name": manifest_name,
            "category": category,
            "tags": tags,
        })

    projects.sort(key=lambda p: (p["category"], p["root"]))

    return {
        "schema_version": SCHEMA_VERSION,
        "layer": "projects",
        "repo_root": ".",
        "project_count": len(projects),
        "stacks": sorted({p["stack"] for p in projects}),
        "projects": projects,
        "skipped_count": len(skipped),
        "skipped_sample": skipped[:25],
        "source_tool": "mercator_project_walk",
        "source_tool_note": (
            "Auto-detected by walking the repo for stack manifests. "
            "Override via .mercator/repo.toml (include/exclude/skip_dirs/[projects.<id>])."
        ),
    }


def write_projects(repo_root: Path, mercator_dir: Path) -> dict:
    """Detect projects and write `.mercator/projects.json`. Returns the doc."""
    doc = detect_projects(repo_root)
    mercator_dir.mkdir(parents=True, exist_ok=True)
    path = mercator_dir / "projects.json"
    path.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return doc


def load_projects(mercator_dir: Path) -> Optional[dict]:
    p = mercator_dir / "projects.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

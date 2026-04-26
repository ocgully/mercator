"""Source-file coverage report.

A repo can have lots of source code that no CodeAtlas project covers —
either because the stack isn't supported (C++, Go, Lua, GDScript, Swift, …)
or because a small project at root only declares build tooling (e.g. Godot's
`pyproject.toml` for SCons hooks while the engine itself is C++).

This module walks the repo, attributes each source file to its deepest
covering project (if any), and emits a coverage breakdown by extension —
mostly so the atlas can honestly say "we mapped 4% of this repo by file
count, the other 96% is C++/GDScript/etc. that CodeAtlas doesn't speak yet".

Output: `.codeatlas/coverage.json`:

    {
      "schema_version": "1",
      "by_extension": {
        ".cpp":  {"total": 12000, "in_projects": 0,    "unmapped": 12000},
        ".py":   {"total": 1500,  "in_projects": 1500, "unmapped": 0},
        ".rs":   {"total": 800,   "in_projects": 800,  "unmapped": 0}
      },
      "in_projects_total": 2300,
      "unmapped_total":    12000,
      "unmapped_top_dirs": [{"path": "scene/", "count": 4200}, ...],
      "unsupported_languages": ["cpp", "gdscript"]
    }

Stdlib-only.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from codeatlas import SCHEMA_VERSION, paths


# Extensions we recognise as code, with the language label we surface in the
# atlas. If an extension has no entry here, it's not counted (no point
# tallying every `.png`).
_EXT_TO_LANG: Dict[str, str] = {
    # CodeAtlas-supported
    ".rs":   "rust",
    ".py":   "python",
    ".pyi":  "python",
    ".ts":   "typescript",
    ".tsx":  "typescript",
    ".js":   "javascript",
    ".jsx":  "javascript",
    ".mjs":  "javascript",
    ".cjs":  "javascript",
    ".dart": "dart",
    ".cs":   "csharp (unity-ish)",
    # Not yet supported — the bulk of "unmapped" results
    ".cpp":  "cpp",
    ".cc":   "cpp",
    ".cxx":  "cpp",
    ".c":    "c",
    ".h":    "c/cpp header",
    ".hpp":  "cpp header",
    ".hh":   "cpp header",
    ".m":    "objective-c",
    ".mm":   "objective-c++",
    ".swift": "swift",
    ".kt":   "kotlin",
    ".java": "java",
    ".scala": "scala",
    ".clj":  "clojure",
    ".go":   "go",
    ".rb":   "ruby",
    ".php":  "php",
    ".lua":  "lua",
    ".gd":   "gdscript",
    ".gdshader": "godot shader",
    ".glsl": "glsl",
    ".hlsl": "hlsl",
    ".wgsl": "wgsl",
    ".sh":   "shell",
    ".bash": "shell",
    ".ps1":  "powershell",
    ".sql":  "sql",
    ".vue":  "vue (template)",
    ".svelte": "svelte",
    ".elm":  "elm",
    ".ex":   "elixir",
    ".exs":  "elixir",
    ".erl":  "erlang",
    ".hs":   "haskell",
    ".ml":   "ocaml",
    ".nim":  "nim",
    ".zig":  "zig",
    ".nix":  "nix",
}

# CodeAtlas-supported language labels — anything else is "unsupported" and
# shows up in `unsupported_languages` for the atlas to surface.
_SUPPORTED_LANGS: set = {
    "rust", "python", "typescript", "javascript", "dart",
}


# Which extensions a project's stack actually claims. A project at root `.`
# with stack=python doesn't "own" the C++ source elsewhere in the repo — it
# only owns .py/.pyi files. This is the difference between a project's
# *path scope* and what it can actually map.
_STACK_EXTS: Dict[str, set] = {
    "rust":   {".rs"},
    "python": {".py", ".pyi"},
    "ts":     {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"},
    "dart":   {".dart"},
    "unity":  {".cs"},
    "go":     {".go"},
}


# Directories we never descend into. Mirrors `projects.SKIP_DIRS` plus
# common build/output dirs that aren't already there. Kept local so this
# module has no import-cycle on projects.
_SKIP_DIRS: set = {
    ".git", ".hg", ".svn", ".jj",
    "target", "build", "dist", "out",
    "node_modules", ".yarn", ".pnpm-store",
    "__pycache__", "site-packages",
    ".tox", ".nox",
    ".cache", ".turbo", ".next", ".nuxt", ".parcel-cache",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".gradle", ".m2",
    ".venv", "venv", "env",
    "coverage", "htmlcov", ".coverage",
    ".idea", ".vscode", ".github",
    ".codeatlas", ".mercator", ".codemap",
    "tmp", "temp",
    "vendor", "third_party", "third-party",
}


# ---------------------------------------------------------------------------
# Walk + attribute
# ---------------------------------------------------------------------------

def compute_coverage(repo_root: Path, projects_doc: dict, *,
                     max_files: int = 200_000) -> dict:
    """Walk `repo_root` for source files, attribute to projects, summarise.

    `max_files` is a hard ceiling so a 5-million-file monorepo doesn't hang
    the refresh — the report is informational, not a build artefact.
    """
    repo_root = repo_root.resolve()
    projects: List[dict] = sorted(
        (projects_doc or {}).get("projects") or [],
        key=lambda p: -(p.get("root", "").count("/")),
    )
    # Deepest project root first → first-match wins for attribution.
    # Each entry: (project_id, root_path, stack).
    project_roots: List[tuple[str, str, str]] = [
        (p["id"], p["root"], p.get("stack", "")) for p in projects
    ]

    by_ext_total: Counter = Counter()
    by_ext_mapped: Counter = Counter()
    by_ext_unmapped: Counter = Counter()
    unmapped_by_dir: Counter = Counter()
    files_seen = 0

    for path in _walk_files(repo_root):
        files_seen += 1
        if files_seen > max_files:
            break
        ext = path.suffix.lower()
        if ext not in _EXT_TO_LANG:
            continue
        try:
            rel = path.relative_to(repo_root).as_posix()
        except ValueError:
            continue
        by_ext_total[ext] += 1
        owner = _attribute(rel, ext, project_roots)
        if owner is None:
            by_ext_unmapped[ext] += 1
            # Top-level bucket for the "where is the unmapped code?" hint.
            top = rel.split("/", 1)[0] if "/" in rel else "."
            unmapped_by_dir[top] += 1
        else:
            by_ext_mapped[ext] += 1

    by_extension: Dict[str, dict] = {}
    unsupported: set = set()
    for ext, total in sorted(by_ext_total.items(), key=lambda kv: -kv[1]):
        lang = _EXT_TO_LANG[ext]
        by_extension[ext] = {
            "language": lang,
            "total": total,
            "in_projects": by_ext_mapped.get(ext, 0),
            "unmapped": by_ext_unmapped.get(ext, 0),
            "supported": lang in _SUPPORTED_LANGS,
        }
        if lang not in _SUPPORTED_LANGS and by_ext_unmapped.get(ext, 0) > 0:
            unsupported.add(lang)

    return {
        "schema_version": SCHEMA_VERSION,
        "layer": "coverage",
        "by_extension": by_extension,
        "in_projects_total": sum(by_ext_mapped.values()),
        "unmapped_total": sum(by_ext_unmapped.values()),
        "unmapped_top_dirs": [
            {"path": d, "count": c}
            for d, c in unmapped_by_dir.most_common(8)
        ],
        "unsupported_languages": sorted(unsupported),
        "files_scanned": files_seen,
        "max_files_capped": files_seen > max_files,
        "source_tool": "codeatlas_coverage_walk",
        "source_tool_note": (
            "Counts source files by extension across the repo and attributes "
            "each to its deepest covering project (or 'unmapped' if no "
            "project owns it). CodeAtlas-supported languages (rust, python, "
            "typescript, javascript, dart) are flagged separately so the "
            "atlas can show how much of the repo is covered."
        ),
    }


def _walk_files(root: Path):
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            for entry in d.iterdir():
                try:
                    if entry.is_symlink():
                        continue  # avoid loops; some symlinks point outside
                    if entry.is_dir():
                        if entry.name in _SKIP_DIRS or entry.name.endswith(".egg-info"):
                            continue
                        stack.append(entry)
                    elif entry.is_file():
                        yield entry
                except OSError:
                    continue
        except OSError:
            continue


def _attribute(
    rel_path: str, ext: str, project_roots: List[tuple[str, str, str]],
) -> Optional[str]:
    """Return the project_id that owns `rel_path`, considering both path
    containment AND stack/extension fit. Deepest project root first.

    A project at root `.` with stack=python only claims .py/.pyi files —
    not the C++ source sharing the same root. That's the whole point of
    the report: surface "this repo has 90% C++ that we can't map yet".
    """
    for pid, root, stack in project_roots:
        # Stack-extension gate: the project can only claim files its stack
        # knows how to read. Stacks without an entry in _STACK_EXTS (Unity,
        # Dart, Go, etc.) are conservatively assumed to claim nothing for
        # coverage purposes — refine the table if a stack lands real Layer-2
        # support.
        if ext not in _STACK_EXTS.get(stack, set()):
            continue
        if root in (".", ""):
            return pid
        if rel_path == root or rel_path.startswith(root + "/"):
            return pid
    return None


def write_coverage(repo_root: Path, projects_doc: dict) -> Path:
    repo_storage = paths.ensure_codeatlas_dir(repo_root)
    doc = compute_coverage(repo_root, projects_doc)
    out = repo_storage / "coverage.json"
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def load_coverage(repo_storage: Path) -> Optional[dict]:
    p = repo_storage / "coverage.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

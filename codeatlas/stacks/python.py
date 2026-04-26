"""Python stack — Layer 1 (packages) + basic Layer 2 (public defs / classes).

Granularity choice: a *system* in Python is a **sub-package** — a directory
that contains `__init__.py`. The top-level distribution (identified by
`pyproject.toml` at the project root) is also a system, matching what
`pip install` ships. Sub-package granularity is where the interesting
dependency structure lives: for CodeAtlas itself we get `codeatlas`,
`codeatlas.render`, `codeatlas.stacks` as three systems with real edges
between them. For a library like Django we'd get dozens.

Layer 1 dependencies come from AST-parsed imports inside each package's
source files. Only intra-project edges are emitted — imports of stdlib /
third-party packages are tracked separately in
`systems[].external_imports` for informational use, but aren't edges in the
Layer 1 graph.

Layer 2 (contracts) extracts top-level `def` and `class` statements whose
names don't start with an underscore — the conventional public surface of a
Python module. Signatures are reconstructed from the AST (with `*`, `**`,
defaults preserved, but type annotations flattened to their `ast.unparse`
output).

Stdlib-only. Tolerant to syntax errors (file is skipped, not fatal).
"""
from __future__ import annotations

import ast
from pathlib import Path, PurePath
from typing import Dict, List, Optional, Set, Tuple

from codeatlas import SCHEMA_VERSION


# Directories to skip when walking for packages. These are well-known
# non-source locations that can contain stray __init__.py files (e.g. tests
# sometimes do; venv site-packages always do).
SKIP_DIRS = {
    ".git", ".hg", ".svn",
    ".venv", "venv", "env", ".env",
    "__pycache__",
    "build", "dist",
    ".tox", ".nox", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "node_modules",
    "site-packages",
    ".codeatlas", ".mercator", ".codemap",
    ".egg-info",
    "htmlcov", ".coverage",
}


# ---------------------------------------------------------------------------
# pyproject.toml — minimal [project] reader (stdlib tomllib when available,
# otherwise a loose key scan). We only need name + version + dependencies.
# ---------------------------------------------------------------------------

def _read_pyproject(project_root: Path) -> dict:
    """Best-effort read of pyproject.toml. Never raises."""
    path = project_root / "pyproject.toml"
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    try:
        import tomllib  # Python 3.11+
        return tomllib.loads(text)
    except ImportError:
        pass
    try:
        import tomli  # type: ignore[import-not-found]
        return tomli.loads(text)
    except ImportError:
        pass
    return {}


# ---------------------------------------------------------------------------
# Package discovery
# ---------------------------------------------------------------------------

def _is_package_dir(d: Path) -> bool:
    return (d / "__init__.py").is_file()


def _walk_packages(src_root: Path) -> List[Path]:
    """Yield every sub-package directory under `src_root` that has __init__.py.

    Doesn't include `src_root` itself — the caller decides whether the root
    counts as a package (the top-level distribution entry) by checking
    `_is_package_dir(src_root)`.
    """
    out: List[Path] = []
    if not src_root.is_dir():
        return out
    for entry in sorted(src_root.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name in SKIP_DIRS or entry.name.endswith(".egg-info"):
            continue
        if _is_package_dir(entry):
            out.append(entry)
            out.extend(_walk_packages(entry))
    return out


def _find_source_roots(project_root: Path, pyproject: dict) -> List[Path]:
    """Find the root directories that contain top-level packages.

    Honours common layouts:
      * flat:   <project_root>/<pkg>/__init__.py  — source_root = project_root
      * src:    <project_root>/src/<pkg>/__init__.py — source_root = project_root/src

    A project can declare this via [tool.setuptools.package-dir] or
    [tool.setuptools.packages.find].where, but we also heuristically detect
    a `src/` layout so unmarked projects still map correctly.
    """
    roots: List[Path] = []

    tool_setuptools = ((pyproject.get("tool") or {}).get("setuptools") or {})
    find = tool_setuptools.get("packages", {}).get("find") if isinstance(tool_setuptools.get("packages"), dict) else None
    if isinstance(find, dict):
        wheres = find.get("where")
        if isinstance(wheres, list):
            for w in wheres:
                if isinstance(w, str):
                    candidate = (project_root / w).resolve()
                    if candidate.is_dir():
                        roots.append(candidate)
        elif isinstance(wheres, str):
            candidate = (project_root / wheres).resolve()
            if candidate.is_dir():
                roots.append(candidate)

    pkg_dir = tool_setuptools.get("package-dir")
    if isinstance(pkg_dir, dict):
        for w in pkg_dir.values():
            if isinstance(w, str):
                candidate = (project_root / w).resolve()
                if candidate.is_dir() and candidate not in roots:
                    roots.append(candidate)

    if not roots:
        # Heuristic: if project_root/src has any __init__.py children, that's
        # a src layout. Otherwise project_root itself is the source root.
        src = project_root / "src"
        if src.is_dir() and any(_is_package_dir(d) for d in src.iterdir() if d.is_dir()):
            roots.append(src)
        else:
            roots.append(project_root)

    # De-dupe while preserving order.
    seen: Set[Path] = set()
    ordered: List[Path] = []
    for r in roots:
        if r not in seen:
            seen.add(r)
            ordered.append(r)
    return ordered


def _package_dotted_name(pkg_dir: Path, source_roots: List[Path]) -> Optional[str]:
    """Convert an absolute package dir to its dotted Python name by locating
    the source root that contains it and joining the relative parts.
    """
    for root in source_roots:
        try:
            rel = pkg_dir.relative_to(root)
        except ValueError:
            continue
        if rel == PurePath("."):
            return None
        return ".".join(rel.parts)
    return None


# ---------------------------------------------------------------------------
# Import extraction (intra-project)
# ---------------------------------------------------------------------------

def _parse_file_imports(py_path: Path) -> List[Tuple[str, int]]:
    """Return [(module, level)] for every import in a file.

    `level` is the number of dots in a relative import (0 for absolute).
    Syntax errors and I/O errors yield an empty list.
    """
    try:
        src = py_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(src, filename=str(py_path))
    except SyntaxError:
        return []
    out: List[Tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    out.append((alias.name, 0))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            out.append((mod, node.level or 0))
    return out


def _resolve_relative(mod: str, level: int, importing_pkg: str) -> Optional[str]:
    """Apply Python's relative-import rules: go up `level` packages from
    `importing_pkg`, then append `mod`.
    """
    if level <= 0:
        return mod or None
    parts = importing_pkg.split(".") if importing_pkg else []
    if level > len(parts):
        return None
    base = ".".join(parts[: len(parts) - level + 1])
    # `from . import foo`  → level=1, base stays at importing_pkg's parent? No:
    # `from . import x` inside pkg.sub resolves to pkg.sub.x. That's level=1
    # meaning "current package". So base = parts[:len(parts) - level + 1]? Let
    # me redo this carefully. Python spec: level=1 → current package; level=2 → parent.
    # If importing file is `pkg/sub/mod.py`, importing_pkg = 'pkg.sub'.
    #   level=1, mod='x'  → 'pkg.sub.x'
    #   level=2, mod='x'  → 'pkg.x'
    # So we drop (level-1) parts.
    drop = level - 1
    if drop > len(parts):
        return None
    base_parts = parts[: len(parts) - drop] if drop > 0 else parts
    base = ".".join(base_parts)
    if mod:
        return f"{base}.{mod}" if base else mod
    return base or None


def _longest_prefix_match(target: str, candidates: Set[str]) -> Optional[str]:
    """Find the longest candidate in `candidates` that is a prefix of `target`
    (either equal or target startswith candidate + '.')."""
    best: Optional[str] = None
    for c in candidates:
        if target == c or target.startswith(c + "."):
            if best is None or len(c) > len(best):
                best = c
    return best


# ---------------------------------------------------------------------------
# Layer 2 — public surface
# ---------------------------------------------------------------------------

def _unparse(node: Optional[ast.AST]) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001
        return ""


def _reconstruct_args(args: ast.arguments) -> str:
    parts: List[str] = []
    # Positional-only
    posonly = list(args.posonlyargs or [])
    for a in posonly:
        s = a.arg
        if a.annotation:
            s += f": {_unparse(a.annotation)}"
        parts.append(s)
    if posonly:
        parts.append("/")
    # Regular positional, with defaults aligned at the tail.
    regular = list(args.args or [])
    defaults = list(args.defaults or [])
    pad = len(regular) - len(defaults)
    for i, a in enumerate(regular):
        s = a.arg
        if a.annotation:
            s += f": {_unparse(a.annotation)}"
        if i >= pad:
            s += f" = {_unparse(defaults[i - pad])}"
        parts.append(s)
    # *args
    if args.vararg:
        s = "*" + args.vararg.arg
        if args.vararg.annotation:
            s += f": {_unparse(args.vararg.annotation)}"
        parts.append(s)
    elif args.kwonlyargs:
        parts.append("*")
    # kw-only
    for i, a in enumerate(args.kwonlyargs or []):
        s = a.arg
        if a.annotation:
            s += f": {_unparse(a.annotation)}"
        default = (args.kw_defaults or [None] * len(args.kwonlyargs))[i]
        if default is not None:
            s += f" = {_unparse(default)}"
        parts.append(s)
    # **kwargs
    if args.kwarg:
        s = "**" + args.kwarg.arg
        if args.kwarg.annotation:
            s += f": {_unparse(args.kwarg.annotation)}"
        parts.append(s)
    return ", ".join(parts)


def _public_items_in_file(py_path: Path, rel_path: str) -> List[dict]:
    try:
        src = py_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(src, filename=str(py_path))
    except SyntaxError:
        return []

    items: List[dict] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            sig = f"def {node.name}({_reconstruct_args(node.args)})"
            if node.returns:
                sig += f" -> {_unparse(node.returns)}"
            kind = "async fn" if isinstance(node, ast.AsyncFunctionDef) else "fn"
            items.append({
                "kind": kind, "name": node.name, "file": rel_path,
                "line": node.lineno, "signature": sig,
            })
        elif isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue
            bases = ", ".join(_unparse(b) for b in node.bases)
            sig = f"class {node.name}" + (f"({bases})" if bases else "")
            items.append({
                "kind": "class", "name": node.name, "file": rel_path,
                "line": node.lineno, "signature": sig,
            })
        elif isinstance(node, ast.Assign):
            # Module-level constants (UPPER_CASE or simple assignment).
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and not tgt.id.startswith("_"):
                    items.append({
                        "kind": "const", "name": tgt.id, "file": rel_path,
                        "line": node.lineno,
                        "signature": f"{tgt.id} = {_unparse(node.value)[:80]}",
                    })
    return items


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def build_systems(project_root: Path) -> dict:
    project_root = project_root.resolve()
    pyproject = _read_pyproject(project_root)

    source_roots = _find_source_roots(project_root, pyproject)

    # Discover packages: every <source_root>/*/ that has __init__.py is a
    # top-level package, and recurse for sub-packages.
    packages: List[Path] = []
    for root in source_roots:
        for d in sorted(root.iterdir()) if root.is_dir() else []:
            if not d.is_dir():
                continue
            if d.name in SKIP_DIRS or d.name.endswith(".egg-info"):
                continue
            if _is_package_dir(d):
                packages.append(d)
                packages.extend(_walk_packages(d))

    # Map: dotted-name → dir
    name_to_dir: Dict[str, Path] = {}
    for pkg_dir in packages:
        name = _package_dotted_name(pkg_dir, source_roots)
        if name is None:
            continue
        if name not in name_to_dir:
            name_to_dir[name] = pkg_dir

    system_names: Set[str] = set(name_to_dir.keys())

    # Build systems list with intra-project deps.
    systems: List[dict] = []
    for name in sorted(system_names):
        pkg_dir = name_to_dir[name]
        intra: Set[str] = set()
        external: Set[str] = set()
        # Iterate every .py file under this package, but NOT under
        # child-package subdirs (those are their own systems).
        child_pkgs = {name_to_dir[n] for n in system_names
                      if n.startswith(name + ".")}
        for py in sorted(pkg_dir.rglob("*.py")):
            # Skip files owned by a child package.
            if any(cp in py.parents for cp in child_pkgs):
                continue
            if any(part in SKIP_DIRS for part in py.relative_to(project_root).parts):
                continue
            for mod, level in _parse_file_imports(py):
                resolved = _resolve_relative(mod, level, name)
                if not resolved:
                    continue
                match = _longest_prefix_match(resolved, system_names)
                if match is None:
                    external.add(resolved.split(".")[0])
                elif match != name:
                    intra.add(match)

        manifest_rel = (pkg_dir / "__init__.py").relative_to(project_root).as_posix()
        scope_rel = pkg_dir.relative_to(project_root).as_posix()
        systems.append({
            "name": name,
            "version": pyproject.get("project", {}).get("version")
                       if name in {pyproject.get("project", {}).get("name")} else None,
            "manifest_path": manifest_rel,
            "scope_dir": scope_rel,
            "kind": "package",
            "dependencies": [{"name": d} for d in sorted(intra)],
            "external_imports": sorted(external),
        })

    project_name = (pyproject.get("project") or {}).get("name")
    project_version = (pyproject.get("project") or {}).get("version")
    declared = [
        d.split(";")[0].split("[")[0].split("=")[0].split(">")[0].split("<")[0].split("~")[0].strip()
        for d in (pyproject.get("project") or {}).get("dependencies") or []
        if isinstance(d, str)
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "layer": "systems",
        "stack": "python",
        "project_name": project_name,
        "project_version": project_version,
        "declared_dependencies": [d for d in declared if d],
        "source_tool": "python_ast_scan",
        "source_tool_note": (
            "Layer 1: each directory with __init__.py under the project source "
            "root(s) is a system. Intra-project dependency edges are derived "
            "from AST-parsed `import` / `from … import` statements; "
            "stdlib + third-party imports are listed per-system under "
            "`external_imports` but do NOT contribute edges."
        ),
        "systems": systems,
    }


# ---------------------------------------------------------------------------
# Layer 3 — definition lookup (visibility-agnostic)
# ---------------------------------------------------------------------------

# Allowed kinds for the Python symbol search. Other inputs (e.g. Rust-only
# kinds like "struct" / "trait") map to an empty result — not an error —
# because Layer 3 lives behind a stack-agnostic CLI flag.
_PYTHON_SYMBOL_KINDS = {"fn", "async fn", "class", "const"}


def _file_owning_system(rel_posix: str, scope_to_name: List[Tuple[str, str]]) -> Optional[str]:
    """Return the dotted system name for a file path, picking the deepest
    owning scope. `scope_to_name` is a pre-sorted list of (scope_dir, name).
    """
    best: Optional[str] = None
    best_depth = -1
    for scope, name in scope_to_name:
        if scope == "." or not scope:
            depth = 0
            owns = True
        else:
            owns = rel_posix == scope or rel_posix.startswith(scope + "/")
            depth = scope.count("/") + 1
        if owns and depth > best_depth:
            best, best_depth = name, depth
    return best


def find_symbol(project_root: Path, systems_doc: dict, name: str, want_kinds) -> List[dict]:
    """Walk every .py file owned by a system in `systems_doc` and return
    every top-level / method / module-const definition matching `name`.

    `want_kinds` is either the string "any" or a set of kind strings drawn
    from `{"fn", "async fn", "class", "const"}`. Anything else degrades to
    "any" defensively (so Rust-specific kinds yield no Python matches via
    the kind filter, but still don't 500).
    """
    # Normalise want_kinds.
    if isinstance(want_kinds, str):
        if want_kinds != "any":
            want_kinds = "any"
    elif isinstance(want_kinds, (set, frozenset, list, tuple)):
        filtered = {k for k in want_kinds if k in _PYTHON_SYMBOL_KINDS}
        if not filtered:
            # Caller passed only kinds we don't recognise (e.g. {"struct"}).
            # Honour the request by returning no matches rather than
            # silently widening it.
            return []
        want_kinds = filtered
    else:
        want_kinds = "any"

    project_root = project_root.resolve()
    systems = systems_doc.get("systems", []) or []
    # Sort scopes deepest-first preference handled inside _file_owning_system.
    scope_to_name: List[Tuple[str, str]] = [
        (s.get("scope_dir") or "", s["name"])
        for s in systems
        if s.get("name")
    ]
    if not scope_to_name:
        return []

    matches: List[dict] = []

    def _kind_ok(kind: str) -> bool:
        return want_kinds == "any" or kind in want_kinds

    for py_path in sorted(project_root.rglob("*.py")):
        try:
            rel = py_path.relative_to(project_root)
        except ValueError:
            continue
        rel_parts = rel.parts
        if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in rel_parts):
            continue
        rel_posix = rel.as_posix()
        owner = _file_owning_system(rel_posix, scope_to_name)
        if owner is None:
            continue

        try:
            src = py_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            tree = ast.parse(src, filename=str(py_path))
        except SyntaxError:
            continue
        src_lines = src.splitlines()

        def _record(node, kind: str, sig: str, ident: str) -> None:
            if ident != name or not _kind_ok(kind):
                return
            matches.append({
                "system": owner,
                "kind": kind,
                "name": ident,
                "file": rel_posix,
                "line": node.lineno,
                "signature": sig,
            })

        # Top-level only — don't ast.walk(), which would descend into
        # function bodies. Methods are surfaced by iterating ClassDef.body
        # one level deep.
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                sig = f"def {node.name}({_reconstruct_args(node.args)})"
                if node.returns:
                    sig += f" -> {_unparse(node.returns)}"
                kind = "async fn" if isinstance(node, ast.AsyncFunctionDef) else "fn"
                _record(node, kind, sig, node.name)
            elif isinstance(node, ast.ClassDef):
                bases = ", ".join(_unparse(b) for b in node.bases)
                class_sig = f"class {node.name}" + (f"({bases})" if bases else "")
                _record(node, "class", class_sig, node.name)
                # Methods: one level deep into the class body.
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        msig = f"def {sub.name}({_reconstruct_args(sub.args)})"
                        if sub.returns:
                            msig += f" -> {_unparse(sub.returns)}"
                        mkind = "async fn" if isinstance(sub, ast.AsyncFunctionDef) else "fn"
                        _record(sub, mkind, msig, sub.name)
            elif isinstance(node, ast.Assign):
                # Module-level NAME = ...; surface every Name target.
                # Use a short repr/snippet of the value.
                value_src = _unparse(node.value)[:80]
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        sig = f"{tgt.id} = {value_src}"
                        _record(node, "const", sig, tgt.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                # NAME: T = value  → also a const-ish binding.
                value_src = _unparse(node.value)[:80] if node.value is not None else ""
                ann = _unparse(node.annotation)
                sig = f"{node.target.id}: {ann}"
                if value_src:
                    sig += f" = {value_src}"
                _record(node, "const", sig, node.target.id)

    matches.sort(key=lambda m: (m["file"], m["line"]))
    return matches


def build_contract(project_root: Path, system_name: str, manifest_rel: str) -> dict:
    """Layer 2 stub: public top-level defs / classes / module-level names."""
    project_root = project_root.resolve()
    pyproject = _read_pyproject(project_root)
    source_roots = _find_source_roots(project_root, pyproject)

    pkg_dir: Optional[Path] = None
    for root in source_roots:
        candidate = root / Path(*system_name.split("."))
        if _is_package_dir(candidate):
            pkg_dir = candidate
            break
    if pkg_dir is None:
        return {
            "schema_version": SCHEMA_VERSION, "layer": "contract",
            "system": system_name, "stack": "python",
            "items": [], "note": "package directory not found",
        }

    # Only files directly inside the package (non-recursive) — sub-packages
    # are their own systems, so their surface belongs to them.
    items: List[dict] = []
    files_scanned = 0
    for py in sorted(pkg_dir.iterdir()):
        if not py.is_file() or py.suffix != ".py":
            continue
        rel = py.relative_to(project_root).as_posix()
        items.extend(_public_items_in_file(py, rel))
        files_scanned += 1

    counts: Dict[str, int] = {}
    for it in items:
        counts[it["kind"]] = counts.get(it["kind"], 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "layer": "contract",
        "system": system_name,
        "stack": "python",
        "source_tool": "python_ast_contract",
        "source_tool_note": (
            "Public surface = top-level `def` / `async def` / `class` whose "
            "names don't start with '_'. Module-level constants (UPPER_CASE "
            "assignments) are included as 'const' items. Only files directly "
            "inside the package are scanned; sub-packages are their own systems."
        ),
        "files_scanned": files_scanned,
        "counts": counts,
        "items": items,
        "item_count": len(items),
    }

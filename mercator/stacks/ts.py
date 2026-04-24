"""TypeScript / JavaScript stack — Layer 1 via `package.json` + `tsconfig.json`.

A TS/JS "system" is a single package. We discover them in three passes:

1. **Root package.** The `package.json` at the project root is always a system.
2. **npm/yarn/pnpm workspaces.** If the root `package.json` declares a
   `workspaces` array (or `{ "packages": [...] }` shape), each glob is
   expanded to find child `package.json` files. Each becomes its own system.
   (pnpm's `pnpm-workspace.yaml` is NOT parsed in this version — see the
   tool-note in the output document.)
3. **tsconfig.json project references.** Any `tsconfig.json` (root or
   workspace member) that declares `references: [{ "path": "./foo" }, ...]`
   contributes those referenced projects as systems with `kind: ["tsconfig-ref"]`,
   provided they don't already appear as an npm-package. This captures the
   TypeScript composite-project boundary, which is often finer than the
   package boundary (a single npm package can have multiple sub-projects).

Dependencies per package come from `dependencies`, `devDependencies`,
`peerDependencies`, `optionalDependencies`. `kind` is null for runtime
dependencies and "dev" / "peer" / "optional" respectively. Per-dep
`optional: true` is set when it came from optionalDependencies.

tsconfig.json is parsed tolerantly (supports `//` and `/* */` comments plus
trailing commas — i.e. JSONC, which the TS compiler itself accepts).
package.json is strict JSON.

Stdlib-only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path, PurePath
from typing import Dict, List, Optional, Set, Tuple

from mercator import SCHEMA_VERSION


# Directories we never descend into when expanding workspace globs or
# scanning for tsconfig.json — they contain artefacts or vendored copies,
# never source-of-truth package manifests.
SKIP_DIRS = {
    "node_modules",
    ".git",
    ".yarn",
    ".pnpm-store",
    "dist",
    "build",
    "out",
    "coverage",
    ".next",
    ".nuxt",
    ".turbo",
    ".cache",
    ".codemap",
    ".mercator",
}


# ---------------------------------------------------------------------------
# JSONC (JSON with Comments) — tsconfig.json dialect
# ---------------------------------------------------------------------------

def _strip_jsonc(text: str) -> str:
    """Remove `//` and `/* */` comments and trailing commas from a JSONC doc.

    Respects string literals (so `"//foo"` is preserved). Designed to be
    good enough for real-world tsconfig.json files, not a full JSONC parser.
    """
    out: List[str] = []
    i = 0
    n = len(text)
    in_str = False
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and nxt == "/":
            # Line comment — skip to newline (preserve the newline itself).
            j = i
            while j < n and text[j] != "\n":
                j += 1
            i = j
            continue
        if c == "/" and nxt == "*":
            # Block comment — skip through closing */.
            j = i + 2
            while j < n - 1 and not (text[j] == "*" and text[j + 1] == "/"):
                j += 1
            i = j + 2
            continue
        out.append(c)
        i += 1

    # Strip trailing commas: `, ]` or `, }` (including with whitespace between).
    cleaned = "".join(out)
    cleaned = re.sub(r",(\s*[\]}])", r"\1", cleaned)
    return cleaned


def _load_jsonc(path: Path) -> Optional[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    # Strip UTF-8 BOM if present.
    if text.startswith("﻿"):
        text = text[1:]
    try:
        return json.loads(_strip_jsonc(text))
    except json.JSONDecodeError:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if text.startswith("﻿"):
        text = text[1:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Workspace glob expansion
# ---------------------------------------------------------------------------

def _extract_workspace_globs(pkg: dict) -> List[str]:
    """Normalise the `workspaces` field across npm/yarn/pnpm conventions.

    npm + yarn classic use `"workspaces": ["packages/*", ...]`.
    yarn berry + some legacy setups use `"workspaces": {"packages": [...]}`.
    """
    ws = pkg.get("workspaces")
    if ws is None:
        return []
    if isinstance(ws, list):
        return [g for g in ws if isinstance(g, str)]
    if isinstance(ws, dict):
        packages = ws.get("packages")
        if isinstance(packages, list):
            return [g for g in packages if isinstance(g, str)]
    return []


def _expand_glob(project_root: Path, glob: str) -> List[Path]:
    """Expand a workspace glob to a list of directories containing package.json.

    Supports the common cases: literal path, `foo/*`, `foo/**`, `foo/*/bar`.
    Uses pathlib's glob which matches npm/yarn semantics for these shapes.
    """
    # Normalise: strip leading "./" and trailing "/".
    g = glob.strip().lstrip("./").rstrip("/")
    if not g:
        return []
    # Skip negation globs ("!pattern") — rare in practice, not supported here.
    if g.startswith("!"):
        return []
    results: List[Path] = []
    try:
        for match in project_root.glob(g):
            if not match.is_dir():
                continue
            # Skip any match under a SKIP_DIRS segment (e.g. node_modules).
            rel = match.relative_to(project_root)
            if any(part in SKIP_DIRS for part in rel.parts):
                continue
            if (match / "package.json").is_file():
                results.append(match)
    except (OSError, ValueError):
        pass
    return results


# ---------------------------------------------------------------------------
# Dependency extraction
# ---------------------------------------------------------------------------

_DEP_FIELDS: List[Tuple[str, Optional[str], bool]] = [
    ("dependencies", None, False),
    ("devDependencies", "dev", False),
    ("peerDependencies", "peer", False),
    ("optionalDependencies", "optional", True),
]


def _extract_deps(pkg: dict) -> List[dict]:
    deps: List[dict] = []
    seen: Set[Tuple[str, Optional[str]]] = set()
    for field, kind, optional in _DEP_FIELDS:
        block = pkg.get(field)
        if not isinstance(block, dict):
            continue
        for name in block.keys():
            if not isinstance(name, str):
                continue
            key = (name, kind)
            if key in seen:
                continue
            seen.add(key)
            deps.append({"name": name, "kind": kind, "optional": optional})
    # Stable-sort by (kind-order, name) for deterministic output. Runtime deps
    # first, then dev, then peer, then optional.
    kind_rank = {None: 0, "dev": 1, "peer": 2, "optional": 3}
    deps.sort(key=lambda d: (kind_rank.get(d["kind"], 9), d["name"]))
    return deps


# ---------------------------------------------------------------------------
# tsconfig.json project references
# ---------------------------------------------------------------------------

def _resolve_ts_ref(ref_path: str, from_dir: Path) -> Optional[Path]:
    """Resolve a tsconfig `references[].path` to an absolute tsconfig path.

    The TS compiler accepts either a directory (looks for tsconfig.json inside)
    or an explicit .json filename.
    """
    if not ref_path:
        return None
    candidate = (from_dir / ref_path).resolve()
    if candidate.is_file() and candidate.suffix == ".json":
        return candidate
    if candidate.is_dir():
        tc = candidate / "tsconfig.json"
        if tc.is_file():
            return tc
    # Missing — may be a stale ref. Skip silently.
    return None


def _collect_ts_references(
    project_root: Path,
    tsconfig_paths: List[Path],
) -> List[Tuple[str, Path, Path]]:
    """Walk tsconfig references transitively. Returns [(name, tsconfig_path, scope_dir)].

    `name` is derived from the directory the tsconfig lives in (relative to
    project root). Duplicates across the walk are de-duped by resolved path.
    """
    visited: Set[Path] = set()
    results: List[Tuple[str, Path, Path]] = []
    queue: List[Path] = list(tsconfig_paths)

    while queue:
        tc = queue.pop(0)
        try:
            tc_resolved = tc.resolve()
        except OSError:
            continue
        if tc_resolved in visited:
            continue
        visited.add(tc_resolved)

        data = _load_jsonc(tc_resolved)
        if data is None:
            continue

        scope_dir = tc_resolved.parent
        try:
            rel = scope_dir.relative_to(project_root.resolve())
        except ValueError:
            continue
        # Skip tsconfigs buried in skip-dirs (e.g. node_modules).
        if any(part in SKIP_DIRS for part in rel.parts):
            continue

        name = rel.as_posix() or "."
        results.append((name, tc_resolved, scope_dir))

        refs = data.get("references")
        if isinstance(refs, list):
            for ref in refs:
                if not isinstance(ref, dict):
                    continue
                ref_path = ref.get("path")
                if not isinstance(ref_path, str):
                    continue
                target = _resolve_ts_ref(ref_path, scope_dir)
                if target is not None:
                    queue.append(target)

    return results


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_systems(project_root: Path) -> dict:
    project_root = project_root.resolve()
    root_pkg_path = project_root / "package.json"
    root_pkg = _load_json(root_pkg_path) if root_pkg_path.is_file() else None

    # Map from resolved package dir → system-dict so we can dedupe
    # between workspace expansion and later tsconfig-ref pass.
    systems_by_dir: Dict[Path, dict] = {}
    name_counts: Dict[str, int] = {}

    def _register_package(pkg_dir: Path, pkg: dict, is_root: bool) -> None:
        rel_manifest = PurePath(
            str((pkg_dir / "package.json").relative_to(project_root))
        ).as_posix()
        rel_scope = PurePath(str(pkg_dir.relative_to(project_root))).as_posix() or "."
        raw_name = pkg.get("name")
        if not isinstance(raw_name, str) or not raw_name:
            # Unnamed (common for private root packages): fall back to dir name,
            # or "<root>" at project root.
            raw_name = "<root>" if is_root else pkg_dir.name
        # Handle scoped packages: "@scope/foo" is used verbatim as the name.
        name = raw_name
        if name in name_counts:
            # Disambiguate by path to keep the roster stable.
            name_counts[name] += 1
            name = f"{raw_name} ({rel_scope})"
        else:
            name_counts[raw_name] = 1

        version = pkg.get("version")
        if not isinstance(version, str):
            version = None

        private = pkg.get("private") is True

        entry = {
            "name": name,
            "version": version,
            "manifest_path": rel_manifest,
            "scope_dir": rel_scope,
            "kind": ["npm-package"],
            "private": private,
            "dependencies": _extract_deps(pkg),
        }
        systems_by_dir[pkg_dir.resolve()] = entry

    # 1. Root package.
    if root_pkg is not None:
        _register_package(project_root, root_pkg, is_root=True)

    # 2. Workspace globs.
    if root_pkg is not None:
        for glob in _extract_workspace_globs(root_pkg):
            for pkg_dir in _expand_glob(project_root, glob):
                resolved = pkg_dir.resolve()
                if resolved in systems_by_dir:
                    continue
                sub_pkg = _load_json(pkg_dir / "package.json")
                if sub_pkg is None:
                    continue
                _register_package(pkg_dir, sub_pkg, is_root=False)

    # 3. tsconfig.json project references (adds tsconfig-ref systems for any
    #    referenced project that wasn't already registered as an npm package).
    seed_tsconfigs: List[Path] = []
    root_tc = project_root / "tsconfig.json"
    if root_tc.is_file():
        seed_tsconfigs.append(root_tc)
    # Also seed from every workspace member's tsconfig.json, since monorepos
    # often don't have a root tsconfig but each package has its own.
    for pkg_dir in list(systems_by_dir.keys()):
        tc = pkg_dir / "tsconfig.json"
        if tc.is_file() and tc not in seed_tsconfigs:
            seed_tsconfigs.append(tc)

    tsconfig_refs = _collect_ts_references(project_root, seed_tsconfigs)

    # Attach tsconfig-ref info to existing npm-package systems where the dirs
    # match; emit standalone tsconfig-ref systems otherwise.
    for ref_name, tc_path, scope_dir in tsconfig_refs:
        scope_resolved = scope_dir.resolve()
        if scope_resolved in systems_by_dir:
            entry = systems_by_dir[scope_resolved]
            if "tsconfig-ref" not in entry["kind"]:
                entry["kind"].append("tsconfig-ref")
            # Record the tsconfig path alongside the package manifest.
            rel_tc = PurePath(str(tc_path.relative_to(project_root))).as_posix()
            entry.setdefault("tsconfig_paths", []).append(rel_tc)
            continue
        # Standalone tsconfig-only system.
        rel_tc = PurePath(str(tc_path.relative_to(project_root))).as_posix()
        rel_scope = PurePath(str(scope_resolved.relative_to(project_root))).as_posix() or "."
        name = ref_name
        if name in name_counts:
            name_counts[name] += 1
            name = f"{ref_name} ({rel_scope})"
        else:
            name_counts[ref_name] = 1
        systems_by_dir[scope_resolved] = {
            "name": name,
            "version": None,
            "manifest_path": rel_tc,
            "scope_dir": rel_scope,
            "kind": ["tsconfig-ref"],
            "private": True,
            "dependencies": [],
        }

    systems = list(systems_by_dir.values())
    systems.sort(key=lambda s: s["name"])

    return {
        "schema_version": SCHEMA_VERSION,
        "layer": "systems",
        "stack": "ts",
        "workspace_root": ".",
        "source_tool": "ts_package_scan",
        "source_tool_note": (
            "Layer 1 built from package.json (root + npm/yarn workspaces globs) "
            "and tsconfig.json project references. pnpm-workspace.yaml is not "
            "parsed — pnpm monorepos using that format will only show the root "
            "package. Negation globs ('!pattern') in workspaces are ignored."
        ),
        "systems": systems,
    }

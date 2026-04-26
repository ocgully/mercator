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
import os
import re
from pathlib import Path, PurePath
from typing import Dict, List, Optional, Set, Tuple

from codeatlas import SCHEMA_VERSION


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
    ".codeatlas",
    ".mercator",
    ".codemap",
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


# ---------------------------------------------------------------------------
# Layer 2 — public-surface (`export …`) scanner
# ---------------------------------------------------------------------------
#
# Regex-based, stdlib-only. Mirrors the Rust `pub`-item scanner: per-file,
# blank out comments/strings/regex/template-literals so they can't produce
# false matches, compute per-line brace depth so we only consider top-level
# declarations, then match a small set of regexes against each top-level
# line. Aims for ~90% of real-world declarations — documented limitations
# appear in `source_tool_note` so users know what's missed.


# Skip file name suffixes (on top of SKIP_DIRS which is used for dir-walk).
_TS_SKIP_FILE_SUFFIXES = (".d.ts", ".test.ts", ".spec.ts",
                          ".test.tsx", ".spec.tsx")


def _strip_ts_source(text: str) -> str:
    """Blank out comments and string/template/regex literals in `text`.

    Produces a same-length buffer with only "code" bytes un-masked so the
    scanner + depth tracker agree on what counts as code. Newlines are
    preserved so line numbers stay stable.

    Template literals (`...${…}...`) are partially handled: backtick-delimited
    spans are blanked, but nested `${ expr }` interpolation is also blanked
    (we don't try to re-enable code inside interpolations — nested braces
    inside `${}` would still contribute to brace-depth in a fully-accurate
    parser, but regex-scanner-fidelity is intentionally close to the Rust
    pattern).
    """
    out = list(text)
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""

        # Line comment //…
        if c == "/" and nxt == "/":
            j = i
            while j < n and text[j] != "\n":
                out[j] = " "
                j += 1
            i = j
            continue

        # Block comment /* … */
        if c == "/" and nxt == "*":
            out[i] = " "
            out[i + 1] = " "
            j = i + 2
            while j < n:
                if text[j] == "*" and j + 1 < n and text[j + 1] == "/":
                    out[j] = " "
                    out[j + 1] = " "
                    j += 2
                    break
                if text[j] != "\n":
                    out[j] = " "
                j += 1
            i = j
            continue

        # String literal " … " or ' … '
        if c == '"' or c == "'":
            quote = c
            out[i] = " "
            j = i + 1
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    if text[j] != "\n":
                        out[j] = " "
                    if text[j + 1] != "\n":
                        out[j + 1] = " "
                    j += 2
                    continue
                if text[j] == quote:
                    out[j] = " "
                    j += 1
                    break
                if text[j] == "\n":
                    # Unterminated on this line — bail to avoid runaway.
                    break
                out[j] = " "
                j += 1
            i = j
            continue

        # Template literal ` … ` (including ${ … } interpolation)
        if c == "`":
            out[i] = " "
            j = i + 1
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    if text[j] != "\n":
                        out[j] = " "
                    if text[j + 1] != "\n":
                        out[j + 1] = " "
                    j += 2
                    continue
                if text[j] == "`":
                    out[j] = " "
                    j += 1
                    break
                if text[j] != "\n":
                    out[j] = " "
                j += 1
            i = j
            continue

        i += 1
    return "".join(out)


def _line_depths(cleaned: str) -> List[int]:
    """Per-line brace depth at the START of each line (1-indexed via [line-1])."""
    depths = [0]
    depth = 0
    for ch in cleaned:
        if ch == "\n":
            depths.append(depth)
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
    return depths


# --- Export regexes (applied to cleaned top-level lines, leading WS stripped) ---
# We match the DECLARATION-form exports. `export { ... }` (local re-exports
# without `from`) is handled separately because it can span multiple lines.

_EXPORT_PREFIX = r"export\s+"

_RE_FUNCTION = re.compile(
    _EXPORT_PREFIX + r"(?P<async>async\s+)?function\s*\*?\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)"
    r"(?P<rest>.*)$"
)
_RE_DEFAULT_FUNCTION = re.compile(
    _EXPORT_PREFIX + r"default\s+(?P<async>async\s+)?function\s*\*?\s*"
    r"(?P<name>[A-Za-z_$][\w$]*)?"
    r"(?P<rest>.*)$"
)
_RE_CLASS = re.compile(
    _EXPORT_PREFIX + r"(?:abstract\s+)?class\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)"
    r"(?P<rest>.*)$"
)
_RE_DEFAULT_CLASS = re.compile(
    _EXPORT_PREFIX + r"default\s+(?:abstract\s+)?class\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)?"
    r"(?P<rest>.*)$"
)
_RE_INTERFACE = re.compile(
    _EXPORT_PREFIX + r"interface\s+(?P<name>[A-Za-z_$][\w$]*)(?P<rest>.*)$"
)
_RE_TYPE = re.compile(
    _EXPORT_PREFIX + r"type\s+(?P<name>[A-Za-z_$][\w$]*)\s*(?P<gens><[^=]*>)?\s*=\s*"
    r"(?P<rhs>.*)$"
)
_RE_ENUM = re.compile(
    _EXPORT_PREFIX + r"(?:const\s+)?enum\s+(?P<name>[A-Za-z_$][\w$]*)(?P<rest>.*)$"
)
_RE_VAR = re.compile(
    _EXPORT_PREFIX + r"(?P<kw>const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)"
    r"(?P<rest>.*)$"
)
# `export * from "./mod"` or `export * as ns from "./mod"`
_RE_STAR_FROM = re.compile(
    _EXPORT_PREFIX + r"\*\s*(?:as\s+(?P<alias>[A-Za-z_$][\w$]*)\s+)?from\s*"
    r"[\"'](?P<mod>[^\"']+)[\"']"
)
# `export { a, b as c } [from "./mod"];` — may span multiple lines. We detect
# the opening `export {` and capture through the closing `}`.
_RE_NAMED_OPEN = re.compile(_EXPORT_PREFIX + r"(?:type\s+)?\{(?P<body>.*)$")

_RE_DEFAULT_EXPR = re.compile(_EXPORT_PREFIX + r"default\b(?P<rest>.*)$")


def _parse_named_members(body: str) -> List[str]:
    """Parse the content of `export { … }` into the exported (external) names.

    For `foo, bar as baz`, returns ["foo", "baz"].
    """
    names: List[str] = []
    for raw in body.split(","):
        part = raw.strip()
        if not part:
            continue
        # Handle `type foo` / `type foo as bar` (TS 3.8+ type-only specifier).
        if part.startswith("type "):
            part = part[5:].strip()
        m = re.match(r"([A-Za-z_$][\w$]*|default)(?:\s+as\s+([A-Za-z_$][\w$]*))?\s*$", part)
        if not m:
            continue
        names.append(m.group(2) or m.group(1))
    return names


def _trim_signature(s: str, maxlen: int = 140) -> str:
    s = s.strip()
    if len(s) > maxlen:
        s = s[: maxlen - 3] + "..."
    return s


def _scan_ts_file(path: Path, scope_dir: Path) -> List[dict]:
    """Return public-surface items for a single .ts/.tsx file."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
    # Strip UTF-8 BOM so the first line matches cleanly.
    if text.startswith("﻿"):
        text = text[1:]

    cleaned = _strip_ts_source(text)
    depths = _line_depths(cleaned)
    cleaned_lines = cleaned.splitlines()
    orig_lines = text.splitlines()

    try:
        rel_file = PurePath(str(path.relative_to(scope_dir))).as_posix()
    except ValueError:
        rel_file = path.name

    items: List[dict] = []
    i = 0
    n = len(cleaned_lines)
    while i < n:
        line_no = i + 1
        if i >= len(depths) or depths[i] != 0:
            i += 1
            continue
        cleaned_line = cleaned_lines[i]
        cleaned_stripped = cleaned_line.lstrip()
        # Fast pre-filter: the `export` keyword must exist at start of line
        # AFTER comments/strings are blanked (so commented-out `// export …`
        # won't match, nor will occurrences inside string literals).
        if not cleaned_stripped.startswith("export"):
            i += 1
            continue
        after = cleaned_stripped[6:7]
        if after and after not in (" ", "\t", "{", "*"):
            i += 1
            continue

        # Run detailed regex matching against the ORIGINAL line so string
        # literals ("./mod" in re-exports) and type annotations are preserved.
        orig_line = orig_lines[i] if i < len(orig_lines) else cleaned_line
        orig_stripped = orig_line.strip()
        stripped = orig_line.lstrip()

        # `export * from "..."` / `export * as ns from "..."`
        m = _RE_STAR_FROM.match(stripped)
        if m:
            alias = m.group("alias")
            if alias:
                items.append({
                    "kind": "re-export", "name": alias, "file": rel_file,
                    "line": line_no,
                    "signature": f"export * as {alias} from \"{m.group('mod')}\"",
                })
            else:
                items.append({
                    "kind": "re-export", "name": "*", "file": rel_file,
                    "line": line_no,
                    "signature": f"export * from \"{m.group('mod')}\"",
                })
            i += 1
            continue

        # `export function foo(...)` / `export async function foo(...)`
        m = _RE_FUNCTION.match(stripped)
        if m:
            kind = "async fn" if m.group("async") else "fn"
            items.append({
                "kind": kind, "name": m.group("name"), "file": rel_file,
                "line": line_no,
                "signature": _trim_signature(orig_stripped),
            })
            i += 1
            continue

        # `export default function foo(...)` (name optional)
        m = _RE_DEFAULT_FUNCTION.match(stripped)
        if m:
            kind = "async fn" if m.group("async") else "fn"
            inner = m.group("name")
            name = f"default({inner})" if inner else "default"
            items.append({
                "kind": kind, "name": name, "file": rel_file,
                "line": line_no,
                "signature": _trim_signature(orig_stripped),
            })
            i += 1
            continue

        # `export [abstract] class Foo ...`
        m = _RE_CLASS.match(stripped)
        if m:
            items.append({
                "kind": "class", "name": m.group("name"), "file": rel_file,
                "line": line_no,
                "signature": _trim_signature(orig_stripped),
            })
            i += 1
            continue

        # `export default class Foo` (name optional)
        m = _RE_DEFAULT_CLASS.match(stripped)
        if m:
            inner = m.group("name")
            name = f"default({inner})" if inner else "default"
            items.append({
                "kind": "class", "name": name, "file": rel_file,
                "line": line_no,
                "signature": _trim_signature(orig_stripped),
            })
            i += 1
            continue

        # `export interface Foo …`
        m = _RE_INTERFACE.match(stripped)
        if m:
            items.append({
                "kind": "interface", "name": m.group("name"), "file": rel_file,
                "line": line_no,
                "signature": _trim_signature(orig_stripped),
            })
            i += 1
            continue

        # `export type Foo = …`
        m = _RE_TYPE.match(stripped)
        if m:
            rhs = m.group("rhs").rstrip().rstrip(";").strip()
            if len(rhs) > 80:
                rhs = rhs[:77] + "..."
            sig = f"type {m.group('name')} = {rhs}"
            items.append({
                "kind": "type", "name": m.group("name"), "file": rel_file,
                "line": line_no,
                "signature": _trim_signature(sig),
            })
            i += 1
            continue

        # `export enum Foo …` / `export const enum Foo …`
        m = _RE_ENUM.match(stripped)
        if m:
            items.append({
                "kind": "enum", "name": m.group("name"), "file": rel_file,
                "line": line_no,
                "signature": _trim_signature(orig_stripped),
            })
            i += 1
            continue

        # `export const/let/var foo [= …]`
        m = _RE_VAR.match(stripped)
        if m:
            items.append({
                "kind": "const", "name": m.group("name"), "file": rel_file,
                "line": line_no,
                "signature": _trim_signature(orig_stripped),
            })
            i += 1
            continue

        # `export { a, b as c } [from "…"]` — possibly multi-line.
        m = _RE_NAMED_OPEN.match(stripped)
        if m:
            # Collect until the matching `}`.
            body_chunks: List[str] = []
            body_chunks.append(m.group("body"))
            # Does the opening line close?
            end_line = i
            closed = False
            if "}" in m.group("body"):
                closed = True
            else:
                j = i + 1
                while j < n and j < i + 200:
                    body_chunks.append(cleaned_lines[j])
                    if "}" in cleaned_lines[j]:
                        end_line = j
                        closed = True
                        break
                    j += 1
            if not closed:
                i += 1
                continue
            joined = " ".join(body_chunks)
            # Split at the closing brace — names live before it; "from" clause after.
            brace_end = joined.find("}")
            body = joined[:brace_end] if brace_end != -1 else joined
            names = _parse_named_members(body)
            sig = _trim_signature(orig_stripped)
            for name in names:
                items.append({
                    "kind": "re-export", "name": name, "file": rel_file,
                    "line": line_no,
                    "signature": sig,
                })
            i = end_line + 1
            continue

        # `export default <expr>;` — fall-through default value export.
        m = _RE_DEFAULT_EXPR.match(stripped)
        if m:
            items.append({
                "kind": "const", "name": "default", "file": rel_file,
                "line": line_no,
                "signature": _trim_signature(orig_stripped),
            })
            i += 1
            continue

        i += 1

    return items


def _ts_source_files(scope_dir: Path, child_scope_dirs: Set[Path]) -> List[Path]:
    """Walk `*.ts`/`*.tsx` under `scope_dir`, skipping SKIP_DIRS and any
    subtree owned by another system (child_scope_dirs).

    Declaration files (`.d.ts`), tests, and specs are also skipped.
    """
    out: List[Path] = []
    if not scope_dir.is_dir():
        return out

    def _walk(d: Path) -> None:
        try:
            entries = list(d.iterdir())
        except OSError:
            return
        for entry in entries:
            try:
                if entry.is_dir():
                    if entry.name in SKIP_DIRS:
                        continue
                    if entry.resolve() in child_scope_dirs:
                        continue
                    _walk(entry)
                elif entry.is_file():
                    name = entry.name
                    # Skip .d.ts, .test.*, .spec.*
                    if name.endswith(_TS_SKIP_FILE_SUFFIXES):
                        continue
                    if name.endswith(".ts") or name.endswith(".tsx"):
                        out.append(entry)
            except OSError:
                continue

    _walk(scope_dir)
    out.sort()
    return out


def build_contract(project_root: Path, system_name: str,
                   manifest_rel: str) -> dict:
    """Layer 2: public exports from a TS system's `.ts`/`.tsx` source files.

    `manifest_rel` is the system's manifest path (package.json OR tsconfig.json)
    relative to the project root. The system's scope is the manifest's parent
    directory (mirroring `scope_dir` in systems.json).
    """
    project_root = project_root.resolve()
    manifest = (project_root / manifest_rel).resolve()
    scope_dir = manifest.parent

    # Load systems.json's sibling data from memory by re-running build_systems,
    # purely to discover child-system scope_dirs we should NOT recurse into.
    # (Matches Python stack behaviour: sub-packages belong to themselves.)
    child_scopes: Set[Path] = set()
    try:
        sys_doc = build_systems(project_root)
    except Exception:  # noqa: BLE001
        sys_doc = {"systems": []}
    scope_resolved = scope_dir.resolve()
    for s in sys_doc.get("systems", []):
        s_scope = s.get("scope_dir") or ""
        if not s_scope or s_scope == ".":
            other = project_root
        else:
            other = (project_root / s_scope).resolve()
        if other == scope_resolved:
            continue
        # Only treat as a "child" if it's strictly under scope_resolved.
        try:
            other.relative_to(scope_resolved)
        except ValueError:
            continue
        if other != scope_resolved:
            child_scopes.add(other)

    files = _ts_source_files(scope_dir, child_scopes)

    items: List[dict] = []
    for f in files:
        items.extend(_scan_ts_file(f, scope_dir))

    items.sort(key=lambda it: (it["file"], it["line"], it["name"]))

    counts: Dict[str, int] = {}
    for it in items:
        counts[it["kind"]] = counts.get(it["kind"], 0) + 1

    try:
        scope_rel = PurePath(
            os.path.relpath(str(scope_dir), str(project_root))
        ).as_posix()
    except ValueError:
        scope_rel = None

    doc = {
        "schema_version": SCHEMA_VERSION,
        "layer": "contract",
        "system": system_name,
        "stack": "ts",
        "source_tool": "ts_export_scan",
        "source_tool_note": (
            "Regex scan of top-level `export …` declarations in .ts/.tsx files "
            "under the system's scope directory (skipping SKIP_DIRS, .d.ts, "
            "*.test.*, *.spec.*, and subtrees owned by another system). "
            "Detects: function / async function / class / interface / type / "
            "enum (incl. const enum) / const-let-var / default function|class / "
            "re-exports (`export { a, b as c } [from …]` and `export * [as n] "
            "from …`). KNOWN GAPS: exports nested inside `namespace {}` / "
            "`module {}` / `declare …` blocks are missed (top-level-only scan); "
            "computed export names, decorator-generated declarations, and "
            "TypeScript-plugin / macro-expanded types are not resolved; "
            "`export = foo` (CommonJS-style) is not detected; `export default "
            "<expression>` is surfaced as a single `const` named `default`."
        ),
        "files_scanned": len(files),
        "counts": counts,
        "items": items,
        "item_count": len(items),
    }
    if scope_rel is not None:
        doc["scope_dir"] = scope_rel
    return doc

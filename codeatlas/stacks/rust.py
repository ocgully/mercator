"""Rust stack — Layers 1 (cargo metadata), 2 (pub-item scan), 3 (definition lookup).

All paths emitted into JSON are relative to the project root so committed
`.codeatlas/` files are portable.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path, PurePath
from typing import Iterable, List, Optional, Set

from codeatlas import SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Layer 1 — cargo metadata → systems.json
# ---------------------------------------------------------------------------

def build_systems(project_root: Path) -> dict:
    """Run `cargo metadata --no-deps` and return the canonical systems doc."""
    if not shutil.which("cargo"):
        raise RuntimeError("cargo not on PATH — install Rust toolchain to build Rust Layer 1")

    out = subprocess.run(
        ["cargo", "metadata", "--format-version", "1", "--no-deps"],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if out.returncode != 0:
        raise RuntimeError(f"cargo metadata failed: {out.stderr.strip()}")

    raw = json.loads(out.stdout)
    # Paths in the output are rebased to `project_root`, not to the
    # cargo-discovered workspace root. When project_root is itself a member
    # crate of a larger workspace, the project's atlas page should live at
    # its own root — `manifest_path` like "Cargo.toml", not
    # "crates/bevy_a11y/Cargo.toml".
    project_root_resolved = project_root.resolve()

    def rel(p: str) -> str:
        try:
            return PurePath(os.path.relpath(p, project_root_resolved)).as_posix()
        except ValueError:
            return p  # different drive — fall back, rare

    # A project corresponds to exactly one Cargo.toml — the one at its
    # `project_root`. cargo metadata returns every workspace member when
    # run from a member crate; we filter to only the package whose manifest
    # is `<project_root>/Cargo.toml`. Sibling workspace members are their
    # own projects and live on their own atlas pages.
    own_manifest = (project_root_resolved / "Cargo.toml").resolve()

    def _belongs_to_project(manifest_path: str) -> bool:
        if not manifest_path:
            return False
        try:
            return Path(manifest_path).resolve() == own_manifest
        except OSError:
            return False

    systems: List[dict] = []
    # Workspace members only (local packages have source=null).
    for pkg in raw.get("packages", []):
        if pkg.get("source") is not None:
            continue
        if not _belongs_to_project(pkg.get("manifest_path", "")):
            continue  # sibling workspace member — its own project
        kinds = sorted({k for t in pkg.get("targets", []) for k in t.get("kind", [])})
        deps = [
            {
                "name": d.get("name"),
                "kind": d.get("kind"),
                "optional": d.get("optional", False),
            }
            for d in pkg.get("dependencies", [])
        ]
        systems.append({
            "name": pkg.get("name"),
            "version": pkg.get("version"),
            "manifest_path": rel(pkg.get("manifest_path", "")),
            "kind": kinds,
            "dependencies": deps,
        })
    systems.sort(key=lambda s: s["name"])

    return {
        "schema_version": SCHEMA_VERSION,
        "layer": "systems",
        "stack": "rust",
        "workspace_root": ".",
        "systems": systems,
    }


# ---------------------------------------------------------------------------
# Layer 2 — `pub` item scanner
# ---------------------------------------------------------------------------

ITEM_RE = re.compile(
    r"""^pub\s+
        (?:(?:async|unsafe|const|extern(?:\s+"[^"]*")?|default)\s+)*
        (fn|struct|enum|trait|type|const|static|use|mod)\b
        (.*)$""",
    re.VERBOSE,
)

IDENT_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)")


def strip_rust_source(text: str) -> str:
    """Blank out comments, string literals, char literals in `text`.

    Newlines are preserved so line numbers stay stable. The result is a
    string of the same length with only "code" bytes un-masked. Used by
    both the Layer 2 scanner and the Layer 3 symbol finder so they agree on
    what counts as code.
    """
    out = list(text)
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""

        if c == "/" and nxt == "/":
            j = i
            while j < n and text[j] != "\n":
                out[j] = " "; j += 1
            i = j
            continue

        if c == "/" and nxt == "*":
            depth = 1
            out[i] = " "; out[i + 1] = " "
            j = i + 2
            while j < n and depth > 0:
                if text[j] == "/" and j + 1 < n and text[j + 1] == "*":
                    depth += 1; out[j] = " "; out[j + 1] = " "; j += 2
                elif text[j] == "*" and j + 1 < n and text[j + 1] == "/":
                    depth -= 1; out[j] = " "; out[j + 1] = " "; j += 2
                else:
                    if text[j] != "\n": out[j] = " "
                    j += 1
            i = j
            continue

        if c == "r" and (nxt == '"' or nxt == "#"):
            k = i + 1
            hashes = 0
            while k < n and text[k] == "#":
                hashes += 1; k += 1
            if k < n and text[k] == '"':
                for m in range(i, k + 1): out[m] = " "
                j = k + 1
                closer = '"' + ("#" * hashes)
                while j < n:
                    if text[j:j + len(closer)] == closer:
                        for m in range(j, j + len(closer)): out[m] = " "
                        j += len(closer); break
                    if text[j] != "\n": out[j] = " "
                    j += 1
                i = j
                continue

        if c == '"' or (c == "b" and nxt == '"'):
            if c == "b":
                out[i] = " "; i += 1
            out[i] = " "
            j = i + 1
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    if text[j] != "\n": out[j] = " "
                    if text[j + 1] != "\n": out[j + 1] = " "
                    j += 2
                    continue
                if text[j] == '"':
                    out[j] = " "; j += 1; break
                if text[j] != "\n": out[j] = " "
                j += 1
            i = j
            continue

        if c == "'" or (c == "b" and nxt == "'"):
            start = i
            probe_start = i + (2 if c == "b" else 1)
            close = -1
            k = probe_start
            while k < n and k - probe_start < 10:
                if text[k] == "\\" and k + 1 < n:
                    k += 2; continue
                if text[k] == "'": close = k; break
                if text[k] == "\n": break
                k += 1
            if close != -1:
                for m in range(start, close + 1):
                    if text[m] != "\n": out[m] = " "
                i = close + 1
                continue
            i += 1
            continue

        i += 1
    return "".join(out)


def _line_depths(cleaned: str) -> List[int]:
    """Per-line brace depth at the start of each line (1-indexed lines)."""
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


def _use_expand(rest: str) -> List[str]:
    """Expand `pub use foo::{A, B as C, D};` into ['A', 'C', 'D']; scalar → [last-seg-or-alias]."""
    rest = rest.rstrip().rstrip(";").strip()
    # Grouped: has `{...}` at top level.
    open_br = rest.find("{")
    close_br = rest.rfind("}")
    if open_br != -1 and close_br > open_br:
        inner = rest[open_br + 1:close_br]
        names = []
        for part in inner.split(","):
            part = part.strip()
            if not part or part == "*":
                continue
            tokens = part.split()
            if "as" in tokens:
                idx = tokens.index("as")
                if idx + 1 < len(tokens):
                    names.append(tokens[idx + 1].strip(",;}{ "))
                    continue
            # Drop path prefix, take final segment.
            names.append(part.rsplit("::", 1)[-1].strip())
        return [n for n in names if n]

    tokens = rest.split()
    if "as" in tokens:
        idx = len(tokens) - 1 - tokens[::-1].index("as")
        if idx + 1 < len(tokens):
            alias = tokens[idx + 1].strip(",;}{ ")
            if alias:
                return [alias]
    head = rest.split("{", 1)[0].rstrip(": ")
    if head:
        last = head.rsplit("::", 1)[-1]
        if last:
            return [last]
    return [rest] if rest else []


def _ident_for(kind: str, rest: str) -> str:
    if kind == "use":
        parts = _use_expand(rest)
        return parts[0] if parts else "?"
    m = IDENT_RE.match(rest.lstrip())
    return m.group(1) if m else "?"


def _source_files(crate_root: Path) -> List[Path]:
    src = crate_root / "src"
    if not src.is_dir():
        return []
    files: List[Path] = []
    for p in src.rglob("*.rs"):
        rel = p.relative_to(crate_root).parts[1:]
        if any(part in ("tests", "examples", "benches", "target") for part in rel):
            continue
        files.append(p)
    files.sort()
    return files


def _scan_file(path: Path, crate_root: Path) -> List[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")
    cleaned = strip_rust_source(text)
    depths = _line_depths(cleaned)
    cleaned_lines = cleaned.splitlines()
    orig_lines = text.splitlines()

    items: List[dict] = []
    for i, cleaned_line in enumerate(cleaned_lines, start=1):
        if i - 1 >= len(depths) or depths[i - 1] != 0:
            continue
        stripped = cleaned_line.lstrip()
        if not stripped.startswith("pub"):
            continue
        if stripped.startswith(("pub(crate)", "pub(super)", "pub(in ", "pub(self)")):
            continue
        if not (stripped[3:4] in (" ", "\t")):
            continue

        m = ITEM_RE.match(stripped)
        if not m:
            continue

        kind = m.group(1)
        rest = m.group(2)
        signature = orig_lines[i - 1].strip() if i - 1 < len(orig_lines) else stripped
        rel_file = PurePath(str(path.relative_to(crate_root))).as_posix()

        if kind == "use":
            names = _use_expand(rest) or ["?"]
            for name in names:
                items.append({"name": name, "kind": "use", "signature": signature, "file": rel_file, "line": i})
        else:
            items.append({
                "name": _ident_for(kind, rest),
                "kind": kind,
                "signature": signature,
                "file": rel_file,
                "line": i,
            })
    return items


def build_contract(project_root: Path, system_name: str, manifest_rel: str) -> dict:
    manifest = (project_root / manifest_rel).resolve()
    if not manifest.is_file():
        raise FileNotFoundError(f"manifest not found: {manifest}")
    crate_root = manifest.parent

    files = _source_files(crate_root)
    items: List[dict] = []
    for f in files:
        items.extend(_scan_file(f, crate_root))
    items.sort(key=lambda it: (it["file"], it["line"]))

    counts: dict = {}
    for it in items:
        counts[it["kind"]] = counts.get(it["kind"], 0) + 1

    try:
        crate_rel = PurePath(os.path.relpath(str(crate_root), project_root)).as_posix()
    except ValueError:
        crate_rel = None

    doc = {
        "schema_version": SCHEMA_VERSION,
        "layer": "contracts",
        "stack": "rust",
        "system": system_name,
        "source_tool": "rust_pub_scan",
        "source_tool_note": (
            "Line-scan of `pub` items at file top-level. Misses items nested inside `mod {}` "
            "blocks and macro-generated items. Higher fidelity available via "
            "`cargo-public-api` (nightly)."
        ),
        "files_scanned": len(files),
        "items": items,
        "counts": counts,
    }
    if crate_rel:
        doc["crate_root"] = crate_rel
    return doc


# ---------------------------------------------------------------------------
# Layer 3 — definition lookup (visibility-agnostic)
# ---------------------------------------------------------------------------

DEFN_RE = re.compile(
    r"""^(?:pub(?:\([^)]*\))?\s+)?
        (?:(?:async|unsafe|const|extern(?:\s+"[^"]*")?|default)\s+)*
        (fn|struct|enum|trait|type|const|static|mod)\s+
        ([A-Za-z_][A-Za-z0-9_]*)
        (.*)$""",
    re.VERBOSE,
)


def find_symbol(project_root: Path, systems_doc: dict, name: str, want_kinds) -> List[dict]:
    """Scan every workspace member's src/ for a top-level definition of `name`.

    `want_kinds` is either the string "any" or a set of allowed kind strings.
    """
    matches: List[dict] = []
    for sys_ in systems_doc.get("systems", []):
        manifest_rel = sys_.get("manifest_path")
        if not manifest_rel:
            continue
        manifest = (project_root / manifest_rel).resolve()
        if not manifest.is_file():
            continue
        crate_root = manifest.parent

        for path in sorted(crate_root.rglob("*.rs") if (crate_root / "src").is_dir() else []):
            # Only under src/, skip tests/examples/benches.
            rel_parts = path.relative_to(crate_root).parts
            if not rel_parts or rel_parts[0] != "src":
                continue
            if any(p in ("tests", "examples", "benches", "target") for p in rel_parts[1:]):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = path.read_text(encoding="utf-8", errors="replace")
            cleaned = strip_rust_source(text)
            depths = _line_depths(cleaned)
            cleaned_lines = cleaned.splitlines()
            orig_lines = text.splitlines()

            for i, cleaned_line in enumerate(cleaned_lines, start=1):
                if i - 1 >= len(depths) or depths[i - 1] != 0:
                    continue
                stripped = cleaned_line.lstrip()
                if not stripped:
                    continue
                m = DEFN_RE.match(stripped)
                if not m:
                    continue
                kind, ident = m.group(1), m.group(2)
                if ident != name:
                    continue
                if want_kinds != "any" and kind not in want_kinds:
                    continue
                signature = orig_lines[i - 1].strip() if i - 1 < len(orig_lines) else stripped
                rel_file = PurePath(str(path.relative_to(project_root))).as_posix()
                matches.append({
                    "system": sys_["name"],
                    "kind": kind,
                    "file": rel_file,
                    "line": i,
                    "signature": signature,
                })
    return matches

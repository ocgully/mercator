"""Unity Layer 4 — assets + localisation strings.

**Assets**: walk `Assets/` and `Packages/` and classify by extension. Skip
`.meta` sidecar files (Unity-internal). Attribute each asset to the
assembly whose `.asmdef` is the deepest ancestor of the file — same scope
logic used in Layer 1 (`unity.py`) so that `assets.json` and `systems.json`
agree on ownership.

**Strings**: parse localisation files that are canonical formats:
  - `.po` — gettext PO files (`msgid` / `msgstr` pairs, one-line subset)
  - `.csv` — common Unity localisation export (`Key,en,fr,...`)
  - `.json` — ignored by default (too ambiguous; projects should use
    explicit CSV/PO exports if they want localisation enumerated)

`.cs` string literals are **not** scanned — false-positive rate is too
high. Projects that want in-code string enumeration can layer on a
custom scanner downstream.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path, PurePath
from typing import Dict, List, Optional, Tuple

from mercator import SCHEMA_VERSION
from mercator.stacks._asset_common import classify, safe_size
from mercator.stacks import unity as unity_stack


META_SUFFIX = ".meta"


def _scope_roots(project_root: Path) -> List[Tuple[str, Path]]:
    """Build the same asmdef scope map used by Layer 1."""
    roots: List[Tuple[str, Path]] = []
    for asmdef_path in unity_stack._find_asmdefs(project_root):
        data = unity_stack._read_asmdef(asmdef_path)
        if data is None:
            continue
        name = data.get("name") or asmdef_path.stem
        roots.append((name, asmdef_path.parent))
    return roots


def _owning_system(path: Path, scope_roots: List[Tuple[str, Path]]) -> Optional[str]:
    return unity_stack._scope_owner(path, scope_roots)


def build_assets(project_root: Path) -> dict:
    scope_roots = _scope_roots(project_root)
    assets: List[dict] = []
    seen: set = set()

    for base in ("Assets", "Packages"):
        d = project_root / base
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if not p.is_file():
                continue
            # Skip Unity .meta sidecars — they're not assets, they're
            # GUID/import-setting metadata paired 1:1 with real files.
            if p.suffix == META_SUFFIX:
                continue
            kind = classify(p)
            if kind is None:
                continue
            rel = PurePath(str(p.relative_to(project_root))).as_posix()
            if rel in seen:
                continue
            seen.add(rel)
            entry: dict = {
                "path": rel,
                "kind": kind,
                "size_bytes": safe_size(p),
            }
            owner = _owning_system(p, scope_roots)
            if owner:
                entry["owning_system"] = owner
            assets.append(entry)

    assets.sort(key=lambda a: a["path"])
    return {
        "schema_version": SCHEMA_VERSION,
        "layer": "assets",
        "stack": "unity",
        "source_tool": "unity_asset_walk",
        "source_tool_note": (
            "Walks Assets/ and Packages/, skipping .meta sidecars. "
            "owning_system is attributed via the deepest-ancestor .asmdef "
            "(same logic as Layer 1). Files under Assets/ with no covering "
            "asmdef have no owning_system set."
        ),
        "assets": assets,
    }


# ---------------------------------------------------------------------------
# Strings
# ---------------------------------------------------------------------------

PO_MSGID_RE = re.compile(r'^\s*msgid\s+"(.*)"\s*$')
PO_MSGSTR_RE = re.compile(r'^\s*msgstr\s+"(.*)"\s*$')


def _parse_po(path: Path, project_root: Path) -> List[dict]:
    """Minimal single-line msgid/msgstr pair parser — no plural forms."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    results: List[dict] = []
    rel = PurePath(str(path.relative_to(project_root))).as_posix()
    current_key: Optional[str] = None
    current_key_line: Optional[int] = None
    for i, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        m = PO_MSGID_RE.match(line)
        if m:
            current_key = m.group(1)
            current_key_line = i
            continue
        m = PO_MSGSTR_RE.match(line)
        if m and current_key is not None:
            translated = m.group(1)
            if current_key == "":
                current_key = None
                continue
            results.append({
                "key": current_key,
                "text": translated if translated else current_key,
                "file": rel,
                "line": current_key_line or i,
            })
            current_key = None
            current_key_line = None
    return results


def _parse_csv(path: Path, project_root: Path) -> List[dict]:
    """Unity CSV export: first column is Key, second column is the reference language."""
    try:
        text = path.read_text(encoding="utf-8-sig")  # handle BOM
    except (UnicodeDecodeError, OSError):
        return []
    results: List[dict] = []
    rel = PurePath(str(path.relative_to(project_root))).as_posix()
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return []
    # Heuristic: first column must look like a key header. Case-insensitive.
    if not header or header[0].strip().lower() not in ("key", "id", "name"):
        return []
    for lineno, row in enumerate(reader, start=2):
        if not row:
            continue
        key = row[0].strip()
        if not key:
            continue
        value = row[1].strip() if len(row) > 1 else ""
        results.append({
            "key": key,
            "text": value,
            "file": rel,
            "line": lineno,
        })
    return results


def build_strings(project_root: Path) -> dict:
    strings: List[dict] = []
    for base in ("Assets", "Packages"):
        d = project_root / base
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if not p.is_file():
                continue
            suf = p.suffix.lower()
            if suf == ".po":
                strings.extend(_parse_po(p, project_root))
            elif suf == ".csv" and "localiz" in p.stem.lower() + p.parent.name.lower():
                # Only treat CSVs as localisation if path hints at it.
                strings.extend(_parse_csv(p, project_root))
    strings.sort(key=lambda s: (s["file"], s["line"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "layer": "strings",
        "stack": "unity",
        "source_tool": "unity_po_csv_parse",
        "source_tool_note": (
            "Parses .po files under Assets/ and Packages/, plus .csv files "
            "whose path contains 'localiz' (e.g. Localization/en.csv). "
            ".cs string literals are intentionally skipped (high false-positive "
            "rate). Unity's binary LocalizationTables (.asset) are not parsed."
        ),
        "strings": strings,
    }

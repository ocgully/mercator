"""Dart/Flutter Layer 4 — assets from pubspec + strings from ARB.

**Assets**: parse the `flutter.assets:` and `flutter.fonts:` lists from each
`pubspec.yaml` in the repo (via the same minimal subset parser used by
Layer 1). Assets may reference either a file (`assets/logo.png`) or a
directory (`assets/images/`). Directories are expanded to their contents.

**Strings**: parse `.arb` files (ARB = Flutter's localisation format — it's
JSON with `@@locale` + `key: value` pairs and `@key: {...}` metadata).
Every non-`@`-prefixed string value is emitted as a user-facing string.
"""
from __future__ import annotations

import json
import re
from pathlib import Path, PurePath
from typing import Dict, List, Optional, Tuple

from mercator import SCHEMA_VERSION
from mercator.stacks._asset_common import classify, safe_size
from mercator.stacks import dart as dart_stack


SKIP_DIRS = dart_stack.SKIP_DIRS


def _parse_flutter_section(text: str) -> Tuple[List[str], List[str]]:
    """Extract the `assets:` list and font-file list under `flutter:` in a pubspec.

    Returns (asset_entries, font_file_entries). asset_entries are the raw
    strings as written (may be files or directories). font_file_entries
    are `asset:` values under any `fonts:` entry.

    Minimal YAML subset — good enough for ~all pubspec files. Nested maps
    beyond two levels aren't supported, which is fine for this schema.
    """
    asset_entries: List[str] = []
    font_files: List[str] = []

    in_flutter = False
    in_assets = False
    in_fonts = False
    flutter_indent = -1
    block_indent = -1

    for raw in text.splitlines():
        # Drop trailing comments (but not `#` inside quoted strings — unlikely here).
        line = re.sub(r"(^|\s)#.*$", "", raw).rstrip()
        if not line.strip():
            continue

        # Top-level key?
        m_top = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", line)
        if m_top and (line[0] != " " and line[0] != "\t"):
            key = m_top.group(1)
            in_flutter = (key == "flutter")
            in_assets = False
            in_fonts = False
            flutter_indent = -1
            continue

        if not in_flutter:
            continue

        indent = len(line) - len(line.lstrip())
        if flutter_indent < 0:
            flutter_indent = indent
        if indent < flutter_indent:
            # Left the flutter: block.
            in_flutter = False
            continue

        stripped = line.strip()

        # Sub-keys under flutter:
        if indent == flutter_indent:
            m_sub = re.match(r"^([A-Za-z_][A-Za-z0-9_\-]*)\s*:\s*(.*)$", stripped)
            if m_sub:
                subkey = m_sub.group(1)
                in_assets = (subkey == "assets")
                in_fonts = (subkey == "fonts")
                block_indent = -1
                continue

        # List items under assets: / fonts:
        if indent > flutter_indent and (in_assets or in_fonts):
            if stripped.startswith("- "):
                item = stripped[2:].strip()
                # `- asset: path/to/foo.ttf` — font entry sub-map starting.
                m_asset_key = re.match(r"^asset\s*:\s*(.+)$", item)
                if in_fonts and m_asset_key:
                    font_files.append(m_asset_key.group(1).strip().strip('"').strip("'"))
                elif in_assets:
                    asset_entries.append(item.strip('"').strip("'"))
            elif in_fonts:
                # Continuation under a fonts entry: `asset: path/to/foo.ttf`
                m_asset_key = re.match(r"^asset\s*:\s*(.+)$", stripped)
                if m_asset_key:
                    font_files.append(m_asset_key.group(1).strip().strip('"').strip("'"))

    return asset_entries, font_files


def _expand_asset_entry(entry: str, pubspec_dir: Path,
                        project_root: Path, owning_system: str) -> List[dict]:
    """Expand a pubspec asset entry into concrete asset records.

    Directory entries (trailing `/`) expand to all files one level deep
    (per Flutter's semantics). File entries map to themselves if present.
    Missing paths are still emitted (with `size_bytes: null`) so downstream
    tooling can flag broken references.
    """
    results: List[dict] = []
    target = (pubspec_dir / entry).resolve()

    def _emit(p: Path) -> None:
        try:
            rel = PurePath(str(p.relative_to(project_root))).as_posix()
        except ValueError:
            rel = PurePath(str(p)).as_posix()
        kind = classify(p) or "other"
        results.append({
            "path": rel,
            "kind": kind,
            "size_bytes": safe_size(p) if p.is_file() else None,
            "owning_system": owning_system,
        })

    if entry.endswith("/"):
        if target.is_dir():
            for child in sorted(target.iterdir()):
                if child.is_file():
                    _emit(child)
        else:
            # Directory declared but missing — record as a declared reference.
            try:
                rel = PurePath(str(target.relative_to(project_root))).as_posix()
            except ValueError:
                rel = entry
            results.append({
                "path": rel.rstrip("/") + "/",
                "kind": "directory",
                "size_bytes": None,
                "owning_system": owning_system,
                "missing": True,
            })
    else:
        if target.is_file():
            _emit(target)
        else:
            try:
                rel = PurePath(str(target.relative_to(project_root))).as_posix()
            except ValueError:
                rel = entry
            kind = classify(Path(entry)) or "other"
            results.append({
                "path": rel,
                "kind": kind,
                "size_bytes": None,
                "owning_system": owning_system,
                "missing": True,
            })
    return results


def build_assets(project_root: Path) -> dict:
    pubspecs = dart_stack._find_pubspecs(project_root)
    assets: List[dict] = []
    seen: set = set()
    for p in pubspecs:
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        parsed_meta = dart_stack._parse_pubspec(text)
        pkg_name = parsed_meta.get("name") or p.parent.name
        asset_entries, font_files = _parse_flutter_section(text)
        pubspec_dir = p.parent
        for entry in asset_entries:
            for rec in _expand_asset_entry(entry, pubspec_dir, project_root, pkg_name):
                if rec["path"] in seen:
                    continue
                seen.add(rec["path"])
                assets.append(rec)
        for font in font_files:
            for rec in _expand_asset_entry(font, pubspec_dir, project_root, pkg_name):
                if rec["path"] in seen:
                    continue
                seen.add(rec["path"])
                # Force kind=font if the extension was unknown.
                if rec["kind"] == "other":
                    rec["kind"] = "font"
                assets.append(rec)

    assets.sort(key=lambda a: a["path"])
    return {
        "schema_version": SCHEMA_VERSION,
        "layer": "assets",
        "stack": "dart",
        "source_tool": "pubspec_flutter_assets",
        "source_tool_note": (
            "Reads flutter.assets and flutter.fonts lists from every "
            "pubspec.yaml. Directory entries expand to files one level deep "
            "(Flutter's semantics). Declared-but-missing paths are emitted "
            "with size_bytes=null and missing=true."
        ),
        "assets": assets,
    }


# ---------------------------------------------------------------------------
# Strings — ARB files
# ---------------------------------------------------------------------------

def _find_arbs(project_root: Path) -> List[Path]:
    out: List[Path] = []
    def walk(d: Path) -> None:
        try:
            for entry in d.iterdir():
                if entry.name in SKIP_DIRS:
                    continue
                if entry.is_dir():
                    walk(entry)
                elif entry.suffix.lower() == ".arb":
                    out.append(entry)
        except (PermissionError, OSError):
            pass
    walk(project_root)
    return sorted(out)


def _parse_arb(path: Path, project_root: Path) -> List[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []

    rel = PurePath(str(path.relative_to(project_root))).as_posix()
    # Best-effort line lookup: find the line containing `"key"`.
    lines = text.splitlines()

    def _line_for(key: str) -> Optional[int]:
        needle = f'"{key}"'
        for i, line in enumerate(lines, start=1):
            if needle in line:
                return i
        return None

    results: List[dict] = []
    for key, value in data.items():
        if not isinstance(key, str) or key.startswith("@"):
            continue  # metadata entries start with @, skip
        if not isinstance(value, str):
            continue
        results.append({
            "key": key,
            "text": value,
            "file": rel,
            "line": _line_for(key) or 0,
        })
    return results


def build_strings(project_root: Path) -> dict:
    strings: List[dict] = []
    for arb in _find_arbs(project_root):
        strings.extend(_parse_arb(arb, project_root))
    strings.sort(key=lambda s: (s["file"], s["line"], s["key"] or ""))
    return {
        "schema_version": SCHEMA_VERSION,
        "layer": "strings",
        "stack": "dart",
        "source_tool": "arb_parse",
        "source_tool_note": (
            "Parses every .arb file in the repo as JSON. Entries with keys "
            "starting with '@' are metadata (Flutter's ARB convention) and "
            "skipped. Line numbers are best-effort (first occurrence of the "
            "quoted key in the file)."
        ),
        "strings": strings,
    }

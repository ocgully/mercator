"""Render contracts/{system}.json → contracts/{system}.md (deterministic)."""
from __future__ import annotations

from typing import Dict, List


KIND_ORDER = ["trait", "struct", "enum", "fn", "type", "const", "static", "macro", "mod", "use"]
KIND_LABELS = {
    "fn": "Functions",
    "struct": "Structs",
    "enum": "Enums",
    "trait": "Traits",
    "type": "Type aliases",
    "const": "Constants",
    "static": "Statics",
    "use": "Re-exports (pub use)",
    "mod": "Public modules",
    "macro": "Macros",
}


def render(doc: dict) -> str:
    system = doc.get("system", "?")
    items = doc.get("items", [])
    counts = doc.get("counts", {})
    files_scanned = doc.get("files_scanned", 0)
    source_tool = doc.get("source_tool", "?")

    lines: List[str] = [
        f"# Contract surface — `{system}`",
        "",
        f"**Source tool**: `{source_tool}`",
        f"**Files scanned**: {files_scanned}",
        f"**Public items**: {len(items)}",
        "",
        "_Last-refresh timestamp is in `.mercator/meta.json`; this file is time-stable._",
        "",
    ]

    if counts:
        lines += ["## Counts by kind", ""]
        for kind in KIND_ORDER:
            if counts.get(kind):
                lines.append(f"- **{KIND_LABELS.get(kind, kind)}** — {counts[kind]}")
        for kind, n in counts.items():
            if kind not in KIND_ORDER:
                lines.append(f"- **{kind}** — {n}")
        lines.append("")

    by_kind: Dict[str, List[dict]] = {}
    for it in items:
        by_kind.setdefault(it["kind"], []).append(it)

    for kind in KIND_ORDER:
        group = by_kind.get(kind)
        if not group:
            continue
        lines += [f"## {KIND_LABELS.get(kind, kind)}", "",
                  "| Name | Signature | File:line |", "|------|-----------|-----------|"]
        for it in group:
            sig = it.get("signature", "").replace("|", "\\|")
            if len(sig) > 140:
                sig = sig[:137] + "..."
            lines.append(f"| `{it['name']}` | `{sig}` | `{it['file']}`:{it['line']} |")
        lines.append("")

    for kind, group in by_kind.items():
        if kind in KIND_ORDER:
            continue
        lines += [f"## {kind}", ""]
        for it in group:
            lines.append(f"- `{it['name']}` — `{it['file']}`:{it['line']}")
        lines.append("")

    note = doc.get("source_tool_note")
    if note:
        lines += ["## Source-tool note", "", f"> {note}", ""]

    lines += ["## How agents use this data", "",
              "Agents should query the CLI for a slice rather than reading this rendered view:",
              "",
              f"```",
              f"mercator query contract {system}          # this data as JSON",
              f"mercator query symbol <name>              # resolve symbol defs across workspace",
              f"```",
              ""]
    return "\n".join(lines) + "\n"

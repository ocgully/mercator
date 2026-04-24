"""Render `.mercator/graph.md` — a human-viewable visual of systems + boundaries.

Output uses mermaid.js — renders natively in GitHub, VS Code, Obsidian, most
markdown tools. Zero install, deterministic, diff-clean. Agents may also
consume this but the JSON query API is preferred; the .md is for humans.

Three mermaid diagrams:

1. **Dependency graph** — every workspace-internal dep edge.
2. **DMZ overlay** — same systems, forbidden edges drawn as dashed red lines.
3. **Violations** — paths that currently cross a boundary, drawn with warning
   emphasis.

Layers (if declared in boundaries.json) are rendered as mermaid subgraphs so
they show as visual groupings.
"""
from __future__ import annotations

import fnmatch
from typing import Dict, Iterable, List, Set, Tuple

from mercator import boundaries as boundaries_mod


MERMAID_NODE_LIMIT = 50


def _safe(name: str) -> str:
    """Mermaid-safe node id."""
    return name.replace("-", "_").replace(".", "_").replace("/", "_")


def _layer_of(system: str, layers: Dict[str, List[str]]) -> str:
    for layer_name, selectors in layers.items():
        for sel in selectors:
            if sel == system or fnmatch.fnmatchcase(system, sel):
                return layer_name
    return ""


def render(systems_doc: dict, boundaries_doc: dict) -> str:
    systems = systems_doc.get("systems", [])
    stack = systems_doc.get("stack", "?")
    members = {s["name"] for s in systems}
    layers: Dict[str, List[str]] = (boundaries_doc or {}).get("layers") or {}
    rules = (boundaries_doc or {}).get("boundaries") or []

    # Compute edges that exist today.
    edges: Set[Tuple[str, str]] = set()
    for s in systems:
        for d in s.get("dependencies", []):
            if d.get("name") in members:
                edges.add((s["name"], d["name"]))

    # Evaluate violations if boundaries present.
    violations = boundaries_mod.evaluate(systems_doc, boundaries_doc) if boundaries_doc else []
    violation_edges: Set[Tuple[str, str]] = set()
    for v in violations:
        path = v["path"]
        for a, b in zip(path, path[1:]):
            violation_edges.add((a, b))

    # Build forbidden-edge pair set (concretised from rules).
    forbidden_pairs: Set[Tuple[str, str]] = set()
    for rule in rules:
        from_set = boundaries_mod._resolve_selector(rule["from"], layers, members)
        not_to_set = boundaries_mod._resolve_selector(rule["not_to"], layers, members)
        for a in from_set:
            for b in not_to_set:
                if a != b:
                    forbidden_pairs.add((a, b))

    lines: List[str] = [
        "# Mercator — Visual View",
        "",
        f"**Stack**: {stack}",
        f"**Systems**: {len(systems)}",
        f"**Dep edges**: {len(edges)}",
        f"**DMZ rules**: {len(rules)}",
        f"**Violations**: {len(violations)}" + ("  **⚠**" if violations else ""),
        "",
        "_This file regenerates on every `mercator refresh` or `mercator render`. Do not edit by hand — edit `.mercator/boundaries.json` and rerun. Renders natively in GitHub, VS Code, Obsidian._",
        "",
    ]

    # ------------------------- 1. Dependency graph -------------------------
    lines += ["## 1. Dependency graph (what currently is)", ""]
    if len(systems) > MERMAID_NODE_LIMIT:
        lines += [
            f"_Graph suppressed ({len(systems)} > {MERMAID_NODE_LIMIT} systems — see `systems.json` directly)._",
            "",
        ]
    else:
        lines += _mermaid_dep_graph(systems, edges, layers, violation_edges)

    # ------------------------- 2. DMZ / boundaries -------------------------
    if rules:
        lines += ["## 2. DMZ rules (what must never be)", "",
                  "Red dashed edges are **forbidden** by `.mercator/boundaries.json`. Solid red edges (if any) are live violations.",
                  ""]
        if len(systems) > MERMAID_NODE_LIMIT:
            lines += [f"_Diagram suppressed ({len(systems)} systems > {MERMAID_NODE_LIMIT})._", ""]
        else:
            lines += _mermaid_boundary_graph(systems, edges, forbidden_pairs, violation_edges, layers)
    else:
        lines += ["## 2. DMZ rules", "",
                  "No `.mercator/boundaries.json` configured. Run `mercator boundaries init` to scaffold one.",
                  ""]

    # ------------------------- 3. Violations detail ------------------------
    if violations:
        lines += ["## 3. Current violations", "",
                  "| Severity | Rule | Path | Rationale |",
                  "|----------|------|------|-----------|"]
        for v in violations:
            arrow = " → ".join(f"`{p}`" for p in v["path"])
            lines.append(
                f"| {v['severity']} | {v['rule_name']} | {arrow} | {v.get('rationale', '').replace('|', '/')} |"
            )
        lines.append("")
    elif rules:
        lines += ["## 3. Current violations", "", "✅ None — all boundary rules pass.", ""]

    # ------------------------- Footer: how to edit -------------------------
    lines += [
        "## How to edit",
        "",
        "- **Add / edit DMZ rules**: open `.mercator/boundaries.json` (scaffold with `mercator boundaries init`).",
        "- **Re-render this file**: `mercator render` (also runs automatically on every `mercator refresh`).",
        "- **CI gate**: `mercator check` exits 1 if any `error`-severity rule is violated.",
        "",
    ]
    return "\n".join(lines) + "\n"


def _mermaid_dep_graph(
    systems: List[dict],
    edges: Set[Tuple[str, str]],
    layers: Dict[str, List[str]],
    violation_edges: Set[Tuple[str, str]],
) -> List[str]:
    out = ["```mermaid", "graph LR"]
    # Group nodes into layer subgraphs.
    members_by_layer: Dict[str, List[str]] = {}
    unassigned: List[str] = []
    for s in systems:
        lay = _layer_of(s["name"], layers)
        if lay:
            members_by_layer.setdefault(lay, []).append(s["name"])
        else:
            unassigned.append(s["name"])

    for layer_name, names in sorted(members_by_layer.items()):
        out.append(f"  subgraph {_safe(layer_name)}[{layer_name}]")
        for n in sorted(names):
            out.append(f"    {_safe(n)}[{n}]")
        out.append("  end")
    for n in sorted(unassigned):
        out.append(f"  {_safe(n)}[{n}]")

    for a, b in sorted(edges):
        if (a, b) in violation_edges:
            out.append(f"  {_safe(a)} ==>|VIOLATION| {_safe(b)}")
        else:
            out.append(f"  {_safe(a)} --> {_safe(b)}")
    # Style violation edges.
    if violation_edges:
        out.append("  linkStyle default stroke:#777")
    out += ["```", ""]
    return out


def _mermaid_boundary_graph(
    systems: List[dict],
    edges: Set[Tuple[str, str]],
    forbidden_pairs: Set[Tuple[str, str]],
    violation_edges: Set[Tuple[str, str]],
    layers: Dict[str, List[str]],
) -> List[str]:
    out = ["```mermaid", "graph LR"]
    members_by_layer: Dict[str, List[str]] = {}
    unassigned: List[str] = []
    for s in systems:
        lay = _layer_of(s["name"], layers)
        if lay:
            members_by_layer.setdefault(lay, []).append(s["name"])
        else:
            unassigned.append(s["name"])

    for layer_name, names in sorted(members_by_layer.items()):
        out.append(f"  subgraph {_safe(layer_name)}[{layer_name}]")
        for n in sorted(names):
            out.append(f"    {_safe(n)}[{n}]")
        out.append("  end")
    for n in sorted(unassigned):
        out.append(f"  {_safe(n)}[{n}]")

    # Current dep edges dimmed.
    for a, b in sorted(edges - violation_edges):
        out.append(f"  {_safe(a)} --- {_safe(b)}")
    # Forbidden edges — dashed. If also a violation, draw stronger.
    for a, b in sorted(forbidden_pairs):
        marker = "x==x" if (a, b) in violation_edges else "-.-x"
        label = "|VIOLATION|" if (a, b) in violation_edges else "|forbidden|"
        out.append(f"  {_safe(a)} {marker}{label} {_safe(b)}")
    out += ["```", ""]
    return out

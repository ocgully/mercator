"""Forbidden-edge boundaries — the inverse of a dep graph.

A project's `.mercator/boundaries.json` declares which systems MUST NOT
reach which other systems — DMZ rules, layer separations, hexagonal-
architecture guards, sim/view splits. The codemap evaluates these rules
against the current Layer 1 dep graph and reports any violations with
concrete paths.

Schema (`.mercator/boundaries.json`):

{
  "schema_version": "1",
  "layers": {
    "view": ["view_*", "ui_*"],
    "sim":  ["sim_*", "gameplay_*"],
    "platform": ["platform_*"]
  },
  "boundaries": [
    {
      "name": "View must not reach Simulation",
      "rationale": "Sim is headless/deterministic; View is presentation-only.",
      "severity": "error",
      "from": "view",
      "not_to": "sim",
      "transitive": true
    }
  ]
}

Each rule's `from` / `not_to` fields resolve to a set of concrete systems
by (in order):
  1. exact system name
  2. glob pattern (fnmatch)
  3. layer name (expanded via the `layers` map; layer entries may themselves
     be globs or exact names)

`transitive: true` (the default) reports any violation reachable through
intermediate systems. `transitive: false` only reports direct edges.

Severity tiers:
  info     — factual state, no action required; emitted in output
  warning  — worth reviewing; does not fail `mercator check`
  error    — fails `mercator check` (exit 1); CI-blocking

A file's absence is not an error — projects with no boundaries get an
empty rule set and pass `check` trivially.
"""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Load + validate the boundaries file
# ---------------------------------------------------------------------------

SEVERITIES = ("info", "warning", "error")


def load_path(path: Path) -> dict:
    """Load a specific boundaries.json file. Returns `{}` if absent.

    Raises ValueError on malformed content. This is the project-aware
    primitive — callers pass the per-project path. `load()` keeps the
    legacy semantics for callers that still talk in terms of project_root.
    """
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"boundaries.json is malformed: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError("boundaries.json must be a JSON object at the top level")
    layers = doc.get("layers") or {}
    boundaries = doc.get("boundaries") or []
    if not isinstance(layers, dict):
        raise ValueError("boundaries.json: `layers` must be an object")
    if not isinstance(boundaries, list):
        raise ValueError("boundaries.json: `boundaries` must be an array")
    for i, rule in enumerate(boundaries):
        if not isinstance(rule, dict):
            raise ValueError(f"boundaries.json: boundaries[{i}] must be an object")
        for required in ("name", "from", "not_to"):
            if required not in rule:
                raise ValueError(f"boundaries.json: boundaries[{i}] missing required field `{required}`")
        sev = rule.get("severity", "error")
        if sev not in SEVERITIES:
            raise ValueError(
                f"boundaries.json: boundaries[{i}] severity must be one of {SEVERITIES}, got {sev!r}"
            )
    return doc


def load(project_root: Path) -> dict:
    """Legacy convenience: load `.mercator/boundaries.json` at the repo root.

    Prefer `load_path(project_storage_dir / "boundaries.json")` for
    project-aware callers.
    """
    path = project_root / ".mercator" / "boundaries.json"
    if not path.is_file():
        legacy = project_root / ".codemap" / "boundaries.json"
        if legacy.is_file():
            path = legacy
        else:
            return {}
    return load_path(path)


# ---------------------------------------------------------------------------
# Resolve `from` / `not_to` selectors to concrete system sets
# ---------------------------------------------------------------------------

def _resolve_selector(selector: str, layers: Dict[str, List[str]], known: Set[str]) -> Set[str]:
    """Return concrete system names matched by `selector`.

    Order: exact name > layer-name > glob pattern.
    """
    if selector in known:
        return {selector}
    if selector in layers:
        expanded: Set[str] = set()
        for entry in layers[selector]:
            expanded |= _resolve_selector(entry, layers, known)
        return expanded
    # Fallback: fnmatch glob
    return {s for s in known if fnmatch.fnmatchcase(s, selector)}


# ---------------------------------------------------------------------------
# Reachability — BFS over the dep graph with path reporting
# ---------------------------------------------------------------------------

def _build_edges(systems_doc: dict) -> Tuple[Dict[str, List[str]], Set[str]]:
    """Return (adjacency, member-set). Only workspace-internal edges are kept."""
    members = {s["name"] for s in systems_doc.get("systems", [])}
    adj: Dict[str, List[str]] = {n: [] for n in members}
    for s in systems_doc.get("systems", []):
        for dep in s.get("dependencies", []):
            name = dep.get("name")
            if name in members:
                adj[s["name"]].append(name)
    return adj, members


def _first_path(adj: Dict[str, List[str]], src: str, dst: str) -> Optional[List[str]]:
    """Return the first (shortest-by-BFS) path from src → dst, or None."""
    if src == dst:
        return [src]
    visited = {src}
    queue: List[Tuple[str, List[str]]] = [(src, [src])]
    while queue:
        node, path = queue.pop(0)
        for nxt in adj.get(node, []):
            if nxt in visited:
                continue
            if nxt == dst:
                return path + [nxt]
            visited.add(nxt)
            queue.append((nxt, path + [nxt]))
    return None


def _direct_edge(adj: Dict[str, List[str]], src: str, dst: str) -> bool:
    return dst in adj.get(src, [])


# ---------------------------------------------------------------------------
# Evaluate rules → list of violations
# ---------------------------------------------------------------------------

def evaluate(systems_doc: dict, boundaries_doc: dict) -> List[dict]:
    """Return violations. Each is a typed dict (see module docstring for shape).

    An empty list means all rules pass.
    """
    if not boundaries_doc:
        return []

    layers = boundaries_doc.get("layers") or {}
    rules = boundaries_doc.get("boundaries") or []
    adj, members = _build_edges(systems_doc)

    violations: List[dict] = []
    for rule in rules:
        transitive = rule.get("transitive", True)
        severity = rule.get("severity", "error")
        from_set = _resolve_selector(rule["from"], layers, members)
        not_to_set = _resolve_selector(rule["not_to"], layers, members)

        for src in sorted(from_set):
            for dst in sorted(not_to_set):
                if src == dst:
                    continue
                path: Optional[List[str]] = None
                if transitive:
                    path = _first_path(adj, src, dst)
                else:
                    if _direct_edge(adj, src, dst):
                        path = [src, dst]
                if not path:
                    continue
                violations.append({
                    "rule_name": rule["name"],
                    "severity": severity,
                    "rationale": rule.get("rationale", ""),
                    "from_system": src,
                    "to_system": dst,
                    "from_selector": rule["from"],
                    "not_to_selector": rule["not_to"],
                    "transitive": transitive,
                    "path": path,
                    "direct_edge": len(path) == 2,
                })

    # Deterministic order.
    violations.sort(key=lambda v: (v["rule_name"], v["from_system"], v["to_system"]))
    return violations


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------

def summarise_rules(systems_doc: dict, boundaries_doc: dict) -> List[dict]:
    """Return one entry per rule: {name, severity, resolved_from, resolved_not_to, status}.

    `status` is `"pass"` if no violation for that rule, else `"fail"` with a count.
    """
    if not boundaries_doc:
        return []
    layers = boundaries_doc.get("layers") or {}
    rules = boundaries_doc.get("boundaries") or []
    _adj, members = _build_edges(systems_doc)

    violations = evaluate(systems_doc, boundaries_doc)
    per_rule_fail_count: Dict[str, int] = {}
    for v in violations:
        per_rule_fail_count[v["rule_name"]] = per_rule_fail_count.get(v["rule_name"], 0) + 1

    out: List[dict] = []
    for rule in rules:
        name = rule["name"]
        from_set = sorted(_resolve_selector(rule["from"], layers, members))
        not_to_set = sorted(_resolve_selector(rule["not_to"], layers, members))
        fail_count = per_rule_fail_count.get(name, 0)
        out.append({
            "name": name,
            "severity": rule.get("severity", "error"),
            "rationale": rule.get("rationale", ""),
            "from_selector": rule["from"],
            "not_to_selector": rule["not_to"],
            "resolved_from": from_set,
            "resolved_not_to": not_to_set,
            "transitive": rule.get("transitive", True),
            "status": "pass" if fail_count == 0 else "fail",
            "violation_count": fail_count,
        })
    return out


def has_blocking_violations(violations: List[dict]) -> bool:
    """True if any violation's severity is `error`."""
    return any(v["severity"] == "error" for v in violations)


# ---------------------------------------------------------------------------
# Scaffold template for `mercator boundaries init`
# ---------------------------------------------------------------------------

SCAFFOLD_JSON = """{
  "schema_version": "1",

  "_doc": "Edit this file to declare forbidden system-to-system edges (DMZs). Run `mercator check` after editing to see violations. Delete this _doc field when done.",

  "layers": {
    "_doc": "Optional: group systems under layer names so rules read naturally. Values can be exact system names or glob patterns (fnmatch-style: `view_*`). Remove this _doc entry after editing.",

    "example_view": ["view_*", "ui_*"],
    "example_sim":  ["sim_*", "gameplay_*"]
  },

  "boundaries": [
    {
      "_doc": "Each rule says: systems matching `from` must not reach systems matching `not_to`. Selectors resolve in order: exact name > layer name > glob. `transitive: true` (default) checks reachability through any path; false checks only direct edges.",
      "name": "EXAMPLE — View must not reach Simulation",
      "rationale": "Simulation is headless/deterministic. View is presentation-only. Reversing this breaks server-authoritative replay.",
      "severity": "error",
      "from": "example_view",
      "not_to": "example_sim",
      "transitive": true
    }
  ]
}
"""


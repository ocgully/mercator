"""Repo-level (cross-project) DMZ rules.

Per-project boundaries (the ones declared under
`.mercator/projects/<id>/boundaries.json`) constrain edges *within* a
project. Repo-level boundaries — declared in
`.mercator/repo-boundaries.json` — constrain edges *between* projects.
They evaluate against `.mercator/repo-edges.json` (the implicit
cross-project edge graph).

Schema:

    {
      "schema_version": "1",
      "categories": {                 // optional aliases (see selectors below)
        "frontend": ["app"],
        "deep":     ["service", "infra"]
      },
      "boundaries": [
        {
          "name": "Apps must not consume infra directly",
          "rationale": "Service tier should mediate infra access.",
          "severity": "error",
          "from": "app",              // selector — see resolution rules
          "not_to": "infra",
          "transitive": true          // (default true) reach via intermediates
        }
      ]
    }

Selector resolution against the project list, in order:
  1. exact project id            (e.g. "apps-web")
  2. category alias (this file)  (e.g. "frontend" → ["app"])
  3. detected category           (e.g. "app", "service", "lib", "tool", "docs", "infra")
  4. tag                         (any project whose `tags` contains the value)
  5. glob over project id        (e.g. "apps-*")

A rule fires when a project in `from` reaches a project in `not_to` via
the edge graph (transitive default). The graph is the union of:
  - `repo-edges.json` edges (implicit, derived from manifest matching)
  - any explicit edges encoded in projects.json (none today, but the
    evaluator is forward-compatible).

Severity tiers mirror per-project boundaries: info / warning / error.
`mercator check` aggregates per-project + repo-level violations and
exits 1 on any error-severity hit.
"""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from mercator import SCHEMA_VERSION


SEVERITIES = ("info", "warning", "error")


# ---------------------------------------------------------------------------
# Load + validate
# ---------------------------------------------------------------------------

def load(repo_storage: Path) -> dict:
    """Load `.mercator/repo-boundaries.json`. Returns `{}` if absent.

    Raises ValueError on malformed content.
    """
    path = repo_storage / "repo-boundaries.json"
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"repo-boundaries.json is malformed: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError("repo-boundaries.json must be a JSON object at the top level")
    cats = doc.get("categories") or {}
    rules = doc.get("boundaries") or []
    if not isinstance(cats, dict):
        raise ValueError("repo-boundaries.json: `categories` must be an object")
    if not isinstance(rules, list):
        raise ValueError("repo-boundaries.json: `boundaries` must be an array")
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError(f"repo-boundaries.json: boundaries[{i}] must be an object")
        for required in ("name", "from", "not_to"):
            if required not in rule:
                raise ValueError(f"repo-boundaries.json: boundaries[{i}] missing field `{required}`")
        sev = rule.get("severity", "error")
        if sev not in SEVERITIES:
            raise ValueError(
                f"repo-boundaries.json: boundaries[{i}] severity must be one of "
                f"{SEVERITIES}, got {sev!r}"
            )
    return doc


# ---------------------------------------------------------------------------
# Selector resolution
# ---------------------------------------------------------------------------

def _resolve_selector(
    selector: str,
    categories: Dict[str, List[str]],
    projects: List[dict],
) -> Set[str]:
    """Return the set of project ids matched by `selector`.

    Order: exact id > category alias > detected category > tag > id glob.
    """
    ids = {p["id"] for p in projects}

    # 1. Exact id.
    if selector in ids:
        return {selector}

    # 2. Category alias (in this file's `categories` map).
    if selector in categories:
        out: Set[str] = set()
        for entry in categories[selector]:
            out |= _resolve_selector(entry, categories, projects)
        return out

    # 3. Detected category (from projects.json).
    cat_match = {p["id"] for p in projects if p.get("category") == selector}
    if cat_match:
        return cat_match

    # 4. Tag.
    tag_match = {p["id"] for p in projects if selector in (p.get("tags") or [])}
    if tag_match:
        return tag_match

    # 5. Glob over id.
    return {pid for pid in ids if fnmatch.fnmatchcase(pid, selector)}


# ---------------------------------------------------------------------------
# Reachability over the cross-project edge graph
# ---------------------------------------------------------------------------

def _build_adj(edges: List[dict]) -> Dict[str, List[str]]:
    adj: Dict[str, List[str]] = {}
    for e in edges:
        a = e.get("from"); b = e.get("to")
        if a and b:
            adj.setdefault(a, []).append(b)
    return adj


def _first_path(adj: Dict[str, List[str]], src: str, dst: str) -> Optional[List[str]]:
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


def _direct(adj: Dict[str, List[str]], src: str, dst: str) -> bool:
    return dst in adj.get(src, [])


# ---------------------------------------------------------------------------
# Evaluate
# ---------------------------------------------------------------------------

def evaluate(
    projects_doc: dict,
    repo_edges_doc: dict,
    repo_boundaries_doc: dict,
) -> List[dict]:
    """Return cross-project violations.

    Each violation is a dict shaped like the per-project version, plus the
    `from_project` / `to_project` ids and the `path` of project ids.
    """
    if not repo_boundaries_doc:
        return []

    projects = (projects_doc or {}).get("projects") or []
    edges = (repo_edges_doc or {}).get("edges") or []
    cats = repo_boundaries_doc.get("categories") or {}
    rules = repo_boundaries_doc.get("boundaries") or []

    adj = _build_adj(edges)
    out: List[dict] = []

    for rule in rules:
        transitive = rule.get("transitive", True)
        severity = rule.get("severity", "error")
        from_set = _resolve_selector(rule["from"], cats, projects)
        not_to_set = _resolve_selector(rule["not_to"], cats, projects)

        for src in sorted(from_set):
            for dst in sorted(not_to_set):
                if src == dst:
                    continue
                path: Optional[List[str]] = None
                if transitive:
                    path = _first_path(adj, src, dst)
                else:
                    if _direct(adj, src, dst):
                        path = [src, dst]
                if not path:
                    continue
                out.append({
                    "rule_name": rule["name"],
                    "severity": severity,
                    "rationale": rule.get("rationale", ""),
                    "from_project": src,
                    "to_project": dst,
                    "from_selector": rule["from"],
                    "not_to_selector": rule["not_to"],
                    "transitive": transitive,
                    "path": path,
                    "direct_edge": len(path) == 2,
                    "scope": "repo",
                })

    out.sort(key=lambda v: (v["rule_name"], v["from_project"], v["to_project"]))
    return out


def summarise_rules(
    projects_doc: dict,
    repo_edges_doc: dict,
    repo_boundaries_doc: dict,
) -> List[dict]:
    if not repo_boundaries_doc:
        return []
    projects = (projects_doc or {}).get("projects") or []
    cats = repo_boundaries_doc.get("categories") or {}
    rules = repo_boundaries_doc.get("boundaries") or []
    violations = evaluate(projects_doc, repo_edges_doc, repo_boundaries_doc)
    fail_counts: Dict[str, int] = {}
    for v in violations:
        fail_counts[v["rule_name"]] = fail_counts.get(v["rule_name"], 0) + 1
    out: List[dict] = []
    for rule in rules:
        from_set = sorted(_resolve_selector(rule["from"], cats, projects))
        not_to_set = sorted(_resolve_selector(rule["not_to"], cats, projects))
        fc = fail_counts.get(rule["name"], 0)
        out.append({
            "name": rule["name"],
            "severity": rule.get("severity", "error"),
            "rationale": rule.get("rationale", ""),
            "from_selector": rule["from"],
            "not_to_selector": rule["not_to"],
            "resolved_from": from_set,
            "resolved_not_to": not_to_set,
            "transitive": rule.get("transitive", True),
            "status": "pass" if fc == 0 else "fail",
            "violation_count": fc,
        })
    return out


def has_blocking_violations(violations: List[dict]) -> bool:
    return any(v["severity"] == "error" for v in violations)


# ---------------------------------------------------------------------------
# Scaffold for `mercator boundaries init --repo`
# ---------------------------------------------------------------------------

SCAFFOLD_JSON = """{
  "schema_version": "1",

  "_doc": "Cross-project DMZ rules. Constrains edges BETWEEN projects in this monorepo. Per-project rules (within a single project's system graph) live under `.mercator/projects/<id>/boundaries.json` instead.",

  "categories": {
    "_doc": "Optional aliases that combine detected categories. Selectors resolve in this order: exact project id > category alias > detected category > tag > id glob.",

    "example_frontend": ["app"],
    "example_deep":     ["service", "infra"]
  },

  "boundaries": [
    {
      "_doc": "A rule says: projects matching `from` must not reach (transitively, by default) projects matching `not_to`.",
      "name": "EXAMPLE — Apps must not consume infra directly",
      "rationale": "Apps should go through services; services mediate infra access. Replacing this rule's _doc and selectors removes the example.",
      "severity": "error",
      "from": "app",
      "not_to": "infra",
      "transitive": true
    }
  ]
}
"""

"""Structural diff between two git refs.

Given two refs, read each ref's `.mercator/systems.json` + per-system
`.mercator/contracts/*.json` via `git show <ref>:<path>` and emit a small,
typed delta describing:

- Systems added / removed (by name).
- Dependency edges added / removed (workspace-internal only — external deps
  aren't workspace systems and would be noise).
- Per-system public-surface additions / removals from Layer-2 contracts.

Designed to work on any commit that has `.mercator/` (or the legacy
`.codemap/`) committed. If a ref has no systems.json at either path, that
side is treated as empty and the diff still runs — useful for "what did
we gain when we introduced the codemap?".

No external deps. Uses only subprocess + json + stdlib.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple


# Preferred path; legacy `.codemap/` is consulted if the preferred path is
# absent at a given ref (for diffs that straddle the rename).
SYSTEMS_PATH = ".mercator/systems.json"
CONTRACT_DIR = ".mercator/contracts"
LEGACY_SYSTEMS_PATH = ".codemap/systems.json"
LEGACY_CONTRACT_DIR = ".codemap/contracts"


# ---------------------------------------------------------------------------
# git helpers
# ---------------------------------------------------------------------------

def _git(project_root: Path, *args: str) -> Tuple[int, str, str]:
    """Run `git` with cwd=project_root. Returns (returncode, stdout, stderr)."""
    proc = subprocess.run(
        ["git", *args],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout, proc.stderr


def _resolve_ref(project_root: Path, ref: str) -> str:
    """Resolve a ref to a short SHA, for display. Falls back to the ref string."""
    rc, out, _ = _git(project_root, "rev-parse", "--short", ref)
    if rc == 0 and out.strip():
        return out.strip()
    return ref


def _show(project_root: Path, ref: str, path: str) -> Optional[str]:
    """Return file contents at ref, or None if missing at that ref."""
    rc, out, _ = _git(project_root, "show", f"{ref}:{path}")
    if rc != 0:
        return None
    return out


def _ls_tree(project_root: Path, ref: str, path: str) -> List[str]:
    """List files in a directory at a ref. Returns [] if path missing."""
    rc, out, _ = _git(project_root, "ls-tree", "--name-only", f"{ref}:{path}")
    if rc != 0:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# state loading
# ---------------------------------------------------------------------------

def _load_systems_at_ref(project_root: Path, ref: str) -> dict:
    raw = _show(project_root, ref, SYSTEMS_PATH)
    if raw is None:
        # Fall back to legacy path for refs predating the rename.
        raw = _show(project_root, ref, LEGACY_SYSTEMS_PATH)
    if raw is None:
        return {"systems": []}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"systems": []}


def _load_contract_at_ref(project_root: Path, ref: str, system: str) -> Optional[dict]:
    raw = _show(project_root, ref, f"{CONTRACT_DIR}/{system}.json")
    if raw is None:
        raw = _show(project_root, ref, f"{LEGACY_CONTRACT_DIR}/{system}.json")
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _system_names(doc: dict) -> Set[str]:
    return {s["name"] for s in doc.get("systems", []) if "name" in s}


def _internal_edges(doc: dict) -> Set[Tuple[str, str, str]]:
    """Return the set of (from, to, kind) edges where both ends are workspace systems.

    `kind` is the cargo dep kind as stored in systems.json. None is normalised
    to "normal" so edges compare as strings cleanly.
    """
    names = _system_names(doc)
    edges: Set[Tuple[str, str, str]] = set()
    for sys in doc.get("systems", []):
        src = sys.get("name")
        if not src:
            continue
        for dep in sys.get("dependencies", []) or []:
            dst = dep.get("name")
            if dst not in names:
                continue  # external dep — out of scope
            kind = dep.get("kind") or "normal"
            edges.add((src, dst, kind))
    return edges


def _contract_item_keys(doc: Optional[dict]) -> Set[Tuple[str, str, str]]:
    """Return a set of (kind, name, signature) identity tuples for contract items.

    Signature is included so that a type-change on the same-named item reads
    as both a remove and an add — which is what an agent consuming the diff
    actually wants to see.
    """
    if not doc:
        return set()
    out: Set[Tuple[str, str, str]] = set()
    for item in doc.get("items", []) or []:
        name = item.get("name", "")
        kind = item.get("kind", "")
        sig = item.get("signature", "")
        out.add((kind, name, sig))
    return out


def _item_tuple_to_dict(t: Tuple[str, str, str]) -> dict:
    kind, name, sig = t
    return {"kind": kind, "name": name, "signature": sig}


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def compute_diff(project_root: Path, ref_a: str, ref_b: str) -> dict:
    """Return a structural delta from ref_a → ref_b. See module docstring for schema."""
    sha_a = _resolve_ref(project_root, ref_a)
    sha_b = _resolve_ref(project_root, ref_b)

    sys_a = _load_systems_at_ref(project_root, ref_a)
    sys_b = _load_systems_at_ref(project_root, ref_b)

    names_a = _system_names(sys_a)
    names_b = _system_names(sys_b)
    added_systems = sorted(names_b - names_a)
    removed_systems = sorted(names_a - names_b)

    edges_a = _internal_edges(sys_a)
    edges_b = _internal_edges(sys_b)
    added_edges = sorted(edges_b - edges_a)
    removed_edges = sorted(edges_a - edges_b)

    # Contract diff: for every system that exists on BOTH sides, compare items.
    # Systems that were added/removed are already covered by the systems diff;
    # listing all their items again would be noise.
    common = sorted(names_a & names_b)
    contracts: List[dict] = []
    for sysname in common:
        ca = _load_contract_at_ref(project_root, ref_a, sysname)
        cb = _load_contract_at_ref(project_root, ref_b, sysname)
        keys_a = _contract_item_keys(ca)
        keys_b = _contract_item_keys(cb)
        added = sorted(keys_b - keys_a)
        removed = sorted(keys_a - keys_b)
        if not added and not removed:
            continue
        contracts.append({
            "system": sysname,
            "added_items": [_item_tuple_to_dict(t) for t in added],
            "removed_items": [_item_tuple_to_dict(t) for t in removed],
        })

    return {
        "query": "diff",
        "refs": {"from": sha_a, "to": sha_b},
        "systems": {"added": added_systems, "removed": removed_systems},
        "edges": {
            "added": [{"from": a, "to": b, "kind": k} for (a, b, k) in added_edges],
            "removed": [{"from": a, "to": b, "kind": k} for (a, b, k) in removed_edges],
        },
        "contracts": contracts,
    }


# ---------------------------------------------------------------------------
# markdown rendering
# ---------------------------------------------------------------------------

def render_diff_md(diff: dict) -> str:
    """Human-readable markdown summary of a diff dict produced by compute_diff."""
    refs = diff.get("refs", {})
    lines: List[str] = []
    lines.append(f"# mercator diff {refs.get('from', '?')} .. {refs.get('to', '?')}")
    lines.append("")

    sys_added = diff.get("systems", {}).get("added", [])
    sys_removed = diff.get("systems", {}).get("removed", [])
    edges_added = diff.get("edges", {}).get("added", [])
    edges_removed = diff.get("edges", {}).get("removed", [])
    contracts = diff.get("contracts", [])

    if not any([sys_added, sys_removed, edges_added, edges_removed, contracts]):
        lines.append("_No structural changes._")
        lines.append("")
        return "\n".join(lines)

    # Systems
    lines.append("## Systems")
    if not sys_added and not sys_removed:
        lines.append("_unchanged_")
    else:
        for name in sys_added:
            lines.append(f"- + `{name}`")
        for name in sys_removed:
            lines.append(f"- - `{name}`")
    lines.append("")

    # Edges
    lines.append("## Dependency edges (workspace-internal)")
    if not edges_added and not edges_removed:
        lines.append("_unchanged_")
    else:
        for e in edges_added:
            lines.append(f"- + `{e['from']} -> {e['to']}` ({e['kind']})")
        for e in edges_removed:
            lines.append(f"- - `{e['from']} -> {e['to']}` ({e['kind']})")
    lines.append("")

    # Contracts
    lines.append("## Contracts (public surface)")
    if not contracts:
        lines.append("_unchanged_")
    else:
        for c in contracts:
            sysname = c.get("system", "?")
            added = c.get("added_items", [])
            removed = c.get("removed_items", [])
            lines.append(f"### `{sysname}`  (+{len(added)} / -{len(removed)})")
            for it in added:
                lines.append(f"- + **{it.get('kind','')}** `{it.get('name','')}` — `{it.get('signature','')}`")
            for it in removed:
                lines.append(f"- - **{it.get('kind','')}** `{it.get('name','')}` — `{it.get('signature','')}`")
            lines.append("")
    return "\n".join(lines)

"""Structural diff between two git refs — project-aware.

Given two refs, read each ref's `.codeatlas/projects.json` (or the legacy
`.mercator/` / `.codemap/` equivalents) and per-project `systems.json` +
`contracts/*.json` via `git show <ref>:<path>` and emit a small, typed
delta describing:

- Projects added / removed (by id) at the repo level.
- Per-project: systems added/removed, dep edges added/removed,
  Layer-2 contract item additions/removals.

Designed to work on any commit that has `.codeatlas/`, `.mercator/`, or
`.codemap/` committed, including refs that predate the v0.5.0 nested
layout. Layout resolution per ref (first match wins):

    1. `.codeatlas/projects.json` exists  → nested layout, current name
    2. `.mercator/projects.json` exists   → nested layout, mid-life name
    3. `.codemap/projects.json` exists    → nested layout, original name
    4. `.codeatlas/systems.json` exists   → flat layout, current name
    5. `.mercator/systems.json` exists    → flat layout, mid-life name
    6. `.codemap/systems.json` exists     → flat layout, original name
    7. nothing                            → empty ref (treat as no projects)

A diff that straddles the v0.4.x → v0.5.0 boundary will see one synthetic
"(legacy)" project on the older side and the real project list on the newer
side. Systems that existed on both sides get a true item-level contract
diff; systems only on one side are reported as system-level adds/removes.

No external deps. Uses only subprocess + json + stdlib.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple


# Storage-dir names in priority order: current, mid-life legacy, original
# legacy. Each is tried in turn when locating a ref's structural data.
STORAGE_DIRS = (".codeatlas", ".mercator", ".codemap")

# Back-compat constants — keep PROJECTS_PATH / PROJECT_*_TPL pointing at
# `.mercator/...` for now so any external callers / tests that import them
# still resolve. Internally we iterate STORAGE_DIRS.
PROJECTS_PATH = ".mercator/projects.json"
PROJECT_SYSTEMS_TPL = ".mercator/projects/{id}/systems.json"
PROJECT_CONTRACT_TPL = ".mercator/projects/{id}/contracts/{system}.json"

# Legacy flat-layout paths (v0.4.x and earlier).
LEGACY_SYSTEMS_PATHS = tuple(f"{d}/systems.json" for d in STORAGE_DIRS)
LEGACY_CONTRACT_DIRS = tuple(f"{d}/contracts" for d in STORAGE_DIRS)

# Sentinel project id used when a ref is on the legacy flat layout.
LEGACY_PROJECT_ID = "(legacy)"


# ---------------------------------------------------------------------------
# git helpers
# ---------------------------------------------------------------------------

def _git(project_root: Path, *args: str) -> Tuple[int, str, str]:
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
    rc, out, _ = _git(project_root, "rev-parse", "--short", ref)
    if rc == 0 and out.strip():
        return out.strip()
    return ref


def _show(project_root: Path, ref: str, path: str) -> Optional[str]:
    rc, out, _ = _git(project_root, "show", f"{ref}:{path}")
    if rc != 0:
        return None
    return out


# ---------------------------------------------------------------------------
# Per-ref state loading: returns a dict {project_id: {systems_doc, contracts}}
# ---------------------------------------------------------------------------

def _load_ref_state(project_root: Path, ref: str) -> dict:
    """Return the structural state at `ref` as a dict keyed by project id.

        { "<project_id>": { "systems": <systems_doc>, "contracts": {<sys>: <doc>} } }

    Empty dict if the ref has no codeatlas data at all.
    """
    # 1. Try the nested (v0.5+) layout under each known storage-dir name.
    for storage in STORAGE_DIRS:
        raw = _show(project_root, ref, f"{storage}/projects.json")
        if raw is None:
            continue
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        out: dict = {}
        for proj in doc.get("projects") or []:
            pid = proj.get("id")
            if not pid:
                continue
            out[pid] = _load_project_at_ref(project_root, ref, pid, storage=storage)
        return out

    # 2. Fall back to legacy flat layout — surface as one synthetic project.
    for storage in STORAGE_DIRS:
        sys_path = f"{storage}/systems.json"
        raw = _show(project_root, ref, sys_path)
        if raw is None:
            continue
        try:
            sys_doc = json.loads(raw)
        except json.JSONDecodeError:
            sys_doc = {"systems": []}
        contract_dir = f"{storage}/contracts"
        return {LEGACY_PROJECT_ID: {
            "systems": sys_doc,
            "contracts": _load_legacy_contracts(project_root, ref, contract_dir, sys_doc),
        }}

    return {}


def _load_project_at_ref(project_root: Path, ref: str, pid: str, *,
                         storage: str = ".codeatlas") -> dict:
    sys_path = f"{storage}/projects/{pid}/systems.json"
    raw = _show(project_root, ref, sys_path)
    if raw is None:
        return {"systems": {"systems": []}, "contracts": {}}
    try:
        sys_doc = json.loads(raw)
    except json.JSONDecodeError:
        sys_doc = {"systems": []}
    contracts: dict = {}
    for s in sys_doc.get("systems") or []:
        name = s.get("name")
        if not name:
            continue
        # System names with `/` (scoped npm packages, ts refs) are stored as
        # `__`-sanitised filenames — match the refresh writer.
        safe = name.replace("/", "__").replace("\\", "__")
        c_path = f"{storage}/projects/{pid}/contracts/{safe}.json"
        c_raw = _show(project_root, ref, c_path)
        if c_raw is None:
            continue
        try:
            contracts[name] = json.loads(c_raw)
        except json.JSONDecodeError:
            continue
    return {"systems": sys_doc, "contracts": contracts}


def _load_legacy_contracts(
    project_root: Path, ref: str, contract_dir: str, sys_doc: dict,
) -> dict:
    contracts: dict = {}
    for s in sys_doc.get("systems") or []:
        name = s.get("name")
        if not name:
            continue
        c_raw = _show(project_root, ref, f"{contract_dir}/{name}.json")
        if c_raw is None:
            continue
        try:
            contracts[name] = json.loads(c_raw)
        except json.JSONDecodeError:
            continue
    return contracts


# ---------------------------------------------------------------------------
# Diff primitives
# ---------------------------------------------------------------------------

def _system_names(sys_doc: dict) -> Set[str]:
    return {s["name"] for s in sys_doc.get("systems", []) if "name" in s}


def _internal_edges(sys_doc: dict) -> Set[Tuple[str, str, str]]:
    """Return (from, to, kind) edges where both ends are workspace systems."""
    names = _system_names(sys_doc)
    edges: Set[Tuple[str, str, str]] = set()
    for sys in sys_doc.get("systems", []):
        src = sys.get("name")
        if not src:
            continue
        for dep in sys.get("dependencies", []) or []:
            dst = dep.get("name")
            if dst not in names:
                continue
            kind = dep.get("kind") or "normal"
            edges.add((src, dst, kind))
    return edges


def _contract_item_keys(doc: Optional[dict]) -> Set[Tuple[str, str, str]]:
    if not doc:
        return set()
    out: Set[Tuple[str, str, str]] = set()
    for item in doc.get("items", []) or []:
        out.add((item.get("kind", ""), item.get("name", ""), item.get("signature", "")))
    return out


def _item_tuple_to_dict(t: Tuple[str, str, str]) -> dict:
    kind, name, sig = t
    return {"kind": kind, "name": name, "signature": sig}


def _project_diff(state_a: dict, state_b: dict) -> dict:
    """Compute the per-project structural delta. Inputs are the per-project
    payloads from `_load_ref_state(...)`."""
    sys_a = state_a.get("systems") or {"systems": []}
    sys_b = state_b.get("systems") or {"systems": []}
    contracts_a = state_a.get("contracts") or {}
    contracts_b = state_b.get("contracts") or {}

    names_a = _system_names(sys_a)
    names_b = _system_names(sys_b)
    added_systems = sorted(names_b - names_a)
    removed_systems = sorted(names_a - names_b)

    edges_a = _internal_edges(sys_a)
    edges_b = _internal_edges(sys_b)
    added_edges = sorted(edges_b - edges_a)
    removed_edges = sorted(edges_a - edges_b)

    # Per-system contract diff for systems present on both sides.
    common = sorted(names_a & names_b)
    contracts: List[dict] = []
    for sysname in common:
        keys_a = _contract_item_keys(contracts_a.get(sysname))
        keys_b = _contract_item_keys(contracts_b.get(sysname))
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
        "systems": {"added": added_systems, "removed": removed_systems},
        "edges": {
            "added": [{"from": a, "to": b, "kind": k} for (a, b, k) in added_edges],
            "removed": [{"from": a, "to": b, "kind": k} for (a, b, k) in removed_edges],
        },
        "contracts": contracts,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_diff(project_root: Path, ref_a: str, ref_b: str) -> dict:
    """Return a structural delta from ref_a → ref_b.

    Output schema:
        {
          "query": "diff",
          "refs": {"from": <sha>, "to": <sha>},
          "projects": {"added": [...], "removed": [...]},
          "per_project": [
            { "id": "...", "systems": {...}, "edges": {...}, "contracts": [...] },
            ...
          ]
        }
    """
    sha_a = _resolve_ref(project_root, ref_a)
    sha_b = _resolve_ref(project_root, ref_b)

    state_a = _load_ref_state(project_root, ref_a)
    state_b = _load_ref_state(project_root, ref_b)

    ids_a = set(state_a.keys())
    ids_b = set(state_b.keys())
    added_projects = sorted(ids_b - ids_a)
    removed_projects = sorted(ids_a - ids_b)
    common_projects = sorted(ids_a & ids_b)

    per_project: List[dict] = []
    for pid in common_projects:
        delta = _project_diff(state_a[pid], state_b[pid])
        # Suppress "no change" entries to keep output small — agents only care
        # about projects that actually moved.
        if (not delta["systems"]["added"] and not delta["systems"]["removed"]
                and not delta["edges"]["added"] and not delta["edges"]["removed"]
                and not delta["contracts"]):
            continue
        per_project.append({"id": pid, **delta})

    # Also emit one entry per added/removed project so the caller has a
    # complete snapshot of what came/went (including their initial systems).
    for pid in added_projects:
        sys_doc = (state_b.get(pid, {}).get("systems") or {"systems": []})
        per_project.append({
            "id": pid, "status": "added",
            "systems": {"added": sorted(_system_names(sys_doc)), "removed": []},
            "edges": {
                "added": [{"from": a, "to": b, "kind": k}
                          for (a, b, k) in sorted(_internal_edges(sys_doc))],
                "removed": [],
            },
            "contracts": [],
        })
    for pid in removed_projects:
        sys_doc = (state_a.get(pid, {}).get("systems") or {"systems": []})
        per_project.append({
            "id": pid, "status": "removed",
            "systems": {"added": [], "removed": sorted(_system_names(sys_doc))},
            "edges": {
                "added": [],
                "removed": [{"from": a, "to": b, "kind": k}
                            for (a, b, k) in sorted(_internal_edges(sys_doc))],
            },
            "contracts": [],
        })

    return {
        "query": "diff",
        "refs": {"from": sha_a, "to": sha_b},
        "projects": {"added": added_projects, "removed": removed_projects},
        "per_project": per_project,
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def render_diff_md(diff: dict) -> str:
    refs = diff.get("refs", {})
    lines: List[str] = []
    lines.append(f"# codeatlas diff {refs.get('from', '?')} .. {refs.get('to', '?')}")
    lines.append("")

    proj_added = diff.get("projects", {}).get("added", [])
    proj_removed = diff.get("projects", {}).get("removed", [])
    per_project = diff.get("per_project", [])

    if not any([proj_added, proj_removed, per_project]):
        lines.append("_No structural changes._")
        lines.append("")
        return "\n".join(lines)

    if proj_added or proj_removed:
        lines.append("## Projects")
        for pid in proj_added:
            lines.append(f"- + `{pid}`")
        for pid in proj_removed:
            lines.append(f"- - `{pid}`")
        lines.append("")

    for entry in per_project:
        pid = entry.get("id", "?")
        status = entry.get("status")
        header = f"## Project `{pid}`"
        if status:
            header += f"  ({status})"
        lines.append(header)

        sys_added = entry.get("systems", {}).get("added", [])
        sys_removed = entry.get("systems", {}).get("removed", [])
        edges_added = entry.get("edges", {}).get("added", [])
        edges_removed = entry.get("edges", {}).get("removed", [])
        contracts = entry.get("contracts", [])

        lines.append("")
        lines.append("### Systems")
        if not sys_added and not sys_removed:
            lines.append("_unchanged_")
        else:
            for name in sys_added:
                lines.append(f"- + `{name}`")
            for name in sys_removed:
                lines.append(f"- - `{name}`")
        lines.append("")

        lines.append("### Dependency edges (workspace-internal)")
        if not edges_added and not edges_removed:
            lines.append("_unchanged_")
        else:
            for e in edges_added:
                lines.append(f"- + `{e['from']} -> {e['to']}` ({e['kind']})")
            for e in edges_removed:
                lines.append(f"- - `{e['from']} -> {e['to']}` ({e['kind']})")
        lines.append("")

        if contracts:
            lines.append("### Contracts (public surface)")
            for c in contracts:
                sysname = c.get("system", "?")
                added = c.get("added_items", [])
                removed = c.get("removed_items", [])
                lines.append(f"#### `{sysname}`  (+{len(added)} / -{len(removed)})")
                for it in added:
                    lines.append(f"- + **{it.get('kind','')}** `{it.get('name','')}` — `{it.get('signature','')}`")
                for it in removed:
                    lines.append(f"- - **{it.get('kind','')}** `{it.get('name','')}` — `{it.get('signature','')}`")
                lines.append("")
        lines.append("")

    return "\n".join(lines)

"""Implicit cross-project edge detection.

After every project's Layer 1 (`systems.json`) lands, we look at each
project's *external* dependencies (deps it consumes that are NOT among its
own systems) and try to match them against other projects in the same repo.
A match means project A consumes project B at the build/package level — a
true monorepo internal edge.

Stack-aware matching:

    rust    — Cargo.toml [package].name + workspace member names. A crate
              dependency is internal iff it matches another rust project's
              package name OR its name appears in this project's path
              (workspace).
    ts      — `package.json` `name`. An npm dep is internal iff some other
              project's package.json declares that exact name.
    python  — `[project].name` from pyproject.toml. An import root (top
              segment of `external_imports`) is internal iff it matches.
    dart    — `pubspec.yaml` `name`.
    go      — module path last segment vs `go.mod` modules; coarse, but
              good enough as a heuristic.

Output: `.mercator/repo-edges.json`:

    {
      "schema_version": "1",
      "edges": [
        { "from": "apps-web", "to": "packages-shared", "via": "shared",
          "kind": "npm-dependency" },
        { "from": "services-api", "to": "packages-pyutils", "via": "pyutils",
          "kind": "python-import" }
      ]
    }
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from mercator import SCHEMA_VERSION, paths


# ---------------------------------------------------------------------------
# Per-stack: extract this project's published name AND its external dep names
# ---------------------------------------------------------------------------

def _project_names_rust(project_dir: Path) -> List[str]:
    """The set of crate names published by this project. A workspace can
    publish many — accept all top-level [package] sections plus workspace
    member crates' names.
    """
    out: Set[str] = set()
    root = project_dir / "Cargo.toml"
    if root.is_file():
        try:
            text = root.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""
        m = re.search(r'^\s*name\s*=\s*"([^"]+)"', text, re.MULTILINE)
        if m:
            out.add(m.group(1))
        # Workspace members.
        ws_match = re.search(
            r'^\s*members\s*=\s*\[([^\]]+)\]', text, re.MULTILINE | re.DOTALL,
        )
        if ws_match:
            for member in re.findall(r'"([^"]+)"', ws_match.group(1)):
                ct = (project_dir / member / "Cargo.toml")
                if ct.is_file():
                    try:
                        sub_text = ct.read_text(encoding="utf-8")
                        m2 = re.search(r'^\s*name\s*=\s*"([^"]+)"', sub_text, re.MULTILINE)
                        if m2:
                            out.add(m2.group(1))
                    except (OSError, UnicodeDecodeError):
                        pass
    return sorted(out)


def _project_names_ts(project_dir: Path) -> List[str]:
    out: Set[str] = set()
    pkg = project_dir / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("name"), str):
                out.add(data["name"])
        except (OSError, ValueError):
            pass
    # Workspace children (rare but possible — npm workspaces).
    for child_pkg in project_dir.glob("**/package.json"):
        if child_pkg == pkg:
            continue
        # Skip node_modules.
        if "node_modules" in child_pkg.parts:
            continue
        try:
            data = json.loads(child_pkg.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("name"), str):
                out.add(data["name"])
        except (OSError, ValueError):
            continue
    return sorted(out)


def _project_names_python(project_dir: Path) -> List[str]:
    out: Set[str] = set()
    py = project_dir / "pyproject.toml"
    if py.is_file():
        try:
            try:
                import tomllib
                data = tomllib.loads(py.read_text(encoding="utf-8"))
            except ImportError:
                import tomli as tomllib  # type: ignore[no-redef,import-not-found]
                data = tomllib.loads(py.read_text(encoding="utf-8"))
            project_name = ((data.get("project") or {}).get("name")
                            or (data.get("tool", {}).get("poetry") or {}).get("name"))
            if isinstance(project_name, str):
                out.add(project_name)
        except (OSError, ValueError, ImportError):
            pass
    # Heuristic: top-level packages (dirs with __init__.py at depth 1).
    for d in project_dir.iterdir() if project_dir.is_dir() else []:
        if d.is_dir() and (d / "__init__.py").is_file():
            out.add(d.name)
    return sorted(out)


def _project_names_dart(project_dir: Path) -> List[str]:
    out: Set[str] = set()
    pub = project_dir / "pubspec.yaml"
    if pub.is_file():
        try:
            text = pub.read_text(encoding="utf-8")
            m = re.search(r"^name:\s*([A-Za-z0-9_]+)", text, re.MULTILINE)
            if m:
                out.add(m.group(1))
        except (OSError, UnicodeDecodeError):
            pass
    return sorted(out)


_NAME_EXTRACTORS = {
    "rust":   _project_names_rust,
    "ts":     _project_names_ts,
    "python": _project_names_python,
    "dart":   _project_names_dart,
}


# ---------------------------------------------------------------------------
# Per-stack: extract this project's external-edge candidates (consumer side)
# ---------------------------------------------------------------------------

def _consumed_rust(systems_doc: dict) -> Set[str]:
    """Rust deps that aren't in this project's workspace are external — a
    candidate for cross-project resolution against another rust project.
    """
    members = {s["name"] for s in systems_doc.get("systems") or []}
    out: Set[str] = set()
    for s in systems_doc.get("systems") or []:
        for d in s.get("dependencies") or []:
            name = d.get("name")
            if name and name not in members:
                out.add(name)
    return out


def _consumed_ts(systems_doc: dict) -> Set[str]:
    """TS package deps that aren't this project's own packages."""
    own = {s["name"] for s in systems_doc.get("systems") or []}
    out: Set[str] = set()
    for s in systems_doc.get("systems") or []:
        for d in s.get("dependencies") or []:
            name = d.get("name")
            if name and name not in own:
                out.add(name)
    return out


def _consumed_python(systems_doc: dict) -> Set[str]:
    """Python: top-level imports per system that don't resolve to a known
    sub-package within this project. The Python stack records these as
    `external_imports` already.
    """
    own_top = {s["name"].split(".")[0] for s in systems_doc.get("systems") or []}
    out: Set[str] = set()
    for s in systems_doc.get("systems") or []:
        for ext in s.get("external_imports") or []:
            top = (ext or "").split(".")[0]
            if not top:
                continue
            if top in own_top:
                continue
            # Skip stdlib + builtin prefixes (rough — we keep all and let the
            # cross-project resolver match against actual project names).
            out.add(top)
    return out


def _consumed_dart(systems_doc: dict) -> Set[str]:
    own = {s["name"] for s in systems_doc.get("systems") or []}
    out: Set[str] = set()
    for s in systems_doc.get("systems") or []:
        for d in s.get("dependencies") or []:
            name = d.get("name")
            if name and name not in own:
                out.add(name)
    return out


_CONSUMERS = {
    "rust":   _consumed_rust,
    "ts":     _consumed_ts,
    "python": _consumed_python,
    "dart":   _consumed_dart,
}


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

def compute_edges(repo_root: Path) -> dict:
    """Compute repo-edges.json — implicit cross-project edges."""
    repo_storage = paths.mercator_dir(repo_root)
    from mercator import projects as projects_mod
    projects_doc = projects_mod.load_projects(repo_storage)
    if projects_doc is None:
        projects_doc = projects_mod.detect_projects(repo_root)
    projects: List[dict] = projects_doc.get("projects") or []

    # Build a name → project_id map. Names come from each project's manifest
    # (cargo / npm / pyproject / pubspec). One name maps to at most one
    # project; if there are conflicts we keep the first (deterministic order).
    name_to_project: Dict[str, str] = {}
    project_names: Dict[str, List[str]] = {}
    for proj in projects:
        extractor = _NAME_EXTRACTORS.get(proj["stack"])
        names: List[str] = []
        if extractor is not None:
            project_dir = (repo_root / proj["root"]).resolve()
            try:
                names = extractor(project_dir)
            except Exception:  # noqa: BLE001
                names = []
        # Always include the manifest_name and the project id itself as
        # fallback aliases.
        if proj.get("manifest_name"):
            names.append(proj["manifest_name"])
        names.append(proj["id"])
        names.append(proj["name"])
        project_names[proj["id"]] = sorted({n for n in names if n})
        for n in project_names[proj["id"]]:
            name_to_project.setdefault(n, proj["id"])

    edges: List[dict] = []
    for proj in projects:
        ps = paths.project_storage_dir(repo_storage, proj["id"])
        sys_path = ps / "systems.json"
        if not sys_path.is_file():
            continue
        try:
            sys_doc = json.loads(sys_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        consumer = _CONSUMERS.get(proj["stack"])
        if consumer is None:
            continue
        consumed = consumer(sys_doc)
        for via in sorted(consumed):
            target_id = name_to_project.get(via)
            if target_id and target_id != proj["id"]:
                edges.append({
                    "from": proj["id"],
                    "to": target_id,
                    "via": via,
                    "kind": _edge_kind(proj["stack"]),
                })

    # Deterministic order.
    edges.sort(key=lambda e: (e["from"], e["to"], e["via"]))

    return {
        "schema_version": SCHEMA_VERSION,
        "layer": "repo-edges",
        "project_count": len(projects),
        "edge_count": len(edges),
        "project_names": project_names,
        "edges": edges,
        "source_tool": "mercator_repo_edges",
        "source_tool_note": (
            "Implicit cross-project edges inferred by matching each project's "
            "external dependency names against other projects' published "
            "manifest names. Stack-specific resolvers per Cargo / npm / "
            "pyproject / pubspec."
        ),
    }


def _edge_kind(stack: str) -> str:
    return {
        "rust":   "cargo-dependency",
        "ts":     "npm-dependency",
        "python": "python-import",
        "dart":   "pub-dependency",
    }.get(stack, "dependency")


def write_edges(repo_root: Path) -> Path:
    repo_storage = paths.ensure_mercator_dir(repo_root)
    doc = compute_edges(repo_root)
    out = repo_storage / "repo-edges.json"
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def load_edges(repo_storage: Path) -> Optional[dict]:
    p = repo_storage / "repo-edges.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

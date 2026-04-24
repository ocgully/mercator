"""Render systems.json → systems.md (deterministic — no timestamps)."""
from __future__ import annotations

from typing import List


MERMAID_NODE_LIMIT = 20


def _safe_node_id(name: str) -> str:
    return name.replace("-", "_").replace(".", "_")


def render(doc: dict) -> str:
    stack = doc.get("stack", "?")
    systems = doc.get("systems", [])
    members = {s["name"] for s in systems}

    lines: List[str] = [
        "# Systems Map",
        "",
        f"**Stack**: {stack}",
        f"**Workspace members**: {len(systems)}",
        "",
        "_Last-refresh timestamp is in `.mercator/meta.json`; this file is time-stable._",
        "",
    ]

    # Table columns differ slightly by stack (Unity has platform flags; Rust
    # has version; Dart has version).
    if stack == "unity":
        lines += [
            "## Systems",
            "",
            "| System | Kind | Editor-only | .cs files | Scope | Deps (asmdef refs) |",
            "|--------|------|-------------|-----------|-------|--------------------|",
        ]
        for s in systems:
            kind = ",".join(s.get("kind", []))
            deps = ", ".join(d["name"] for d in s.get("dependencies", []))
            lines.append(
                f"| `{s['name']}` | {kind} | {'yes' if s.get('editor_only') else 'no'} "
                f"| {s.get('cs_file_count', 0)} | `{s.get('scope_dir', '?')}` | {deps} |"
            )
    elif stack == "ts":
        lines += [
            "## Systems",
            "",
            "| System | Version | Kind | Scope | Deps | Dev deps |",
            "|--------|---------|------|-------|------|----------|",
        ]
        for s in systems:
            kinds = ",".join(s.get("kind", []))
            deps = [d["name"] for d in s.get("dependencies", []) if d.get("kind") is None]
            devs = [d["name"] for d in s.get("dependencies", []) if d.get("kind") == "dev"]
            lines.append(
                f"| `{s['name']}` | {s.get('version') or '—'} | {kinds} "
                f"| `{s.get('scope_dir', '.')}` "
                f"| {', '.join(deps[:5])}{'…' if len(deps) > 5 else ''} "
                f"| {', '.join(devs[:5])}{'…' if len(devs) > 5 else ''} |"
            )
    elif stack == "dart":
        lines += [
            "## Systems",
            "",
            "| System | Version | Scope | Deps | Dev deps |",
            "|--------|---------|-------|------|----------|",
        ]
        for s in systems:
            deps = [d["name"] for d in s.get("dependencies", []) if d.get("kind") is None]
            devs = [d["name"] for d in s.get("dependencies", []) if d.get("kind") == "dev"]
            lines.append(
                f"| `{s['name']}` | {s.get('version') or '—'} | `{s.get('scope_dir', '.')}` "
                f"| {', '.join(deps[:5])}{'…' if len(deps) > 5 else ''} "
                f"| {', '.join(devs[:5])}{'…' if len(devs) > 5 else ''} |"
            )
    else:
        lines += [
            "## Systems",
            "",
            "| System | Version | Kind | Workspace deps |",
            "|--------|---------|------|----------------|",
        ]
        for s in systems:
            kinds = ",".join(s.get("kind", []))
            workspace_deps = sorted(
                {d["name"] for d in s.get("dependencies", []) if d["name"] in members}
            )
            lines.append(
                f"| `{s['name']}` | {s.get('version', '?')} | {kinds} | {', '.join(workspace_deps)} |"
            )

    lines.append("")

    # Dependency graph (Rust and Unity both have internal edges).
    if stack in ("rust", "unity") and len(systems) <= MERMAID_NODE_LIMIT:
        lines += ["## Dependency Graph", "", "```mermaid", "graph LR"]
        edges = set()
        for s in systems:
            src = _safe_node_id(s["name"])
            for dep in s.get("dependencies", []):
                if dep["name"] in members:
                    edges.add((src, _safe_node_id(dep["name"])))
        for src, dst in sorted(edges):
            lines.append(f"  {src} --> {dst}")
        lines += ["```", ""]
    elif stack in ("rust", "unity"):
        lines += [
            f"_Dependency graph suppressed ({len(systems)} > {MERMAID_NODE_LIMIT} members — see systems.json)._",
            "",
        ]

    lines += ["## How agents use this data", "",
              "Agents should query the CLI rather than reading this file directly:",
              "",
              "```",
              "mercator query systems                  # this view as JSON",
              "mercator query deps <system>            # dependents + dependencies",
              "mercator query touches <file-path>      # which system owns this path",
              "mercator query system <name>            # Layer 1 + 2 slice for one system",
              "```",
              ""]
    return "\n".join(lines) + "\n"

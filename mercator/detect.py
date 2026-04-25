"""Stack detection.

Detection is explicit and file-based — no heuristics beyond "is this
marker present?". When a project has multiple stacks (e.g. Rust backend +
TypeScript frontend in a monorepo), detection returns the *primary* stack
for the root; sub-stack handling is deferred to per-stack code.

Precedence (highest first):
    rust        — Cargo.toml
    unity       — Assets/ + ProjectSettings/ + Packages/manifest.json
    dart        — pubspec.yaml
    ts          — package.json
    python      — pyproject.toml or setup.py
    go          — go.mod or go.work
    unknown     — nothing matched

Unity takes precedence over `csharp`/`ts` because a Unity project can also
contain `.csproj` or `package.json` in subdirs — those aren't the primary
signal for the repo.

`.csproj` is *not* used for detection: Unity regenerates it from asmdefs
and it's typically gitignored, so it can't be trusted to reflect reality.
"""
from __future__ import annotations

from pathlib import Path


def detect(project_root: Path) -> str:
    if (project_root / "Cargo.toml").is_file():
        return "rust"
    if (
        (project_root / "Assets").is_dir()
        and (project_root / "ProjectSettings").is_dir()
        and (project_root / "Packages" / "manifest.json").is_file()
    ):
        return "unity"
    if (project_root / "pubspec.yaml").is_file():
        return "dart"
    if (project_root / "package.json").is_file():
        return "ts"
    if (project_root / "pyproject.toml").is_file() or (project_root / "setup.py").is_file():
        return "python"
    if (project_root / "go.mod").is_file() or (project_root / "go.work").is_file():
        return "go"
    return "unknown"


def layer_support(stack: str) -> dict:
    """Which layers are implemented for each stack, in this version."""
    supported = {
        "rust":   {"systems": "implemented", "contracts": "implemented", "symbols": "implemented (definition-lookup)", "assets": "implemented (dir-walk + UI-setter strings)"},
        "unity":  {"systems": "implemented", "contracts": "stub",        "symbols": "stub",                             "assets": "implemented (Assets/+Packages/ walk + PO/CSV strings)"},
        "dart":   {"systems": "implemented", "contracts": "stub",        "symbols": "stub",                             "assets": "implemented (pubspec flutter.assets + ARB strings)"},
        "ts":     {"systems": "implemented", "contracts": "implemented (regex export-scan)", "symbols": "stub",            "assets": "stub"},
        "python": {"systems": "implemented", "contracts": "implemented (AST public-surface)", "symbols": "implemented (AST def-lookup)", "assets": "stub"},
        "go":     {"systems": "stub",        "contracts": "stub",        "symbols": "stub",                             "assets": "stub"},
    }
    return supported.get(stack, {"systems": "unsupported", "contracts": "unsupported", "symbols": "unsupported", "assets": "unsupported"})

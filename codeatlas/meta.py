"""meta.json I/O — the single source of truth for codeatlas freshness."""
from __future__ import annotations

import datetime
import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict

from codeatlas import SCHEMA_VERSION
from codeatlas.detect import layer_support


def _iso_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git_head(project_root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def _tool_versions(stack: str) -> Dict[str, str]:
    versions: Dict[str, str] = {}
    if stack == "rust" and shutil.which("cargo"):
        try:
            out = subprocess.run(["cargo", "--version"], capture_output=True, text=True, timeout=10)
            if out.returncode == 0:
                versions["cargo"] = out.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    return versions


def write(project_root: Path, codeatlas_dir: Path, stack: str) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "stack": stack,
        "generated_at": _iso_now(),
        "git_head": _git_head(project_root),
        "tools": _tool_versions(stack),
        "layers": layer_support(stack) if stack != "multi-project" else {},
    }
    (codeatlas_dir / "meta.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def write_project(repo_root: Path, project_storage: Path, stack: str) -> None:
    """Write per-project meta.json under .codeatlas/projects/<id>/."""
    payload = {
        "schema_version": SCHEMA_VERSION,
        "stack": stack,
        "generated_at": _iso_now(),
        "git_head": _git_head(repo_root),
        "tools": _tool_versions(stack),
        "layers": layer_support(stack),
    }
    (project_storage / "meta.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def read(codeatlas_dir: Path) -> dict:
    path = codeatlas_dir / "meta.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))

"""One-shot migration from legacy `.codemap/` storage to `.mercator/`.

Consumer projects that adopted the tool pre-rename have a `.codemap/`
directory committed at the repo root. This module implements:

    mercator migrate [--dry-run]

which renames the directory, rewrites any internal references that
hard-code `.codemap/` in generated JSON/MD files, and updates a
project-root `.claudeignore` so agents that are told to skip the storage
dir keep doing so.

Idempotent: if `.mercator/` already exists (and `.codemap/` does not),
the migration is a no-op. If both exist, we refuse to clobber and ask
the user to resolve — the tool never deletes user data.

The `.claudeignore` update is conservative: we only touch existing
entries like `.codemap/` (exact line) or `.codemap/*` — we don't add
a new entry if the project never ignored `.codemap` in the first place.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, List, Optional


LEGACY_DIR = ".codemap"
NEW_DIR = ".mercator"


def migrate(project_root: Path, *, dry_run: bool = False) -> dict:
    """Rename `.codemap/` -> `.mercator/` and rewrite internal references.

    Returns a result dict with `status` in
    {"migrated", "already-migrated", "noop", "dry-run"} plus a `rewrites`
    list describing each file touched (or that would be touched).
    """
    legacy = project_root / LEGACY_DIR
    new = project_root / NEW_DIR

    if new.is_dir() and not legacy.is_dir():
        return {"status": "already-migrated", "from": str(legacy), "to": str(new), "rewrites": []}

    if not legacy.is_dir():
        return {"status": "noop", "from": str(legacy), "to": str(new), "rewrites": []}

    if new.is_dir() and legacy.is_dir():
        raise RuntimeError(
            f"both {legacy} and {new} exist — refusing to clobber. "
            f"Move or delete one before re-running `mercator migrate`."
        )

    # Plan the text rewrites before touching anything on disk.
    rewrites: List[str] = []
    rewrite_plan: List[tuple] = []  # (path, old_text, new_text)
    for p in legacy.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".json", ".md"):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        new_text = text.replace(".codemap/", ".mercator/")
        if new_text != text:
            rel = p.relative_to(legacy).as_posix()
            rewrites.append(rel)
            rewrite_plan.append((p, text, new_text))

    # `.claudeignore` rewrite (project-root-level only).
    ci_path = project_root / ".claudeignore"
    ci_rewrite: Optional[str] = None
    if ci_path.is_file():
        try:
            ci_text = ci_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            ci_text = None
        if ci_text is not None:
            new_ci = []
            changed = False
            for line in ci_text.splitlines():
                s = line.strip()
                if s in (".codemap/", ".codemap", ".codemap/*", ".codemap/**"):
                    new_ci.append(line.replace(".codemap", ".mercator"))
                    changed = True
                else:
                    new_ci.append(line)
            if changed:
                ci_rewrite = "\n".join(new_ci) + ("\n" if ci_text.endswith("\n") else "")
                rewrites.append(".claudeignore")

    if dry_run:
        return {
            "status": "dry-run",
            "from": str(legacy),
            "to": str(new),
            "rewrites": rewrites,
        }

    # Do it.
    # 1. Apply internal JSON/MD rewrites inside the legacy dir before the
    #    directory rename so individual-file mtimes stay correct.
    for p, _old, new_text in rewrite_plan:
        p.write_text(new_text, encoding="utf-8")

    # 2. Rename the directory. Use shutil.move for cross-filesystem safety.
    shutil.move(str(legacy), str(new))

    # 3. Rewrite .claudeignore (outside the renamed dir).
    if ci_rewrite is not None:
        ci_path.write_text(ci_rewrite, encoding="utf-8")

    return {
        "status": "migrated",
        "from": str(legacy),
        "to": str(new),
        "rewrites": rewrites,
    }

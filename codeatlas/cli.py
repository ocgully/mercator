"""codeatlas CLI — one argparse entry point, many subcommands.

Exit codes (contract for scripts + CI):
    0  success
    1  usage error
    2  missing prerequisite (cargo, python version, etc.)
    3  unsupported / unrecognised stack
    4  internal failure (parser crash, malformed input)

All `query` subcommands emit JSON by default. Pass `--format md` for the
human-friendly rendered view. Agents should prefer JSON — it's smaller
and typed. Humans reading `.codeatlas/*.md` files directly is still fine,
but those files are derived, not authoritative.

Backwards-compat: the `mercator` and `codemap` CLI entry points (shipped in
earlier releases) remain installed during the transition window. They print
a stderr deprecation warning and forward to `main()`. See
`main_deprecated_alias()` and `deprecated_main()`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from codeatlas import __version__, SCHEMA_VERSION, paths, hooks, meta
from codeatlas import boundaries as boundaries_mod
from codeatlas import projects as projects_mod
from codeatlas.detect import detect
from codeatlas import query as query_mod
from codeatlas import refresh as refresh_mod
from codeatlas.render import graph_md, boundaries_md, write_atlas


def _project_root(args) -> Path:
    if getattr(args, "project_root", None):
        return Path(args.project_root).resolve()
    return paths.find_project_root()


def _print_json(data) -> None:
    sys.stdout.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# init / refresh
# ---------------------------------------------------------------------------

def cmd_init(args) -> int:
    root = _project_root(args)
    try:
        result = refresh_mod.refresh(root)
    except RuntimeError as exc:
        print(f"codeatlas: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"codeatlas: {exc}", file=sys.stderr)
        return 3
    if not args.quiet:
        npc = result.get("project_count", 0)
        print(
            f"Initialized .codeatlas/ — {npc} project(s), "
            f"{result.get('systems_count', 0)} systems total, "
            f"{result.get('contracts_written', 0)} contract files."
        )
        for r in result.get("project_results", []):
            print(f"  - {r['id']:32} {r['stack']:8} "
                  f"{r.get('systems_count', 0)} systems, "
                  f"{r.get('contracts_written', 0)} contracts")
        print(f"  {paths.codeatlas_dir(root)}")
    return 0


def cmd_refresh(args) -> int:
    root = _project_root(args)
    project_id = getattr(args, "project", None)

    # `--files` workflow: map files → {project_id: affected_systems}.
    # When refreshing per-project, use that project's affected set if any.
    per_project_affected = None
    if args.files:
        affected_map = refresh_mod.files_to_affected_systems(root, args.files)
        if not affected_map and not args.full_on_empty:
            if not args.quiet:
                print("codeatlas: no affected systems for the given files; skipping refresh.")
            return 0
        per_project_affected = affected_map

    try:
        if project_id:
            result = refresh_mod.refresh(
                root, project_id=project_id,
                affected=(per_project_affected or {}).get(project_id) if per_project_affected else None,
            )
        elif per_project_affected and len(per_project_affected) == 1:
            # Single project affected — refresh only that one for speed.
            only_id, only_affected = next(iter(per_project_affected.items()))
            result = refresh_mod.refresh(root, project_id=only_id, affected=only_affected)
        else:
            result = refresh_mod.refresh(root)
    except RuntimeError as exc:
        print(f"codeatlas: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"codeatlas: {exc}", file=sys.stderr)
        return 3
    if not args.quiet:
        npc = result.get("project_count", 0)
        print(
            f"Refreshed .codeatlas/ — {npc} project(s), "
            f"{result.get('systems_count', 0)} systems, "
            f"{result.get('contracts_written', 0)} contract files written."
        )
        if result.get("migrated_legacy_flat_into"):
            print(f"  (migrated legacy flat layout into project '{result['migrated_legacy_flat_into']}')")
        for r in result.get("project_results", []):
            status = r.get("status", "ok")
            print(f"  - {r['id']:32} {r['stack']:8} {status:14} "
                  f"{r.get('systems_count', 0)} systems, "
                  f"{r.get('contracts_written', 0)} contracts")
    return 0


# ---------------------------------------------------------------------------
# query subcommands
# ---------------------------------------------------------------------------

def cmd_query(args) -> int:
    root = _project_root(args)
    project_id = getattr(args, "project", None)
    try:
        if args.subject == "projects":
            data = query_mod.projects(root)
        elif args.subject == "repo-edges":
            data = query_mod.repo_edges(root)
        elif args.subject == "coverage":
            data = query_mod.coverage(root)
        elif args.subject == "repo-boundaries":
            data = query_mod.repo_boundaries(root)
        elif args.subject == "repo-violations":
            data = query_mod.repo_violations(root)
        elif args.subject == "systems":
            data = query_mod.systems(root, project_id)
        elif args.subject == "deps":
            if not args.name:
                print("codeatlas: `query deps` requires <name>", file=sys.stderr)
                return 1
            data = query_mod.deps(root, args.name, project_id)
        elif args.subject == "contract":
            if not args.name:
                print("codeatlas: `query contract` requires <name>", file=sys.stderr)
                return 1
            data = query_mod.contract(root, args.name, project_id)
        elif args.subject == "symbol":
            if not args.name:
                print("codeatlas: `query symbol` requires <name>", file=sys.stderr)
                return 1
            kinds = "any"
            if args.kind != "any":
                kinds = {args.kind}
            if args.kinds:
                kinds = {k.strip() for k in args.kinds.split(",") if k.strip()}
            data = query_mod.symbol(root, args.name, kinds, project_id)
        elif args.subject == "touches":
            if not args.name:
                print("codeatlas: `query touches` requires <path>", file=sys.stderr)
                return 1
            data = query_mod.touches(root, args.name, project_id)
        elif args.subject == "system":
            if not args.name:
                print("codeatlas: `query system` requires <name>", file=sys.stderr)
                return 1
            data = query_mod.system(root, args.name, project_id)
        elif args.subject == "boundaries":
            data = query_mod.boundaries(root, project_id)
        elif args.subject == "violations":
            data = query_mod.violations(root, project_id)
        elif args.subject == "assets":
            data = _query_layer4(root, "assets", project_id,
                                 system=args.system, asset_kind=args.asset_kind)
        elif args.subject == "strings":
            data = _query_layer4(root, "strings", project_id,
                                 key=args.key, file=args.file)
        else:
            print(f"codeatlas: unknown query subject '{args.subject}'", file=sys.stderr)
            return 1
    except FileNotFoundError as exc:
        print(f"codeatlas: {exc}", file=sys.stderr)
        return 4
    except ValueError as exc:
        print(f"codeatlas: {exc}", file=sys.stderr)
        return 1

    _print_json(data)
    return 0


def _query_layer4(root: Path, layer: str, project_id, *,
                  system=None, asset_kind=None, key=None, file=None) -> dict:
    """Load <project>/{assets|strings}.json + apply optional filters."""
    import fnmatch
    proj = query_mod.resolve_project(root, project_id)
    storage = paths.project_storage_dir(paths.codeatlas_dir(root), proj["id"])
    path = storage / f"{layer}.json"
    if not path.is_file():
        return {"query": layer, "found": False, "project": proj["id"],
                "note": f"{layer}.json not present — run `codeatlas refresh`"}
    doc = json.loads(path.read_text(encoding="utf-8"))
    items_key = layer
    items = doc.get(items_key, [])
    if system:
        items = [i for i in items if i.get("owning_system") == system]
    if asset_kind:
        items = [i for i in items if i.get("kind") == asset_kind]
    if key:
        items = [i for i in items
                 if i.get("key") and fnmatch.fnmatchcase(i["key"], key)]
    if file:
        items = [i for i in items if i.get("file") == file]
    out = dict(doc)
    out[items_key] = items
    out["query"] = layer
    out["project"] = proj["id"]
    out["filters"] = {"system": system, "asset_kind": asset_kind,
                      "key": key, "file": file}
    out["count"] = len(items)
    return out


def cmd_diff(args) -> int:
    from codeatlas import diff as diff_mod
    root = _project_root(args)
    if ".." not in args.range:
        print("codeatlas: diff requires a 'refA..refB' range", file=sys.stderr)
        return 1
    ref_a, ref_b = args.range.split("..", 1)
    if not ref_a or not ref_b:
        print("codeatlas: diff requires both sides of the range", file=sys.stderr)
        return 1
    data = diff_mod.compute_diff(root, ref_a, ref_b)
    if args.format == "md":
        sys.stdout.write(diff_mod.render_diff_md(data) + "\n")
    else:
        _print_json(data)
    return 0


# ---------------------------------------------------------------------------
# hooks
# ---------------------------------------------------------------------------

def cmd_hooks(args) -> int:
    root = _project_root(args)
    if args.action == "install":
        launcher = Path(__file__).resolve().parents[2] / "codeatlas.py"
        if not launcher.is_file():
            # Legacy launcher names (during transition).
            for legacy_name in ("mercator.py", "codemap.py"):
                legacy = Path(__file__).resolve().parents[2] / legacy_name
                if legacy.is_file():
                    launcher = legacy
                    break
        try:
            hp = hooks.install(root, launcher_path=launcher if launcher.is_file() else None)
        except RuntimeError as exc:
            print(f"codeatlas: {exc}", file=sys.stderr)
            return 2
        if not args.quiet:
            print(f"Installed post-commit hook at {hp}")
        return 0
    if args.action == "uninstall":
        ok = hooks.uninstall(root)
        if not args.quiet:
            print("Uninstalled." if ok else "No codeatlas hook found.")
        return 0
    print(f"codeatlas: unknown hooks action '{args.action}'", file=sys.stderr)
    return 1


# ---------------------------------------------------------------------------
# migrate — one-shot rename of legacy storage dir to .codeatlas/
# ---------------------------------------------------------------------------

def cmd_migrate(args) -> int:
    from codeatlas import migrate as migrate_mod
    root = _project_root(args)
    try:
        result = migrate_mod.migrate(root, dry_run=args.dry_run)
    except RuntimeError as exc:
        print(f"codeatlas: {exc}", file=sys.stderr)
        return 4
    if not args.quiet:
        if result["status"] == "migrated":
            print(f"Migrated {result['from']} -> {result['to']}")
            for note in result.get("rewrites", []):
                print(f"  rewrote: {note}")
        elif result["status"] == "already-migrated":
            print(f"Already on .codeatlas/ — nothing to do.")
        elif result["status"] == "noop":
            print("No legacy .mercator/ or .codemap/ directory found — nothing to migrate.")
        elif result["status"] == "dry-run":
            print(f"[dry-run] would migrate {result['from']} -> {result['to']}")
            for note in result.get("rewrites", []):
                print(f"  [dry-run] would rewrite: {note}")
    return 0


# ---------------------------------------------------------------------------
# info / version
# ---------------------------------------------------------------------------

def cmd_check(args) -> int:
    """CI-friendly: exit 0 clean, exit 1 on any error-severity violation.

    Aggregates across all projects in the repo (or one with --project).
    """
    root = _project_root(args)
    repo_storage = paths.codeatlas_dir(root)
    from codeatlas import projects as projects_mod
    projects_doc = projects_mod.load_projects(repo_storage)
    if projects_doc is None:
        print("codeatlas: no projects.json — run `codeatlas init` first", file=sys.stderr)
        return 4

    target_id = getattr(args, "project", None)
    targets = projects_doc.get("projects") or []
    if target_id:
        targets = [p for p in targets if p["id"] == target_id]

    all_violations = []  # (project_id_or_<repo>, violation)
    for proj in targets:
        ps = paths.project_storage_dir(repo_storage, proj["id"])
        sys_path = ps / "systems.json"
        bnd_path = ps / "boundaries.json"
        if not sys_path.is_file():
            continue
        try:
            import json as _json
            sys_doc = _json.loads(sys_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        try:
            bnd_doc = boundaries_mod.load_path(bnd_path)
        except ValueError as exc:
            print(f"codeatlas: boundaries file error in '{proj['id']}' — {exc}", file=sys.stderr)
            return 4
        if not bnd_doc:
            continue
        for v in boundaries_mod.evaluate(sys_doc, bnd_doc):
            all_violations.append((proj["id"], v))

    # Repo-level (cross-project) rules — only when targeting the whole repo
    # (not a single --project).
    if not target_id:
        from codeatlas import repo_boundaries as repo_bnd_mod
        from codeatlas import repo_edges as repo_edges_mod
        try:
            repo_bnd_doc = repo_bnd_mod.load(repo_storage)
        except ValueError as exc:
            print(f"codeatlas: repo-boundaries file error — {exc}", file=sys.stderr)
            return 4
        if repo_bnd_doc:
            edges_doc = (repo_edges_mod.load_edges(repo_storage)
                         or repo_edges_mod.compute_edges(root))
            for v in repo_bnd_mod.evaluate(projects_doc, edges_doc, repo_bnd_doc):
                all_violations.append(("<repo>", v))

    errors = [(pid, v) for pid, v in all_violations if v["severity"] == "error"]
    warnings = [(pid, v) for pid, v in all_violations if v["severity"] == "warning"]
    infos = [(pid, v) for pid, v in all_violations if v["severity"] == "info"]

    if args.format == "json":
        _print_json({
            "check": "boundaries",
            "project_count": len(targets),
            "error_count": len(errors),
            "warning_count": len(warnings),
            "info_count": len(infos),
            "violations": [{"project": pid, **v} for pid, v in all_violations],
            "pass": len(errors) == 0,
        })
    else:
        if not all_violations:
            if not args.quiet:
                print("codeatlas check: PASS — no boundary violations across all projects.")
            return 0
        print(f"codeatlas check: {len(errors)} error, {len(warnings)} warning, {len(infos)} info "
              f"(across {len(targets)} project(s) + repo-level)")
        for pid, v in all_violations:
            arrow = " -> ".join(v["path"])
            scope = "repo" if pid == "<repo>" else f"project {pid}"
            print(f"  [{v['severity'].upper():7}] [{scope}] {v['rule_name']}")
            print(f"             {arrow}")
            if v.get("rationale"):
                print(f"             ({v['rationale']})")
    return 1 if errors else 0


def cmd_render(args) -> int:
    """Regenerate visual views (graph.md + boundaries.md per project + atlas.html).

    All deterministic — no source-of-truth data is touched.
    """
    root = _project_root(args)
    repo_storage = paths.codeatlas_dir(root)
    from codeatlas import projects as projects_mod
    projects_doc = projects_mod.load_projects(repo_storage)
    if projects_doc is None:
        print("codeatlas: no projects.json — run `codeatlas init` first", file=sys.stderr)
        return 4

    targets = projects_doc.get("projects") or []
    target_id = getattr(args, "project", None)
    if target_id:
        targets = [p for p in targets if p["id"] == target_id]

    rendered: List[Path] = []
    for proj in targets:
        ps = paths.project_storage_dir(repo_storage, proj["id"])
        sys_path = ps / "systems.json"
        if not sys_path.is_file():
            continue
        import json as _json
        sys_doc = _json.loads(sys_path.read_text(encoding="utf-8"))
        try:
            bnd_doc = boundaries_mod.load_path(ps / "boundaries.json")
        except ValueError as exc:
            print(f"codeatlas: boundaries file error in '{proj['id']}' — {exc}", file=sys.stderr)
            return 4
        (ps / "graph.md").write_text(graph_md.render(sys_doc, bnd_doc), encoding="utf-8")
        (ps / "boundaries.md").write_text(boundaries_md.render(sys_doc, bnd_doc), encoding="utf-8")
        rendered.append(ps / "graph.md")
        rendered.append(ps / "boundaries.md")

    atlas_path = write_atlas(root)
    if not args.quiet:
        for p in rendered:
            print(f"Rendered {p}")
        print(f"Rendered {atlas_path}")
        print("Open the .md files in any markdown viewer (GitHub, VS Code, Obsidian); open atlas.html in a browser.")
    return 0


def cmd_boundaries(args) -> int:
    """Scaffold or validate boundaries — project-scoped by default,
    repo-level with `--repo`."""
    root = _project_root(args)
    repo_storage = paths.codeatlas_dir(root)

    if getattr(args, "repo", False):
        return _cmd_boundaries_repo(args, repo_storage, root)

    project_id = getattr(args, "project", None)
    try:
        proj = query_mod.resolve_project(root, project_id)
    except ValueError as exc:
        print(f"codeatlas: {exc}", file=sys.stderr)
        return 1
    ps = paths.project_storage_dir(repo_storage, proj["id"])
    path = ps / "boundaries.json"

    if args.action == "init":
        if path.is_file() and not args.force:
            print(f"codeatlas: {path} already exists. Use --force to overwrite.", file=sys.stderr)
            return 1
        ps.mkdir(parents=True, exist_ok=True)
        path.write_text(boundaries_mod.SCAFFOLD_JSON, encoding="utf-8")
        if not args.quiet:
            print(f"Scaffolded {path} (project '{proj['id']}')")
            print("Edit it to declare forbidden edges. Rerun `codeatlas check` to see violations.")
        return 0

    if args.action == "validate":
        try:
            doc = boundaries_mod.load_path(path)
        except ValueError as exc:
            print(f"codeatlas: {exc}", file=sys.stderr)
            return 4
        if not doc:
            print(f"codeatlas: no boundaries.json to validate in '{proj['id']}'.")
            return 0
        sys_path = ps / "systems.json"
        if not sys_path.is_file():
            print(f"codeatlas: no systems.json for '{proj['id']}' — run `codeatlas refresh` first", file=sys.stderr)
            return 4
        sys_doc = json.loads(sys_path.read_text(encoding="utf-8"))
        rules = boundaries_mod.summarise_rules(sys_doc, doc)
        empty = [r for r in rules if not r["resolved_from"] or not r["resolved_not_to"]]
        if empty:
            print(f"codeatlas: {len(empty)} rule(s) resolve to empty system set — check selectors:", file=sys.stderr)
            for r in empty:
                print(f"  - {r['name']}: from={r['from_selector']!r} -> {r['resolved_from']}, "
                      f"not_to={r['not_to_selector']!r} -> {r['resolved_not_to']}", file=sys.stderr)
            return 4
        if not args.quiet:
            print(f"codeatlas: {len(rules)} rule(s) OK in '{proj['id']}'")
        return 0
    print(f"codeatlas: unknown boundaries action '{args.action}'", file=sys.stderr)
    return 1


def _cmd_boundaries_repo(args, repo_storage: Path, repo_root: Path) -> int:
    """Repo-level (cross-project) boundaries scaffold + validate."""
    from codeatlas import repo_boundaries as repo_bnd_mod
    from codeatlas import repo_edges as repo_edges_mod
    path = repo_storage / "repo-boundaries.json"

    if args.action == "init":
        if path.is_file() and not args.force:
            print(f"codeatlas: {path} already exists. Use --force to overwrite.", file=sys.stderr)
            return 1
        repo_storage.mkdir(parents=True, exist_ok=True)
        path.write_text(repo_bnd_mod.SCAFFOLD_JSON, encoding="utf-8")
        if not args.quiet:
            print(f"Scaffolded {path}")
            print("Edit it to declare cross-project DMZ rules. Rerun `codeatlas check` to see violations.")
        return 0

    if args.action == "validate":
        try:
            doc = repo_bnd_mod.load(repo_storage)
        except ValueError as exc:
            print(f"codeatlas: {exc}", file=sys.stderr)
            return 4
        if not doc:
            print("codeatlas: no repo-boundaries.json to validate.")
            return 0
        projects_doc = projects_mod.load_projects(repo_storage) or projects_mod.detect_projects(repo_root)
        from codeatlas import repo_edges as repo_edges_mod2
        edges_doc = repo_edges_mod2.load_edges(repo_storage) or repo_edges_mod2.compute_edges(repo_root)
        rules = repo_bnd_mod.summarise_rules(projects_doc, edges_doc, doc)
        empty = [r for r in rules if not r["resolved_from"] or not r["resolved_not_to"]]
        if empty:
            print(f"codeatlas: {len(empty)} repo-rule(s) resolve to empty project set:", file=sys.stderr)
            for r in empty:
                print(f"  - {r['name']}: from={r['from_selector']!r} -> {r['resolved_from']}, "
                      f"not_to={r['not_to_selector']!r} -> {r['resolved_not_to']}", file=sys.stderr)
            return 4
        if not args.quiet:
            print(f"codeatlas: {len(rules)} repo-rule(s) OK")
        return 0
    print(f"codeatlas: unknown boundaries action '{args.action}'", file=sys.stderr)
    return 1


def cmd_projects(args) -> int:
    """List detected projects, or re-run detection."""
    root = _project_root(args)
    cmdir = paths.codeatlas_dir(root)
    if args.action == "detect":
        cmdir.mkdir(parents=True, exist_ok=True)
        doc = projects_mod.write_projects(root, cmdir)
        if not args.quiet:
            print(f"Detected {doc['project_count']} project(s) — {cmdir / 'projects.json'}")
            for p in doc["projects"]:
                tag = f" [{','.join(p['tags'])}]" if p["tags"] else ""
                print(f"  {p['id']:32} {p['stack']:8} {p['category']:8} {p['root']}{tag}")
        return 0
    if args.action == "list":
        doc = projects_mod.load_projects(cmdir)
        if doc is None:
            doc = projects_mod.detect_projects(root)
        if args.format == "json":
            _print_json(doc)
            return 0
        print(f"# {doc['project_count']} project(s) in {root}")
        for p in doc["projects"]:
            tag = f" [{','.join(p['tags'])}]" if p["tags"] else ""
            print(f"  {p['id']:32} {p['stack']:8} {p['category']:8} {p['root']}{tag}")
        return 0
    print(f"codeatlas: unknown projects action '{args.action}'", file=sys.stderr)
    return 1


def cmd_atlas(args) -> int:
    """Regenerate `.codeatlas/atlas.html` — the interactive code atlas."""
    root = _project_root(args)
    cmdir = paths.codeatlas_dir(root)
    if not (cmdir / "projects.json").is_file():
        print("codeatlas: no projects.json — run `codeatlas init` first", file=sys.stderr)
        return 4
    out = write_atlas(root)
    if not args.quiet:
        print(f"Rendered {out}")
        print("Open it in any browser (double-click, or `file://` URL) — no server needed.")
    if args.open:
        try:
            import webbrowser
            webbrowser.open(out.as_uri())
        except Exception as exc:  # noqa: BLE001
            print(f"codeatlas: failed to open browser: {exc}", file=sys.stderr)
    return 0


def cmd_info(args) -> int:
    root = _project_root(args)
    stack = detect(root)
    m = meta.read(paths.codeatlas_dir(root))
    _print_json({
        "codeatlas_version": __version__,
        "schema_version": SCHEMA_VERSION,
        "project_root": str(root),
        "storage_dir": str(paths.codeatlas_dir(root)),
        "detected_stack": stack,
        "initialized": bool(m),
        "meta": m,
    })
    return 0


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

def _build_parser(prog: str = "codeatlas") -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=prog,
        description="Layered, AI-friendly codemap — agent-consumable via JSON queries.",
    )
    p.add_argument("--version", action="version", version=f"{prog} {__version__} (schema {SCHEMA_VERSION})")
    p.add_argument("--project-root", help="Override project-root detection")
    p.add_argument("--storage-dir",
                   help="Redirect .codeatlas/ storage dir (read + write). "
                        "Use this to analyse a project without planting "
                        "files inside it.")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", help="Initialize .codeatlas/ and run all implemented layers")
    sp.add_argument("--quiet", action="store_true")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("refresh", help="Regenerate layers. `--files` for incremental.")
    sp.add_argument("--files", nargs="*", default=None, help="Changed files (relative to project root) — only affected systems regen")
    sp.add_argument("--full-on-empty", action="store_true", help="If --files resolves to zero affected systems, do a full refresh anyway")
    sp.add_argument("--project", default=None, help="Refresh only this project id")
    sp.add_argument("--quiet", action="store_true")
    sp.set_defaults(func=cmd_refresh)

    sp = sub.add_parser("query", help="Query a slice. JSON by default.")
    sp.add_argument("subject",
                    choices=["projects", "repo-edges", "repo-boundaries", "repo-violations", "coverage",
                             "systems", "deps", "contract", "symbol", "touches", "system",
                             "boundaries", "violations", "assets", "strings"])
    sp.add_argument("name", nargs="?", help="Name/path argument for the query")
    sp.add_argument("--project", default=None, help="Target project id (required when repo has >1 project)")
    sp.add_argument("--kind", default="any",
                    choices=["any", "fn", "struct", "enum", "trait", "type", "const", "static", "mod"],
                    help="(symbol) Restrict to one kind")
    sp.add_argument("--kinds", default=None, help="(symbol) Comma-separated kind set (overrides --kind)")
    sp.add_argument("--system", default=None, help="(assets/strings) Filter to one owning system")
    sp.add_argument("--asset-kind", default=None, help="(assets) Filter by asset kind (texture|audio|model|scene|material|vector|…)")
    sp.add_argument("--key", default=None, help="(strings) Filter by localisation key (glob OK)")
    sp.add_argument("--file", default=None, help="(strings) Filter to one file")
    sp.set_defaults(func=cmd_query)

    sp = sub.add_parser("diff",
                        help="Structural delta between two git refs (systems, edges, contracts)")
    sp.add_argument("range", help="Ref range, e.g. 'HEAD~5..HEAD' or 'v0.1.0..main'")
    sp.add_argument("--format", choices=["json", "md"], default="json")
    sp.set_defaults(func=cmd_diff)

    sp = sub.add_parser("hooks", help="Git hook management")
    sp.add_argument("action", choices=["install", "uninstall"])
    sp.add_argument("--quiet", action="store_true")
    sp.set_defaults(func=cmd_hooks)

    sp = sub.add_parser("migrate",
                        aliases=["migrate-from-mercator"],
                        help="Rename legacy .mercator/ (or .codemap/) to .codeatlas/ and rewrite internal references")
    sp.add_argument("--dry-run", action="store_true", help="Show what would change without touching the filesystem")
    sp.add_argument("--quiet", action="store_true")
    sp.set_defaults(func=cmd_migrate)

    sp = sub.add_parser("check", help="CI-friendly: exit 1 on any boundary violation of severity 'error'")
    sp.add_argument("--format", choices=["text", "json"], default="text")
    sp.add_argument("--project", default=None, help="Restrict the check to one project")
    sp.add_argument("--quiet", action="store_true")
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("render", help="Regenerate graph.md + boundaries.md (human-viewable via mermaid)")
    sp.add_argument("--project", default=None, help="Render only one project")
    sp.add_argument("--quiet", action="store_true")
    sp.set_defaults(func=cmd_render)

    sp = sub.add_parser("boundaries", help="Scaffold or validate boundaries.json")
    sp.add_argument("action", choices=["init", "validate"])
    sp.add_argument("--project", default=None, help="Project to operate on (required when repo has >1)")
    sp.add_argument("--repo", action="store_true",
                    help="Operate on repo-level (cross-project) boundaries instead of a single project's")
    sp.add_argument("--force", action="store_true", help="(init) Overwrite existing boundaries.json")
    sp.add_argument("--quiet", action="store_true")
    sp.set_defaults(func=cmd_boundaries)

    sp = sub.add_parser("projects", help="List detected projects, or re-run detection")
    sp.add_argument("action", choices=["list", "detect"])
    sp.add_argument("--format", choices=["text", "json"], default="text")
    sp.add_argument("--quiet", action="store_true")
    sp.set_defaults(func=cmd_projects)

    sp = sub.add_parser("atlas",
                        help="Regenerate the interactive code atlas (.codeatlas/atlas.html)")
    sp.add_argument("--open", action="store_true", help="Open the atlas in the default browser after writing")
    sp.add_argument("--quiet", action="store_true")
    sp.set_defaults(func=cmd_atlas)

    sp = sub.add_parser("info", help="Show project root, detected stack, and meta.json")
    sp.set_defaults(func=cmd_info)

    return p


def _apply_storage_override(args) -> None:
    override = getattr(args, "storage_dir", None)
    if override:
        paths.set_storage_override(Path(override))


def main(argv=None) -> int:
    parser = _build_parser("codeatlas")
    args = parser.parse_args(argv)
    _apply_storage_override(args)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ncodeatlas: interrupted", file=sys.stderr)
        return 130


def main_deprecated_alias(argv=None) -> int:
    """Deprecation-shim entry point for the legacy `mercator` script.

    Prints a one-line stderr warning and forwards to `main()`. Scheduled
    for removal in v2.0 (kept for two minor cycles). See README for
    migration notes.
    """
    sys.stderr.write(
        "mercator: 'mercator' is the legacy name for codeatlas; "
        "this alias will be removed in v2.0\n"
    )
    parser = _build_parser("mercator")
    args = parser.parse_args(argv)
    _apply_storage_override(args)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ncodeatlas: interrupted", file=sys.stderr)
        return 130


def deprecated_main(argv=None) -> int:
    """Deprecation-shim entry point for the legacy `codemap` script.

    Prints a one-line stderr warning and forwards to `main()`. Will be
    removed in the release after next. See README for migration notes.
    """
    sys.stderr.write(
        "codemap: DEPRECATED — this CLI has been renamed to `codeatlas`. "
        "Please invoke `codeatlas` instead. This shim will be removed in a "
        "future release.\n"
    )
    parser = _build_parser("codemap")
    args = parser.parse_args(argv)
    _apply_storage_override(args)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ncodemap: interrupted", file=sys.stderr)
        return 130

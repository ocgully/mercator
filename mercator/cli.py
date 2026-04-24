"""mercator CLI — one argparse entry point, many subcommands.

Exit codes (contract for scripts + CI):
    0  success
    1  usage error
    2  missing prerequisite (cargo, python version, etc.)
    3  unsupported / unrecognised stack
    4  internal failure (parser crash, malformed input)

All `query` subcommands emit JSON by default. Pass `--format md` for the
human-friendly rendered view. Agents should prefer JSON — it's smaller
and typed. Humans reading `.mercator/*.md` files directly is still fine,
but those files are derived, not authoritative.

Backwards-compat: the `codemap` CLI entry point (shipped in earlier releases)
remains installed during the transition window. It prints a stderr
deprecation warning and forwards to `main()`. See `deprecated_main()`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from mercator import __version__, SCHEMA_VERSION, paths, hooks, meta
from mercator import boundaries as boundaries_mod
from mercator import projects as projects_mod
from mercator.detect import detect
from mercator import query as query_mod
from mercator import refresh as refresh_mod
from mercator.render import graph_md, boundaries_md, write_atlas


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
        print(f"mercator: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"mercator: {exc}", file=sys.stderr)
        return 3
    if not args.quiet:
        npc = result.get("project_count", 0)
        print(
            f"Initialized .mercator/ — {npc} project(s), "
            f"{result.get('systems_count', 0)} systems total, "
            f"{result.get('contracts_written', 0)} contract files."
        )
        for r in result.get("project_results", []):
            print(f"  - {r['id']:32} {r['stack']:8} "
                  f"{r.get('systems_count', 0)} systems, "
                  f"{r.get('contracts_written', 0)} contracts")
        print(f"  {paths.mercator_dir(root)}")
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
                print("mercator: no affected systems for the given files; skipping refresh.")
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
        print(f"mercator: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"mercator: {exc}", file=sys.stderr)
        return 3
    if not args.quiet:
        npc = result.get("project_count", 0)
        print(
            f"Refreshed .mercator/ — {npc} project(s), "
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
        elif args.subject == "systems":
            data = query_mod.systems(root, project_id)
        elif args.subject == "deps":
            if not args.name:
                print("mercator: `query deps` requires <name>", file=sys.stderr)
                return 1
            data = query_mod.deps(root, args.name, project_id)
        elif args.subject == "contract":
            if not args.name:
                print("mercator: `query contract` requires <name>", file=sys.stderr)
                return 1
            data = query_mod.contract(root, args.name, project_id)
        elif args.subject == "symbol":
            if not args.name:
                print("mercator: `query symbol` requires <name>", file=sys.stderr)
                return 1
            kinds = "any"
            if args.kind != "any":
                kinds = {args.kind}
            if args.kinds:
                kinds = {k.strip() for k in args.kinds.split(",") if k.strip()}
            data = query_mod.symbol(root, args.name, kinds, project_id)
        elif args.subject == "touches":
            if not args.name:
                print("mercator: `query touches` requires <path>", file=sys.stderr)
                return 1
            data = query_mod.touches(root, args.name, project_id)
        elif args.subject == "system":
            if not args.name:
                print("mercator: `query system` requires <name>", file=sys.stderr)
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
            print(f"mercator: unknown query subject '{args.subject}'", file=sys.stderr)
            return 1
    except FileNotFoundError as exc:
        print(f"mercator: {exc}", file=sys.stderr)
        return 4
    except ValueError as exc:
        print(f"mercator: {exc}", file=sys.stderr)
        return 1

    _print_json(data)
    return 0


def _query_layer4(root: Path, layer: str, project_id, *,
                  system=None, asset_kind=None, key=None, file=None) -> dict:
    """Load <project>/{assets|strings}.json + apply optional filters."""
    import fnmatch
    proj = query_mod.resolve_project(root, project_id)
    storage = paths.project_storage_dir(paths.mercator_dir(root), proj["id"])
    path = storage / f"{layer}.json"
    if not path.is_file():
        return {"query": layer, "found": False, "project": proj["id"],
                "note": f"{layer}.json not present — run `mercator refresh`"}
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
    from mercator import diff as diff_mod
    root = _project_root(args)
    if ".." not in args.range:
        print("mercator: diff requires a 'refA..refB' range", file=sys.stderr)
        return 1
    ref_a, ref_b = args.range.split("..", 1)
    if not ref_a or not ref_b:
        print("mercator: diff requires both sides of the range", file=sys.stderr)
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
        launcher = Path(__file__).resolve().parents[2] / "mercator.py"
        if not launcher.is_file():
            # Legacy launcher name (during transition).
            legacy = Path(__file__).resolve().parents[2] / "codemap.py"
            launcher = legacy if legacy.is_file() else launcher
        try:
            hp = hooks.install(root, launcher_path=launcher if launcher.is_file() else None)
        except RuntimeError as exc:
            print(f"mercator: {exc}", file=sys.stderr)
            return 2
        if not args.quiet:
            print(f"Installed post-commit hook at {hp}")
        return 0
    if args.action == "uninstall":
        ok = hooks.uninstall(root)
        if not args.quiet:
            print("Uninstalled." if ok else "No mercator hook found.")
        return 0
    print(f"mercator: unknown hooks action '{args.action}'", file=sys.stderr)
    return 1


# ---------------------------------------------------------------------------
# migrate — one-shot rename from .codemap/ to .mercator/
# ---------------------------------------------------------------------------

def cmd_migrate(args) -> int:
    from mercator import migrate as migrate_mod
    root = _project_root(args)
    try:
        result = migrate_mod.migrate(root, dry_run=args.dry_run)
    except RuntimeError as exc:
        print(f"mercator: {exc}", file=sys.stderr)
        return 4
    if not args.quiet:
        if result["status"] == "migrated":
            print(f"Migrated {result['from']} -> {result['to']}")
            for note in result.get("rewrites", []):
                print(f"  rewrote: {note}")
        elif result["status"] == "already-migrated":
            print(f"Already on .mercator/ — nothing to do.")
        elif result["status"] == "noop":
            print("No .codemap/ or .mercator/ directory found — nothing to migrate.")
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
    repo_storage = paths.mercator_dir(root)
    from mercator import projects as projects_mod
    projects_doc = projects_mod.load_projects(repo_storage)
    if projects_doc is None:
        print("mercator: no projects.json — run `mercator init` first", file=sys.stderr)
        return 4

    target_id = getattr(args, "project", None)
    targets = projects_doc.get("projects") or []
    if target_id:
        targets = [p for p in targets if p["id"] == target_id]

    all_violations = []  # (project_id, violation)
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
            print(f"mercator: boundaries file error in '{proj['id']}' — {exc}", file=sys.stderr)
            return 4
        if not bnd_doc:
            continue
        for v in boundaries_mod.evaluate(sys_doc, bnd_doc):
            all_violations.append((proj["id"], v))

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
                print("mercator check: PASS — no boundary violations across all projects.")
            return 0
        print(f"mercator check: {len(errors)} error, {len(warnings)} warning, {len(infos)} info "
              f"(across {len(targets)} project(s))")
        for pid, v in all_violations:
            arrow = " -> ".join(v["path"])
            print(f"  [{v['severity'].upper():7}] [{pid}] {v['rule_name']}")
            print(f"             {arrow}")
            if v.get("rationale"):
                print(f"             ({v['rationale']})")
    return 1 if errors else 0


def cmd_render(args) -> int:
    """Regenerate visual views (graph.md + boundaries.md per project + atlas.html).

    All deterministic — no source-of-truth data is touched.
    """
    root = _project_root(args)
    repo_storage = paths.mercator_dir(root)
    from mercator import projects as projects_mod
    projects_doc = projects_mod.load_projects(repo_storage)
    if projects_doc is None:
        print("mercator: no projects.json — run `mercator init` first", file=sys.stderr)
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
            print(f"mercator: boundaries file error in '{proj['id']}' — {exc}", file=sys.stderr)
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
    """Scaffold or validate boundaries.json — always project-scoped."""
    root = _project_root(args)
    project_id = getattr(args, "project", None)
    try:
        proj = query_mod.resolve_project(root, project_id)
    except ValueError as exc:
        print(f"mercator: {exc}", file=sys.stderr)
        return 1
    repo_storage = paths.mercator_dir(root)
    ps = paths.project_storage_dir(repo_storage, proj["id"])
    path = ps / "boundaries.json"

    if args.action == "init":
        if path.is_file() and not args.force:
            print(f"mercator: {path} already exists. Use --force to overwrite.", file=sys.stderr)
            return 1
        ps.mkdir(parents=True, exist_ok=True)
        path.write_text(boundaries_mod.SCAFFOLD_JSON, encoding="utf-8")
        if not args.quiet:
            print(f"Scaffolded {path} (project '{proj['id']}')")
            print("Edit it to declare forbidden edges. Rerun `mercator check` to see violations.")
        return 0

    if args.action == "validate":
        try:
            doc = boundaries_mod.load_path(path)
        except ValueError as exc:
            print(f"mercator: {exc}", file=sys.stderr)
            return 4
        if not doc:
            print(f"mercator: no boundaries.json to validate in '{proj['id']}'.")
            return 0
        sys_path = ps / "systems.json"
        if not sys_path.is_file():
            print(f"mercator: no systems.json for '{proj['id']}' — run `mercator refresh` first", file=sys.stderr)
            return 4
        sys_doc = json.loads(sys_path.read_text(encoding="utf-8"))
        rules = boundaries_mod.summarise_rules(sys_doc, doc)
        empty = [r for r in rules if not r["resolved_from"] or not r["resolved_not_to"]]
        if empty:
            print(f"mercator: {len(empty)} rule(s) resolve to empty system set — check selectors:", file=sys.stderr)
            for r in empty:
                print(f"  - {r['name']}: from={r['from_selector']!r} -> {r['resolved_from']}, "
                      f"not_to={r['not_to_selector']!r} -> {r['resolved_not_to']}", file=sys.stderr)
            return 4
        if not args.quiet:
            print(f"mercator: {len(rules)} rule(s) OK in '{proj['id']}'")
        return 0
    print(f"mercator: unknown boundaries action '{args.action}'", file=sys.stderr)
    return 1


def cmd_projects(args) -> int:
    """List detected projects, or re-run detection."""
    root = _project_root(args)
    cmdir = paths.mercator_dir(root)
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
    print(f"mercator: unknown projects action '{args.action}'", file=sys.stderr)
    return 1


def cmd_atlas(args) -> int:
    """Regenerate `.mercator/atlas.html` — the interactive code atlas."""
    root = _project_root(args)
    cmdir = paths.mercator_dir(root)
    if not (cmdir / "projects.json").is_file():
        print("mercator: no projects.json — run `mercator init` first", file=sys.stderr)
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
            print(f"mercator: failed to open browser: {exc}", file=sys.stderr)
    return 0


def cmd_info(args) -> int:
    root = _project_root(args)
    stack = detect(root)
    m = meta.read(paths.mercator_dir(root))
    _print_json({
        "mercator_version": __version__,
        "schema_version": SCHEMA_VERSION,
        "project_root": str(root),
        "storage_dir": str(paths.mercator_dir(root)),
        "detected_stack": stack,
        "initialized": bool(m),
        "meta": m,
    })
    return 0


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

def _build_parser(prog: str = "mercator") -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=prog,
        description="Layered, AI-friendly codemap — agent-consumable via JSON queries.",
    )
    p.add_argument("--version", action="version", version=f"{prog} {__version__} (schema {SCHEMA_VERSION})")
    p.add_argument("--project-root", help="Override project-root detection")
    p.add_argument("--storage-dir",
                   help="Redirect .mercator/ storage dir (read + write). "
                        "Use this to analyse a project without planting "
                        "files inside it.")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", help="Initialize .mercator/ and run all implemented layers")
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
                    choices=["projects", "repo-edges", "systems", "deps", "contract", "symbol", "touches", "system",
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
                        help="Rename legacy .codemap/ to .mercator/ and rewrite internal references")
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

    sp = sub.add_parser("boundaries", help="Scaffold or validate boundaries.json (per project)")
    sp.add_argument("action", choices=["init", "validate"])
    sp.add_argument("--project", default=None, help="Project to operate on (required when repo has >1)")
    sp.add_argument("--force", action="store_true", help="(init) Overwrite existing boundaries.json")
    sp.add_argument("--quiet", action="store_true")
    sp.set_defaults(func=cmd_boundaries)

    sp = sub.add_parser("projects", help="List detected projects, or re-run detection")
    sp.add_argument("action", choices=["list", "detect"])
    sp.add_argument("--format", choices=["text", "json"], default="text")
    sp.add_argument("--quiet", action="store_true")
    sp.set_defaults(func=cmd_projects)

    sp = sub.add_parser("atlas",
                        help="Regenerate the interactive code atlas (.mercator/atlas.html)")
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
    parser = _build_parser("mercator")
    args = parser.parse_args(argv)
    _apply_storage_override(args)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nmercator: interrupted", file=sys.stderr)
        return 130


def deprecated_main(argv=None) -> int:
    """Deprecation-shim entry point for the legacy `codemap` script.

    Prints a one-line stderr warning and forwards to `main()`. Will be
    removed in the release after next. See README for migration notes.
    """
    sys.stderr.write(
        "codemap: DEPRECATED — this CLI has been renamed to `mercator`. "
        "Please invoke `mercator` instead. This shim will be removed in a "
        "future release.\n"
    )
    parser = _build_parser("codemap")
    args = parser.parse_args(argv)
    _apply_storage_override(args)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nmercator: interrupted", file=sys.stderr)
        return 130

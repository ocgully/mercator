"""Atlas renderer — assembles single-file HTML pages from templates + static assets.

Layout (all under this package):

    templates/
      single_project.html   # outer shell for a per-project atlas
      repo_index.html       # outer shell for the multi-project picker
    static/
      atlas.css             # shared styles
      atlas.js              # single-project app code
      repo_index.js         # repo-index page code

Authoring lives in real .html / .css / .js files (proper editor support, no
1000-line f-strings). Every output HTML is single-file, double-clickable —
the CSS and JS are inlined into the output by string substitution. No build
step, no Node, no server.

Placeholder grammar (intentionally tiny, no template engine):

    {{DATA}}            JSON island contents
    {{CSS}}             contents of static/atlas.css
    {{JS}}              contents of the relevant script
    {{VERSION}}         mercator package version
    {{STACK}}           stack name (single-project page only)
    {{TITLE}}           page title (single-project page only)
    {{PROJECT_COUNT}}   number of projects (repo-index page only)

Substitution is a literal `str.replace`; placeholders never appear in
template content for any reason other than substitution. Use raw strings
in the templates for HTML/CSS/JS that may contain `{{` (none currently do).
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Dict, List, Optional


_PKG_DIR = Path(__file__).resolve().parent
_TEMPLATES = _PKG_DIR / "templates"
_STATIC = _PKG_DIR / "static"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _stamp(template: str, **subs: str) -> str:
    out = template
    for key, val in subs.items():
        out = out.replace("{{" + key + "}}", val)
    return out


def _safe_json(payload: dict) -> str:
    """Serialise `payload` for embedding in a `<script type="application/json">`.

    Splits any literal `</` so the browser doesn't end the script element on
    an embedded `</script>` token in user-controlled strings.
    """
    s = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return s.replace("</", "<\\/")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_single_project(
    *,
    bundle: dict,
    mercator_version: str,
    schema_version: str,
    repo_meta: Optional[dict] = None,
    projects_doc: Optional[dict] = None,
    href_back: Optional[str] = None,
) -> str:
    """Render a single project's atlas to a self-contained HTML string.

    `bundle` is a dict from `mercator.render._read_project(...)` containing
    systems / contracts / boundaries / violations / assets / strings / meta /
    project. `href_back` is set when this page is rendered as a child of a
    repo index — it adds an `↑ Repo` topbar link.
    """
    project = bundle["project"]
    payload = {
        "mercator_version": mercator_version,
        "schema_version": schema_version,
        "project": project,
        "systems": bundle["systems"] or {"systems": [], "stack": "unknown"},
        "contracts": bundle["contracts"] or {},
        "boundaries": bundle["boundaries"] or {},
        "violations": bundle["violations"] or [],
        "assets": bundle["assets"] or {"assets": []},
        "strings": bundle["strings"] or {"strings": []},
        "meta": bundle["meta"] or {},
        "repo_meta": repo_meta or {},
        "projects": (projects_doc or {}).get("projects") or [],
        "href_back": href_back,
    }
    template = _read(_TEMPLATES / "single_project.html")
    css = _read(_STATIC / "atlas.css")
    js = _read(_STATIC / "atlas.js")
    title = project.get("name") or project.get("id") or payload["systems"].get("stack") or "?"
    stack = payload["systems"].get("stack") or project.get("stack") or "?"

    return _stamp(
        template,
        DATA=_safe_json(payload),
        CSS=css,
        JS=js,
        VERSION=html.escape(mercator_version),
        STACK=html.escape(stack),
        TITLE=html.escape(title),
    )


def render_repo_index(
    *,
    bundles: List[dict],
    mercator_version: str,
    schema_version: str,
    repo_meta: Optional[dict] = None,
    projects_doc: Optional[dict] = None,
    repo_edges: Optional[dict] = None,
    repo_boundaries: Optional[dict] = None,
) -> str:
    """Render the multi-project index page.

    Each card links to `atlas/projects/<id>.html` (relative path, written
    by `mercator.render.write_atlas`).
    """
    summaries = []
    for b in bundles:
        proj = b["project"]
        sys_doc = b.get("systems") or {}
        systems = sys_doc.get("systems") or []
        contracts = b.get("contracts") or {}
        violations = b.get("violations") or []
        summaries.append({
            "id": proj["id"],
            "name": proj.get("name") or proj["id"],
            "stack": proj.get("stack"),
            "root": proj.get("root"),
            "category": proj.get("category"),
            "tags": proj.get("tags") or [],
            "systems_count": len(systems),
            "contracts_count": len(contracts),
            "violation_count": len(violations),
            "error_violations": sum(1 for v in violations if v.get("severity") == "error"),
            "href": f"atlas/projects/{proj['id']}.html",
        })
    payload = {
        "mercator_version": mercator_version,
        "schema_version": schema_version,
        "repo_meta": repo_meta or {},
        "projects_doc": projects_doc or {},
        "summaries": summaries,
        "repo_edges": repo_edges or {"edges": []},
        "repo_boundaries": repo_boundaries or None,
    }
    template = _read(_TEMPLATES / "repo_index.html")
    css = _read(_STATIC / "atlas.css")
    js = _read(_STATIC / "repo_index.js")
    return _stamp(
        template,
        DATA=_safe_json(payload),
        CSS=css,
        JS=js,
        VERSION=html.escape(mercator_version),
        PROJECT_COUNT=str(len(summaries)),
    )


# Compatibility shim — for callers that still import `render(...)` directly.
def render(*, systems_doc=None, contracts=None, boundaries_doc=None, violations=None,
           assets_doc=None, strings_doc=None, meta_doc=None,
           mercator_version: str, schema_version: str) -> str:
    return render_single_project(
        bundle={
            "project": {
                "id": "(legacy)", "name": "(legacy)",
                "stack": (systems_doc or {}).get("stack", "?"),
                "root": ".", "category": "lib", "tags": [],
            },
            "systems": systems_doc, "contracts": contracts,
            "boundaries": boundaries_doc, "violations": violations,
            "assets": assets_doc, "strings": strings_doc, "meta": meta_doc,
        },
        mercator_version=mercator_version, schema_version=schema_version,
    )

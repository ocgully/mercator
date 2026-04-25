# Contract surface — `mercator.render.atlas`

**Source tool**: `python_ast_contract`
**Files scanned**: 1
**Public items**: 3

_Last-refresh timestamp is in `.mercator/meta.json`; this file is time-stable._

## Counts by kind

- **Functions** — 3

## Functions

| Name | Signature | File:line |
|------|-----------|-----------|
| `render_single_project` | `def render_single_project(*, bundle: dict, mercator_version: str, schema_version: str, repo_meta: Optional[dict] = None, projects_doc: Op...` | `mercator/render/atlas/__init__.py`:70 |
| `render_repo_index` | `def render_repo_index(*, bundles: List[dict], mercator_version: str, schema_version: str, repo_meta: Optional[dict] = None, projects_doc:...` | `mercator/render/atlas/__init__.py`:119 |
| `render` | `def render(*, systems_doc = None, contracts = None, boundaries_doc = None, violations = None, assets_doc = None, strings_doc = None, meta...` | `mercator/render/atlas/__init__.py`:249 |

## Source-tool note

> Public surface = top-level `def` / `async def` / `class` whose names don't start with '_'. Module-level constants (UPPER_CASE assignments) are included as 'const' items. Only files directly inside the package are scanned; sub-packages are their own systems.

## How agents use this data

Agents should query the CLI for a slice rather than reading this rendered view:

```
mercator query contract mercator.render.atlas          # this data as JSON
mercator query symbol <name>              # resolve symbol defs across workspace
```


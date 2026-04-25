# Contract surface — `mercator.render`

**Source tool**: `python_ast_contract`
**Files scanned**: 6
**Public items**: 9

_Last-refresh timestamp is in `.mercator/meta.json`; this file is time-stable._

## Counts by kind

- **Functions** — 5
- **Constants** — 4

## Functions

| Name | Signature | File:line |
|------|-----------|-----------|
| `write_atlas` | `def write_atlas(repo_root: Path) -> Path` | `mercator/render/__init__.py`:63 |
| `render` | `def render(systems_doc: dict, boundaries_doc: dict) -> str` | `mercator/render/boundaries_md.py`:13 |
| `render` | `def render(doc: dict) -> str` | `mercator/render/contract_md.py`:22 |
| `render` | `def render(systems_doc: dict, boundaries_doc: dict) -> str` | `mercator/render/graph_md.py`:41 |
| `render` | `def render(doc: dict) -> str` | `mercator/render/systems_md.py`:14 |

## Constants

| Name | Signature | File:line |
|------|-----------|-----------|
| `KIND_ORDER` | `KIND_ORDER = ['trait', 'struct', 'enum', 'fn', 'type', 'const', 'static', 'macro', 'mod', 'us` | `mercator/render/contract_md.py`:7 |
| `KIND_LABELS` | `KIND_LABELS = {'fn': 'Functions', 'struct': 'Structs', 'enum': 'Enums', 'trait': 'Traits', 'ty` | `mercator/render/contract_md.py`:8 |
| `MERMAID_NODE_LIMIT` | `MERMAID_NODE_LIMIT = 50` | `mercator/render/graph_md.py`:25 |
| `MERMAID_NODE_LIMIT` | `MERMAID_NODE_LIMIT = 20` | `mercator/render/systems_md.py`:7 |

## Source-tool note

> Public surface = top-level `def` / `async def` / `class` whose names don't start with '_'. Module-level constants (UPPER_CASE assignments) are included as 'const' items. Only files directly inside the package are scanned; sub-packages are their own systems.

## How agents use this data

Agents should query the CLI for a slice rather than reading this rendered view:

```
mercator query contract mercator.render          # this data as JSON
mercator query symbol <name>              # resolve symbol defs across workspace
```


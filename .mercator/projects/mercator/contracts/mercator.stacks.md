# Contract surface — `mercator.stacks`

**Source tool**: `python_ast_contract`
**Files scanned**: 10
**Public items**: 32

_Last-refresh timestamp is in `.mercator/meta.json`; this file is time-stable._

## Counts by kind

- **Functions** — 19
- **Constants** — 13

## Functions

| Name | Signature | File:line |
|------|-----------|-----------|
| `classify` | `def classify(path: Path) -> Optional[str]` | `mercator/stacks/_asset_common.py`:62 |
| `safe_size` | `def safe_size(path: Path) -> Optional[int]` | `mercator/stacks/_asset_common.py`:67 |
| `build_systems` | `def build_systems(project_root: Path) -> dict` | `mercator/stacks/dart.py`:96 |
| `build_assets` | `def build_assets(project_root: Path) -> dict` | `mercator/stacks/dart_assets.py`:166 |
| `build_strings` | `def build_strings(project_root: Path) -> dict` | `mercator/stacks/dart_assets.py`:270 |
| `build_systems` | `def build_systems(project_root: Path) -> dict` | `mercator/stacks/python.py`:355 |
| `find_symbol` | `def find_symbol(project_root: Path, systems_doc: dict, name: str, want_kinds) -> List[dict]` | `mercator/stacks/python.py`:479 |
| `build_contract` | `def build_contract(project_root: Path, system_name: str, manifest_rel: str) -> dict` | `mercator/stacks/python.py`:597 |
| `build_systems` | `def build_systems(project_root: Path) -> dict` | `mercator/stacks/rust.py`:23 |
| `strip_rust_source` | `def strip_rust_source(text: str) -> str` | `mercator/stacks/rust.py`:116 |
| `build_contract` | `def build_contract(project_root: Path, system_name: str, manifest_rel: str) -> dict` | `mercator/stacks/rust.py`:332 |
| `find_symbol` | `def find_symbol(project_root: Path, systems_doc: dict, name: str, want_kinds) -> List[dict]` | `mercator/stacks/rust.py`:387 |
| `build_assets` | `def build_assets(project_root: Path) -> dict` | `mercator/stacks/rust_assets.py`:93 |
| `build_strings` | `def build_strings(project_root: Path) -> dict` | `mercator/stacks/rust_assets.py`:156 |
| `build_systems` | `def build_systems(project_root: Path) -> dict` | `mercator/stacks/ts.py`:309 |
| `build_contract` | `def build_contract(project_root: Path, system_name: str, manifest_rel: str) -> dict` | `mercator/stacks/ts.py`:903 |
| `build_systems` | `def build_systems(project_root: Path) -> dict` | `mercator/stacks/unity.py`:70 |
| `build_assets` | `def build_assets(project_root: Path) -> dict` | `mercator/stacks/unity_assets.py`:51 |
| `build_strings` | `def build_strings(project_root: Path) -> dict` | `mercator/stacks/unity_assets.py`:175 |

## Constants

| Name | Signature | File:line |
|------|-----------|-----------|
| `SKIP_DIRS` | `SKIP_DIRS = {'.dart_tool', 'build', '.pub-cache', 'node_modules', '.git'}` | `mercator/stacks/dart.py`:22 |
| `SKIP_DIRS` | `SKIP_DIRS = dart_stack.SKIP_DIRS` | `mercator/stacks/dart_assets.py`:24 |
| `SKIP_DIRS` | `SKIP_DIRS = {'.git', '.hg', '.svn', '.venv', 'venv', 'env', '.env', '__pycache__', 'build', ` | `mercator/stacks/python.py`:37 |
| `ITEM_RE` | `ITEM_RE = re.compile('^pub\\s+\n        (?:(?:async\|unsafe\|const\|extern(?:\\s+"[^"]*")?\|de` | `mercator/stacks/rust.py`:105 |
| `IDENT_RE` | `IDENT_RE = re.compile('([A-Za-z_][A-Za-z0-9_]*)')` | `mercator/stacks/rust.py`:113 |
| `DEFN_RE` | `DEFN_RE = re.compile('^(?:pub(?:\\([^)]*\\))?\\s+)?\n        (?:(?:async\|unsafe\|const\|exte` | `mercator/stacks/rust.py`:377 |
| `ASSET_DIRS` | `ASSET_DIRS = ('assets', 'res', 'resources', 'static')` | `mercator/stacks/rust_assets.py`:26 |
| `SKIP_DIRS` | `SKIP_DIRS = {'target', '.git', 'node_modules', '.cargo', '.codemap', '.mercator'}` | `mercator/stacks/rust_assets.py`:27 |
| `UI_SETTER_RE` | `UI_SETTER_RE = re.compile('\\.(text\|title\|label\|placeholder\|tooltip\|button\|heading\|caption\|hint` | `mercator/stacks/rust_assets.py`:31 |
| `SKIP_DIRS` | `SKIP_DIRS = {'node_modules', '.git', '.yarn', '.pnpm-store', 'dist', 'build', 'out', 'covera` | `mercator/stacks/ts.py`:43 |
| `META_SUFFIX` | `META_SUFFIX = '.meta'` | `mercator/stacks/unity_assets.py`:32 |
| `PO_MSGID_RE` | `PO_MSGID_RE = re.compile('^\\s*msgid\\s+"(.*)"\\s*$')` | `mercator/stacks/unity_assets.py`:104 |
| `PO_MSGSTR_RE` | `PO_MSGSTR_RE = re.compile('^\\s*msgstr\\s+"(.*)"\\s*$')` | `mercator/stacks/unity_assets.py`:105 |

## Source-tool note

> Public surface = top-level `def` / `async def` / `class` whose names don't start with '_'. Module-level constants (UPPER_CASE assignments) are included as 'const' items. Only files directly inside the package are scanned; sub-packages are their own systems.

## How agents use this data

Agents should query the CLI for a slice rather than reading this rendered view:

```
mercator query contract mercator.stacks          # this data as JSON
mercator query symbol <name>              # resolve symbol defs across workspace
```


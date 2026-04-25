# Contract surface — `mercator`

**Source tool**: `python_ast_contract`
**Files scanned**: 15
**Public items**: 86

_Last-refresh timestamp is in `.mercator/meta.json`; this file is time-stable._

## Counts by kind

- **Functions** — 61
- **Constants** — 25

## Functions

| Name | Signature | File:line |
|------|-----------|-----------|
| `load_path` | `def load_path(path: Path) -> dict` | `mercator/boundaries.py`:63 |
| `load` | `def load(project_root: Path) -> dict` | `mercator/boundaries.py`:98 |
| `evaluate` | `def evaluate(systems_doc: dict, boundaries_doc: dict) -> List[dict]` | `mercator/boundaries.py`:176 |
| `summarise_rules` | `def summarise_rules(systems_doc: dict, boundaries_doc: dict) -> List[dict]` | `mercator/boundaries.py`:229 |
| `has_blocking_violations` | `def has_blocking_violations(violations: List[dict]) -> bool` | `mercator/boundaries.py`:266 |
| `cmd_init` | `def cmd_init(args) -> int` | `mercator/cli.py`:50 |
| `cmd_refresh` | `def cmd_refresh(args) -> int` | `mercator/cli.py`:75 |
| `cmd_query` | `def cmd_query(args) -> int` | `mercator/cli.py`:129 |
| `cmd_diff` | `def cmd_diff(args) -> int` | `mercator/cli.py`:229 |
| `cmd_hooks` | `def cmd_hooks(args) -> int` | `mercator/cli.py`:251 |
| `cmd_migrate` | `def cmd_migrate(args) -> int` | `mercator/cli.py`:280 |
| `cmd_check` | `def cmd_check(args) -> int` | `mercator/cli.py`:308 |
| `cmd_render` | `def cmd_render(args) -> int` | `mercator/cli.py`:395 |
| `cmd_boundaries` | `def cmd_boundaries(args) -> int` | `mercator/cli.py`:440 |
| `cmd_projects` | `def cmd_projects(args) -> int` | `mercator/cli.py`:542 |
| `cmd_atlas` | `def cmd_atlas(args) -> int` | `mercator/cli.py`:571 |
| `cmd_info` | `def cmd_info(args) -> int` | `mercator/cli.py`:591 |
| `main` | `def main(argv = None) -> int` | `mercator/cli.py`:713 |
| `deprecated_main` | `def deprecated_main(argv = None) -> int` | `mercator/cli.py`:724 |
| `detect` | `def detect(project_root: Path) -> str` | `mercator/detect.py`:29 |
| `layer_support` | `def layer_support(stack: str) -> dict` | `mercator/detect.py`:49 |
| `compute_diff` | `def compute_diff(project_root: Path, ref_a: str, ref_b: str) -> dict` | `mercator/diff.py`:255 |
| `render_diff_md` | `def render_diff_md(diff: dict) -> str` | `mercator/diff.py`:331 |
| `install` | `def install(project_root: Path, launcher_path: Optional[Path] = None) -> Path` | `mercator/hooks.py`:86 |
| `uninstall` | `def uninstall(project_root: Path) -> bool` | `mercator/hooks.py`:117 |
| `write` | `def write(project_root: Path, mercator_dir: Path, stack: str) -> None` | `mercator/meta.py`:44 |
| `write_project` | `def write_project(repo_root: Path, project_storage: Path, stack: str) -> None` | `mercator/meta.py`:58 |
| `read` | `def read(mercator_dir: Path) -> dict` | `mercator/meta.py`:73 |
| `migrate` | `def migrate(project_root: Path, *, dry_run: bool = False) -> dict` | `mercator/migrate.py`:32 |
| `find_project_root` | `def find_project_root(start: Optional[Path] = None) -> Path` | `mercator/paths.py`:38 |
| `set_storage_override` | `def set_storage_override(path: Optional[Path]) -> None` | `mercator/paths.py`:62 |
| `mercator_dir` | `def mercator_dir(project_root: Path) -> Path` | `mercator/paths.py`:74 |
| `ensure_mercator_dir` | `def ensure_mercator_dir(project_root: Path) -> Path` | `mercator/paths.py`:98 |
| `project_storage_dir` | `def project_storage_dir(repo_storage: Path, project_id: str) -> Path` | `mercator/paths.py`:107 |
| `ensure_project_storage_dir` | `def ensure_project_storage_dir(repo_storage: Path, project_id: str) -> Path` | `mercator/paths.py`:117 |
| `detect_projects` | `def detect_projects(repo_root: Path, *, max_depth: int = 8) -> dict` | `mercator/projects.py`:338 |
| `write_projects` | `def write_projects(repo_root: Path, mercator_dir: Path) -> dict` | `mercator/projects.py`:424 |
| `load_projects` | `def load_projects(mercator_dir: Path) -> Optional[dict]` | `mercator/projects.py`:436 |
| `resolve_project` | `def resolve_project(repo_root: Path, project_id: Optional[str] = None) -> dict` | `mercator/query.py`:27 |
| `projects` | `def projects(repo_root: Path) -> dict` | `mercator/query.py`:82 |
| `repo_edges` | `def repo_edges(repo_root: Path) -> dict` | `mercator/query.py`:91 |
| `repo_boundaries` | `def repo_boundaries(repo_root: Path) -> dict` | `mercator/query.py`:101 |
| `repo_violations` | `def repo_violations(repo_root: Path) -> dict` | `mercator/query.py`:131 |
| `systems` | `def systems(repo_root: Path, project_id: Optional[str] = None) -> dict` | `mercator/query.py`:161 |
| `deps` | `def deps(repo_root: Path, target: str, project_id: Optional[str] = None) -> dict` | `mercator/query.py`:165 |
| `contract` | `def contract(repo_root: Path, system_name: str, project_id: Optional[str] = None) -> dict` | `mercator/query.py`:185 |
| `symbol` | `def symbol(repo_root: Path, name: str, kinds: Union[str, Set[str]] = 'any', project_id: Optional[str] = None) -> dict` | `mercator/query.py`:196 |
| `touches` | `def touches(repo_root: Path, file_path: str, project_id: Optional[str] = None) -> dict` | `mercator/query.py`:225 |
| `system` | `def system(repo_root: Path, name: str, project_id: Optional[str] = None) -> dict` | `mercator/query.py`:321 |
| `boundaries` | `def boundaries(repo_root: Path, project_id: Optional[str] = None) -> dict` | `mercator/query.py`:342 |
| `violations` | `def violations(repo_root: Path, project_id: Optional[str] = None) -> dict` | `mercator/query.py`:366 |
| `refresh_one_project` | `def refresh_one_project(repo_root: Path, repo_storage: Path, project: dict, *, affected: Optional[Set[str]] = None) -> dict` | `mercator/refresh.py`:200 |
| `refresh` | `def refresh(repo_root: Path, *, project_id: Optional[str] = None, affected: Optional[Set[str]] = None) -> dict` | `mercator/refresh.py`:324 |
| `files_to_affected_systems` | `def files_to_affected_systems(repo_root: Path, changed_files: Iterable[str]) -> dict` | `mercator/refresh.py`:396 |
| `load` | `def load(repo_storage: Path) -> dict` | `mercator/repo_boundaries.py`:64 |
| `evaluate` | `def evaluate(projects_doc: dict, repo_edges_doc: dict, repo_boundaries_doc: dict) -> List[dict]` | `mercator/repo_boundaries.py`:177 |
| `summarise_rules` | `def summarise_rules(projects_doc: dict, repo_edges_doc: dict, repo_boundaries_doc: dict) -> List[dict]` | `mercator/repo_boundaries.py`:234 |
| `has_blocking_violations` | `def has_blocking_violations(violations: List[dict]) -> bool` | `mercator/repo_boundaries.py`:268 |
| `compute_edges` | `def compute_edges(repo_root: Path) -> dict` | `mercator/repo_edges.py`:227 |
| `write_edges` | `def write_edges(repo_root: Path) -> Path` | `mercator/repo_edges.py`:313 |
| `load_edges` | `def load_edges(repo_storage: Path) -> Optional[dict]` | `mercator/repo_edges.py`:321 |

## Constants

| Name | Signature | File:line |
|------|-----------|-----------|
| `SCHEMA_VERSION` | `SCHEMA_VERSION = '1'` | `mercator/__init__.py`:15 |
| `SEVERITIES` | `SEVERITIES = ('info', 'warning', 'error')` | `mercator/boundaries.py`:60 |
| `SCAFFOLD_JSON` | `SCAFFOLD_JSON = '{\n  "schema_version": "1",\n\n  "_doc": "Edit this file to declare forbidden s` | `mercator/boundaries.py`:275 |
| `PROJECTS_PATH` | `PROJECTS_PATH = '.mercator/projects.json'` | `mercator/diff.py`:36 |
| `PROJECT_SYSTEMS_TPL` | `PROJECT_SYSTEMS_TPL = '.mercator/projects/{id}/systems.json'` | `mercator/diff.py`:37 |
| `PROJECT_CONTRACT_TPL` | `PROJECT_CONTRACT_TPL = '.mercator/projects/{id}/contracts/{system}.json'` | `mercator/diff.py`:38 |
| `LEGACY_SYSTEMS_PATHS` | `LEGACY_SYSTEMS_PATHS = ('.mercator/systems.json', '.codemap/systems.json')` | `mercator/diff.py`:41 |
| `LEGACY_CONTRACT_DIRS` | `LEGACY_CONTRACT_DIRS = ('.mercator/contracts', '.codemap/contracts')` | `mercator/diff.py`:42 |
| `LEGACY_PROJECT_ID` | `LEGACY_PROJECT_ID = '(legacy)'` | `mercator/diff.py`:45 |
| `MARKER_BEGIN` | `MARKER_BEGIN = '# --- mercator hook (managed; do not edit this block) ---'` | `mercator/hooks.py`:21 |
| `MARKER_END` | `MARKER_END = '# --- /mercator hook ---'` | `mercator/hooks.py`:22 |
| `LEGACY_MARKER_BEGIN` | `LEGACY_MARKER_BEGIN = '# --- codemap hook (managed; do not edit this block) ---'` | `mercator/hooks.py`:27 |
| `LEGACY_MARKER_END` | `LEGACY_MARKER_END = '# --- /codemap hook ---'` | `mercator/hooks.py`:28 |
| `HOOK_BODY` | `HOOK_BODY = '\n# Regenerate affected slices of .mercator/ after each commit.\n# Skip during ` | `mercator/hooks.py`:30 |
| `LEGACY_DIR` | `LEGACY_DIR = '.codemap'` | `mercator/migrate.py`:28 |
| `NEW_DIR` | `NEW_DIR = '.mercator'` | `mercator/migrate.py`:29 |
| `STACK_MARKERS` | `STACK_MARKERS = ('Cargo.toml', 'package.json', 'pyproject.toml', 'setup.py', 'go.mod', 'go.work'` | `mercator/paths.py`:19 |
| `UNITY_DIR_MARKERS` | `UNITY_DIR_MARKERS = ('Assets', 'ProjectSettings', 'Packages')` | `mercator/paths.py`:30 |
| `STORAGE_DIR` | `STORAGE_DIR = '.mercator'` | `mercator/paths.py`:34 |
| `LEGACY_STORAGE_DIR` | `LEGACY_STORAGE_DIR = '.codemap'` | `mercator/paths.py`:35 |
| `codemap_dir` | `codemap_dir = mercator_dir` | `mercator/paths.py`:95 |
| `ensure_codemap_dir` | `ensure_codemap_dir = ensure_mercator_dir` | `mercator/paths.py`:127 |
| `UNITY_MARKERS` | `UNITY_MARKERS = ('Assets', 'ProjectSettings', 'Packages')` | `mercator/projects.py`:97 |
| `SEVERITIES` | `SEVERITIES = ('info', 'warning', 'error')` | `mercator/repo_boundaries.py`:57 |
| `SCAFFOLD_JSON` | `SCAFFOLD_JSON = '{\n  "schema_version": "1",\n\n  "_doc": "Cross-project DMZ rules. Constrains e` | `mercator/repo_boundaries.py`:276 |

## Source-tool note

> Public surface = top-level `def` / `async def` / `class` whose names don't start with '_'. Module-level constants (UPPER_CASE assignments) are included as 'const' items. Only files directly inside the package are scanned; sub-packages are their own systems.

## How agents use this data

Agents should query the CLI for a slice rather than reading this rendered view:

```
mercator query contract mercator          # this data as JSON
mercator query symbol <name>              # resolve symbol defs across workspace
```


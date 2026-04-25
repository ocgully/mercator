# Contract surface — `tests`

**Source tool**: `python_ast_contract`
**Files scanned**: 3
**Public items**: 19

_Last-refresh timestamp is in `.mercator/meta.json`; this file is time-stable._

## Counts by kind

- **Functions** — 19

## Functions

| Name | Signature | File:line |
|------|-----------|-----------|
| `test_single_rust_project_at_root` | `def test_single_rust_project_at_root(tmp_path: Path) -> None` | `tests/test_projects.py`:49 |
| `test_single_python_project_at_root` | `def test_single_python_project_at_root(tmp_path: Path) -> None` | `tests/test_projects.py`:66 |
| `test_multi_project_detection` | `def test_multi_project_detection(tmp_path: Path) -> None` | `tests/test_projects.py`:89 |
| `test_path_convention_categories` | `def test_path_convention_categories(tmp_path: Path) -> None` | `tests/test_projects.py`:105 |
| `test_skip_dirs_not_detected_as_projects` | `def test_skip_dirs_not_detected_as_projects(tmp_path: Path) -> None` | `tests/test_projects.py`:121 |
| `test_include_glob_filters_to_apps_only` | `def test_include_glob_filters_to_apps_only(tmp_path: Path) -> None` | `tests/test_projects.py`:146 |
| `test_exclude_glob_removes_one` | `def test_exclude_glob_removes_one(tmp_path: Path) -> None` | `tests/test_projects.py`:159 |
| `test_per_project_name_and_category_override` | `def test_per_project_name_and_category_override(tmp_path: Path) -> None` | `tests/test_projects.py`:173 |
| `test_id_disambiguation_on_slug_collision` | `def test_id_disambiguation_on_slug_collision(tmp_path: Path) -> None` | `tests/test_projects.py`:197 |
| `test_nested_project_not_detected_inside_outer` | `def test_nested_project_not_detected_inside_outer(tmp_path: Path) -> None` | `tests/test_projects.py`:211 |
| `test_manifest_precedence_rust_wins_over_ts` | `def test_manifest_precedence_rust_wins_over_ts(tmp_path: Path) -> None` | `tests/test_projects.py`:224 |
| `test_slug_handles_weird_paths` | `def test_slug_handles_weird_paths() -> None` | `tests/test_projects.py`:241 |
| `test_empty_repo_no_crash` | `def test_empty_repo_no_crash(tmp_path: Path) -> None` | `tests/test_repo_edges.py`:81 |
| `test_single_project_no_edges` | `def test_single_project_no_edges(tmp_path: Path) -> None` | `tests/test_repo_edges.py`:93 |
| `test_ts_npm_dependency_edge` | `def test_ts_npm_dependency_edge(tmp_path: Path) -> None` | `tests/test_repo_edges.py`:111 |
| `test_python_import_edge` | `def test_python_import_edge(tmp_path: Path) -> None` | `tests/test_repo_edges.py`:145 |
| `test_rust_unmatched_external_dep_dropped` | `def test_rust_unmatched_external_dep_dropped(tmp_path: Path) -> None` | `tests/test_repo_edges.py`:179 |
| `test_cross_stack_name_collision_deterministic` | `def test_cross_stack_name_collision_deterministic(tmp_path: Path) -> None` | `tests/test_repo_edges.py`:200 |
| `test_self_edges_suppressed` | `def test_self_edges_suppressed(tmp_path: Path) -> None` | `tests/test_repo_edges.py`:254 |

## Source-tool note

> Public surface = top-level `def` / `async def` / `class` whose names don't start with '_'. Module-level constants (UPPER_CASE assignments) are included as 'const' items. Only files directly inside the package are scanned; sub-packages are their own systems.

## How agents use this data

Agents should query the CLI for a slice rather than reading this rendered view:

```
mercator query contract tests          # this data as JSON
mercator query symbol <name>              # resolve symbol defs across workspace
```


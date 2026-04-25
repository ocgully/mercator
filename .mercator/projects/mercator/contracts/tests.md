# Contract surface — `tests`

**Source tool**: `python_ast_contract`
**Files scanned**: 7
**Public items**: 87

_Last-refresh timestamp is in `.mercator/meta.json`; this file is time-stable._

## Counts by kind

- **Functions** — 87

## Functions

| Name | Signature | File:line |
|------|-----------|-----------|
| `test_load_ref_state_empty_when_neither_layout_present` | `def test_load_ref_state_empty_when_neither_layout_present(tmp_path: Path) -> None` | `tests/test_diff.py`:102 |
| `test_load_ref_state_nested_layout` | `def test_load_ref_state_nested_layout(tmp_path: Path) -> None` | `tests/test_diff.py`:112 |
| `test_load_ref_state_legacy_mercator_flat_layout` | `def test_load_ref_state_legacy_mercator_flat_layout(tmp_path: Path) -> None` | `tests/test_diff.py`:133 |
| `test_load_ref_state_legacy_codemap_flat_layout` | `def test_load_ref_state_legacy_codemap_flat_layout(tmp_path: Path) -> None` | `tests/test_diff.py`:147 |
| `test_compute_diff_project_added_and_removed` | `def test_compute_diff_project_added_and_removed(tmp_path: Path) -> None` | `tests/test_diff.py`:165 |
| `test_compute_diff_per_project_systems_edges_and_contracts` | `def test_compute_diff_per_project_systems_edges_and_contracts(tmp_path: Path) -> None` | `tests/test_diff.py`:193 |
| `test_compute_diff_skips_unchanged_per_project_entries` | `def test_compute_diff_skips_unchanged_per_project_entries(tmp_path: Path) -> None` | `tests/test_diff.py`:241 |
| `test_compute_diff_cross_boundary_legacy_to_nested` | `def test_compute_diff_cross_boundary_legacy_to_nested(tmp_path: Path) -> None` | `tests/test_diff.py`:267 |
| `test_compute_diff_scoped_system_name_with_slash` | `def test_compute_diff_scoped_system_name_with_slash(tmp_path: Path) -> None` | `tests/test_diff.py`:288 |
| `test_render_diff_md_no_changes` | `def test_render_diff_md_no_changes() -> None` | `tests/test_diff.py`:330 |
| `test_render_diff_md_non_empty` | `def test_render_diff_md_non_empty(tmp_path: Path) -> None` | `tests/test_diff.py`:342 |
| `test_single_rust_project_at_root` | `def test_single_rust_project_at_root(tmp_path: Path) -> None` | `tests/test_projects.py`:49 |
| `test_single_python_project_at_root` | `def test_single_python_project_at_root(tmp_path: Path) -> None` | `tests/test_projects.py`:66 |
| `test_multi_project_detection` | `def test_multi_project_detection(tmp_path: Path) -> None` | `tests/test_projects.py`:89 |
| `test_path_convention_categories` | `def test_path_convention_categories(tmp_path: Path) -> None` | `tests/test_projects.py`:105 |
| `test_skip_dirs_not_detected_as_projects` | `def test_skip_dirs_not_detected_as_projects(tmp_path: Path) -> None` | `tests/test_projects.py`:121 |
| `test_include_glob_filters_to_apps_only` | `def test_include_glob_filters_to_apps_only(tmp_path: Path) -> None` | `tests/test_projects.py`:146 |
| `test_exclude_glob_removes_one` | `def test_exclude_glob_removes_one(tmp_path: Path) -> None` | `tests/test_projects.py`:159 |
| `test_per_project_name_and_category_override` | `def test_per_project_name_and_category_override(tmp_path: Path) -> None` | `tests/test_projects.py`:173 |
| `test_id_disambiguation_on_slug_collision` | `def test_id_disambiguation_on_slug_collision(tmp_path: Path) -> None` | `tests/test_projects.py`:197 |
| `test_nested_projects_both_detected` | `def test_nested_projects_both_detected(tmp_path: Path) -> None` | `tests/test_projects.py`:211 |
| `test_workspace_only_cargo_root_skipped` | `def test_workspace_only_cargo_root_skipped(tmp_path: Path) -> None` | `tests/test_projects.py`:225 |
| `test_workspace_root_with_package_kept` | `def test_workspace_root_with_package_kept(tmp_path: Path) -> None` | `tests/test_projects.py`:241 |
| `test_manifest_precedence_rust_wins_over_ts` | `def test_manifest_precedence_rust_wins_over_ts(tmp_path: Path) -> None` | `tests/test_projects.py`:259 |
| `test_slug_handles_weird_paths` | `def test_slug_handles_weird_paths() -> None` | `tests/test_projects.py`:276 |
| `test_build_systems_flat_layout` | `def test_build_systems_flat_layout(tmp_path: Path) -> None` | `tests/test_python_stack.py`:36 |
| `test_build_systems_src_layout` | `def test_build_systems_src_layout(tmp_path: Path) -> None` | `tests/test_python_stack.py`:46 |
| `test_build_systems_subpackage_detected_as_separate_system` | `def test_build_systems_subpackage_detected_as_separate_system(tmp_path: Path) -> None` | `tests/test_python_stack.py`:56 |
| `test_build_systems_skips_pycache_and_venv` | `def test_build_systems_skips_pycache_and_venv(tmp_path: Path) -> None` | `tests/test_python_stack.py`:67 |
| `test_build_systems_tests_dir_is_detected_deliberately` | `def test_build_systems_tests_dir_is_detected_deliberately(tmp_path: Path) -> None` | `tests/test_python_stack.py`:84 |
| `test_intra_project_absolute_import_edge` | `def test_intra_project_absolute_import_edge(tmp_path: Path) -> None` | `tests/test_python_stack.py`:101 |
| `test_relative_imports_resolve_to_internal_edges` | `def test_relative_imports_resolve_to_internal_edges(tmp_path: Path) -> None` | `tests/test_python_stack.py`:118 |
| `test_external_imports_recorded_not_edges` | `def test_external_imports_recorded_not_edges(tmp_path: Path) -> None` | `tests/test_python_stack.py`:142 |
| `test_contract_function_extracted` | `def test_contract_function_extracted(tmp_path: Path) -> None` | `tests/test_python_stack.py`:177 |
| `test_contract_async_function_extracted` | `def test_contract_async_function_extracted(tmp_path: Path) -> None` | `tests/test_python_stack.py`:188 |
| `test_contract_class_with_bases` | `def test_contract_class_with_bases(tmp_path: Path) -> None` | `tests/test_python_stack.py`:199 |
| `test_contract_excludes_private_and_dunder` | `def test_contract_excludes_private_and_dunder(tmp_path: Path) -> None` | `tests/test_python_stack.py`:215 |
| `test_contract_module_level_const` | `def test_contract_module_level_const(tmp_path: Path) -> None` | `tests/test_python_stack.py`:234 |
| `test_contract_signature_includes_annotations_and_defaults` | `def test_contract_signature_includes_annotations_and_defaults(tmp_path: Path) -> None` | `tests/test_python_stack.py`:251 |
| `test_contract_excludes_subpackage_files` | `def test_contract_excludes_subpackage_files(tmp_path: Path) -> None` | `tests/test_python_stack.py`:268 |
| `test_load_returns_empty_dict_when_file_absent` | `def test_load_returns_empty_dict_when_file_absent(tmp_path: Path) -> None` | `tests/test_repo_boundaries.py`:50 |
| `test_load_raises_on_malformed_json` | `def test_load_raises_on_malformed_json(tmp_path: Path) -> None` | `tests/test_repo_boundaries.py`:56 |
| `test_load_raises_when_top_level_is_not_object` | `def test_load_raises_when_top_level_is_not_object(tmp_path: Path) -> None` | `tests/test_repo_boundaries.py`:64 |
| `test_load_raises_on_missing_required_field` | `def test_load_raises_on_missing_required_field(tmp_path: Path) -> None` | `tests/test_repo_boundaries.py`:72 |
| `test_load_raises_on_unknown_severity` | `def test_load_raises_on_unknown_severity(tmp_path: Path) -> None` | `tests/test_repo_boundaries.py`:85 |
| `test_load_raises_when_categories_not_object` | `def test_load_raises_when_categories_not_object(tmp_path: Path) -> None` | `tests/test_repo_boundaries.py`:103 |
| `test_load_raises_when_boundaries_not_array` | `def test_load_raises_when_boundaries_not_array(tmp_path: Path) -> None` | `tests/test_repo_boundaries.py`:112 |
| `test_selector_exact_id_takes_priority_over_category` | `def test_selector_exact_id_takes_priority_over_category() -> None` | `tests/test_repo_boundaries.py`:125 |
| `test_selector_category_alias_resolution` | `def test_selector_category_alias_resolution() -> None` | `tests/test_repo_boundaries.py`:146 |
| `test_selector_detected_category` | `def test_selector_detected_category() -> None` | `tests/test_repo_boundaries.py`:165 |
| `test_selector_tag_match` | `def test_selector_tag_match() -> None` | `tests/test_repo_boundaries.py`:183 |
| `test_selector_id_glob` | `def test_selector_id_glob() -> None` | `tests/test_repo_boundaries.py`:200 |
| `test_evaluate_fires_on_transitive_path` | `def test_evaluate_fires_on_transitive_path() -> None` | `tests/test_repo_boundaries.py`:226 |
| `test_evaluate_does_not_fire_when_transitive_false_and_only_indirect` | `def test_evaluate_does_not_fire_when_transitive_false_and_only_indirect() -> None` | `tests/test_repo_boundaries.py`:250 |
| `test_evaluate_fires_when_transitive_false_and_direct_edge_exists` | `def test_evaluate_fires_when_transitive_false_and_direct_edge_exists() -> None` | `tests/test_repo_boundaries.py`:267 |
| `test_evaluate_suppresses_self_edges` | `def test_evaluate_suppresses_self_edges() -> None` | `tests/test_repo_boundaries.py`:285 |
| `test_evaluate_returns_empty_when_no_rules` | `def test_evaluate_returns_empty_when_no_rules() -> None` | `tests/test_repo_boundaries.py`:310 |
| `test_summarise_rules_pass_and_fail` | `def test_summarise_rules_pass_and_fail() -> None` | `tests/test_repo_boundaries.py`:320 |
| `test_summarise_rules_empty_doc_returns_empty` | `def test_summarise_rules_empty_doc_returns_empty() -> None` | `tests/test_repo_boundaries.py`:344 |
| `test_has_blocking_violations_true_for_error` | `def test_has_blocking_violations_true_for_error() -> None` | `tests/test_repo_boundaries.py`:352 |
| `test_has_blocking_violations_false_for_warnings_and_info` | `def test_has_blocking_violations_false_for_warnings_and_info() -> None` | `tests/test_repo_boundaries.py`:356 |
| `test_has_blocking_violations_false_for_empty` | `def test_has_blocking_violations_false_for_empty() -> None` | `tests/test_repo_boundaries.py`:363 |
| `test_scaffold_json_is_valid_json` | `def test_scaffold_json_is_valid_json() -> None` | `tests/test_repo_boundaries.py`:371 |
| `test_scaffold_json_round_trips_through_load` | `def test_scaffold_json_round_trips_through_load(tmp_path: Path) -> None` | `tests/test_repo_boundaries.py`:378 |
| `test_empty_repo_no_crash` | `def test_empty_repo_no_crash(tmp_path: Path) -> None` | `tests/test_repo_edges.py`:81 |
| `test_single_project_no_edges` | `def test_single_project_no_edges(tmp_path: Path) -> None` | `tests/test_repo_edges.py`:93 |
| `test_ts_npm_dependency_edge` | `def test_ts_npm_dependency_edge(tmp_path: Path) -> None` | `tests/test_repo_edges.py`:111 |
| `test_python_import_edge` | `def test_python_import_edge(tmp_path: Path) -> None` | `tests/test_repo_edges.py`:145 |
| `test_rust_unmatched_external_dep_dropped` | `def test_rust_unmatched_external_dep_dropped(tmp_path: Path) -> None` | `tests/test_repo_edges.py`:179 |
| `test_cross_stack_name_collision_deterministic` | `def test_cross_stack_name_collision_deterministic(tmp_path: Path) -> None` | `tests/test_repo_edges.py`:200 |
| `test_self_edges_suppressed` | `def test_self_edges_suppressed(tmp_path: Path) -> None` | `tests/test_repo_edges.py`:254 |
| `test_export_function_with_signature` | `def test_export_function_with_signature(tmp_path: Path) -> None` | `tests/test_ts_layer2.py`:40 |
| `test_export_async_function` | `def test_export_async_function(tmp_path: Path) -> None` | `tests/test_ts_layer2.py`:54 |
| `test_export_class_with_extends_and_implements` | `def test_export_class_with_extends_and_implements(tmp_path: Path) -> None` | `tests/test_ts_layer2.py`:67 |
| `test_export_interface` | `def test_export_interface(tmp_path: Path) -> None` | `tests/test_ts_layer2.py`:80 |
| `test_export_type_signature_truncated` | `def test_export_type_signature_truncated(tmp_path: Path) -> None` | `tests/test_ts_layer2.py`:89 |
| `test_export_simple_type_alias` | `def test_export_simple_type_alias(tmp_path: Path) -> None` | `tests/test_ts_layer2.py`:104 |
| `test_export_enum` | `def test_export_enum(tmp_path: Path) -> None` | `tests/test_ts_layer2.py`:114 |
| `test_export_const_let_var` | `def test_export_const_let_var(tmp_path: Path) -> None` | `tests/test_ts_layer2.py`:127 |
| `test_export_default_function_named` | `def test_export_default_function_named(tmp_path: Path) -> None` | `tests/test_ts_layer2.py`:144 |
| `test_export_named_re_export_with_alias` | `def test_export_named_re_export_with_alias(tmp_path: Path) -> None` | `tests/test_ts_layer2.py`:157 |
| `test_export_star_from` | `def test_export_star_from(tmp_path: Path) -> None` | `tests/test_ts_layer2.py`:166 |
| `test_underscore_and_unexported_not_extracted` | `def test_underscore_and_unexported_not_extracted(tmp_path: Path) -> None` | `tests/test_ts_layer2.py`:179 |
| `test_dts_test_spec_files_skipped` | `def test_dts_test_spec_files_skipped(tmp_path: Path) -> None` | `tests/test_ts_layer2.py`:198 |
| `test_skip_dirs_excluded` | `def test_skip_dirs_excluded(tmp_path: Path) -> None` | `tests/test_ts_layer2.py`:215 |
| `test_string_literals_dont_leak_as_exports` | `def test_string_literals_dont_leak_as_exports(tmp_path: Path) -> None` | `tests/test_ts_layer2.py`:232 |
| `test_export_inside_block_comment_skipped` | `def test_export_inside_block_comment_skipped(tmp_path: Path) -> None` | `tests/test_ts_layer2.py`:245 |

## Source-tool note

> Public surface = top-level `def` / `async def` / `class` whose names don't start with '_'. Module-level constants (UPPER_CASE assignments) are included as 'const' items. Only files directly inside the package are scanned; sub-packages are their own systems.

## How agents use this data

Agents should query the CLI for a slice rather than reading this rendered view:

```
mercator query contract tests          # this data as JSON
mercator query symbol <name>              # resolve symbol defs across workspace
```


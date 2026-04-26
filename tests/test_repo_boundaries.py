"""Tests for codeatlas.repo_boundaries — repo-level (cross-project) DMZ rules."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from codeatlas.repo_boundaries import (
    SCAFFOLD_JSON,
    evaluate,
    has_blocking_violations,
    load,
    summarise_rules,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _projects_doc(*projects: dict) -> dict:
    return {"schema_version": "1", "projects": list(projects)}


def _proj(pid: str, category: str = "lib", tags=None) -> dict:
    return {
        "id": pid,
        "category": category,
        "tags": list(tags or []),
    }


def _edges_doc(*edges) -> dict:
    return {
        "schema_version": "1",
        "edges": [{"from": a, "to": b} for (a, b) in edges],
    }


# ---------------------------------------------------------------------------
# load()
# ---------------------------------------------------------------------------

def test_load_returns_empty_dict_when_file_absent(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    assert load(storage) == {}


def test_load_raises_on_malformed_json(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    _write(storage / "repo-boundaries.json", "{not json")
    with pytest.raises(ValueError, match="malformed"):
        load(storage)


def test_load_raises_when_top_level_is_not_object(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    _write(storage / "repo-boundaries.json", "[1, 2, 3]")
    with pytest.raises(ValueError, match="JSON object"):
        load(storage)


def test_load_raises_on_missing_required_field(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    doc = {
        "boundaries": [
            {"name": "incomplete", "from": "app"},  # no `not_to`
        ],
    }
    _write(storage / "repo-boundaries.json", json.dumps(doc))
    with pytest.raises(ValueError, match=r"missing field `not_to`"):
        load(storage)


def test_load_raises_on_unknown_severity(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    doc = {
        "boundaries": [
            {
                "name": "bad-sev",
                "from": "app",
                "not_to": "infra",
                "severity": "critical",  # not allowed
            }
        ]
    }
    _write(storage / "repo-boundaries.json", json.dumps(doc))
    with pytest.raises(ValueError, match="severity"):
        load(storage)


def test_load_raises_when_categories_not_object(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    doc = {"categories": ["frontend"]}
    _write(storage / "repo-boundaries.json", json.dumps(doc))
    with pytest.raises(ValueError, match="`categories`"):
        load(storage)


def test_load_raises_when_boundaries_not_array(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    doc = {"boundaries": {"name": "x"}}
    _write(storage / "repo-boundaries.json", json.dumps(doc))
    with pytest.raises(ValueError, match="`boundaries`"):
        load(storage)


# ---------------------------------------------------------------------------
# Selector resolution priority (via evaluate / summarise_rules)
# ---------------------------------------------------------------------------

def test_selector_exact_id_takes_priority_over_category() -> None:
    # A project id == "app" exists. Selector "app" should resolve to that
    # exact id, NOT to all projects with category=app.
    projects = _projects_doc(
        _proj("app", category="app"),
        _proj("other-app", category="app"),
        _proj("infra-1", category="infra"),
    )
    edges = _edges_doc(("app", "infra-1"), ("other-app", "infra-1"))
    rules = {
        "boundaries": [
            {"name": "no-infra", "from": "app", "not_to": "infra",
             "transitive": False},
        ],
    }
    out = evaluate(projects, edges, rules)
    # Only "app" (exact id match), not "other-app".
    froms = sorted({v["from_project"] for v in out})
    assert froms == ["app"]


def test_selector_category_alias_resolution() -> None:
    projects = _projects_doc(
        _proj("a-1", category="app"),
        _proj("a-2", category="tool"),
        _proj("infra-1", category="infra"),
    )
    edges = _edges_doc(("a-1", "infra-1"), ("a-2", "infra-1"))
    rules = {
        "categories": {"frontend": ["app", "tool"]},
        "boundaries": [
            {"name": "no-infra", "from": "frontend", "not_to": "infra",
             "transitive": False},
        ],
    }
    out = evaluate(projects, edges, rules)
    froms = sorted({v["from_project"] for v in out})
    assert froms == ["a-1", "a-2"]


def test_selector_detected_category() -> None:
    projects = _projects_doc(
        _proj("svc-1", category="service"),
        _proj("svc-2", category="service"),
        _proj("infra-1", category="infra"),
    )
    edges = _edges_doc(("svc-1", "infra-1"))
    rules = {
        "boundaries": [
            {"name": "no-direct", "from": "service", "not_to": "infra",
             "transitive": False},
        ],
    }
    out = evaluate(projects, edges, rules)
    assert len(out) == 1
    assert out[0]["from_project"] == "svc-1"


def test_selector_tag_match() -> None:
    projects = _projects_doc(
        _proj("a", category="app", tags=["public"]),
        _proj("b", category="app", tags=["internal"]),
        _proj("c", category="infra"),
    )
    edges = _edges_doc(("a", "c"), ("b", "c"))
    rules = {
        "boundaries": [
            {"name": "public-isolated", "from": "public", "not_to": "infra",
             "transitive": False},
        ],
    }
    out = evaluate(projects, edges, rules)
    assert {v["from_project"] for v in out} == {"a"}


def test_selector_id_glob() -> None:
    projects = _projects_doc(
        _proj("apps-web", category="app"),
        _proj("apps-cli", category="app"),
        _proj("services-api", category="service"),
        _proj("infra-1", category="infra"),
    )
    edges = _edges_doc(
        ("apps-web", "infra-1"),
        ("apps-cli", "infra-1"),
        ("services-api", "infra-1"),
    )
    rules = {
        "boundaries": [
            {"name": "apps-only", "from": "apps-*", "not_to": "infra",
             "transitive": False},
        ],
    }
    out = evaluate(projects, edges, rules)
    assert {v["from_project"] for v in out} == {"apps-web", "apps-cli"}


# ---------------------------------------------------------------------------
# evaluate() — transitive vs direct, self-edges
# ---------------------------------------------------------------------------

def test_evaluate_fires_on_transitive_path() -> None:
    # A → B → C; rule "A must not reach C" with transitive=true.
    projects = _projects_doc(
        _proj("A", category="app"),
        _proj("B", category="service"),
        _proj("C", category="infra"),
    )
    edges = _edges_doc(("A", "B"), ("B", "C"))
    rules = {
        "boundaries": [
            {"name": "isolate-app-from-infra", "from": "A", "not_to": "C",
             "transitive": True},
        ],
    }
    out = evaluate(projects, edges, rules)
    assert len(out) == 1
    v = out[0]
    assert v["from_project"] == "A"
    assert v["to_project"] == "C"
    assert v["path"] == ["A", "B", "C"]
    assert v["direct_edge"] is False
    assert v["scope"] == "repo"


def test_evaluate_does_not_fire_when_transitive_false_and_only_indirect() -> None:
    projects = _projects_doc(
        _proj("A", category="app"),
        _proj("B", category="service"),
        _proj("C", category="infra"),
    )
    edges = _edges_doc(("A", "B"), ("B", "C"))
    rules = {
        "boundaries": [
            {"name": "no-direct", "from": "A", "not_to": "C",
             "transitive": False},
        ],
    }
    out = evaluate(projects, edges, rules)
    assert out == []


def test_evaluate_fires_when_transitive_false_and_direct_edge_exists() -> None:
    projects = _projects_doc(
        _proj("A", category="app"),
        _proj("C", category="infra"),
    )
    edges = _edges_doc(("A", "C"))
    rules = {
        "boundaries": [
            {"name": "no-direct", "from": "A", "not_to": "C",
             "transitive": False},
        ],
    }
    out = evaluate(projects, edges, rules)
    assert len(out) == 1
    assert out[0]["direct_edge"] is True
    assert out[0]["path"] == ["A", "C"]


def test_evaluate_suppresses_self_edges() -> None:
    # Selectors that resolve to overlapping sets — same project on each side
    # must be skipped.
    projects = _projects_doc(
        _proj("A", category="app"),
        _proj("B", category="app"),
    )
    # Edge from A→A is nonsensical, but ensure the selector pair (app, app)
    # doesn't trip on src==dst even if a path technically loops.
    edges = _edges_doc(("A", "B"), ("B", "A"))
    rules = {
        "boundaries": [
            {"name": "self", "from": "app", "not_to": "app",
             "transitive": True},
        ],
    }
    out = evaluate(projects, edges, rules)
    pairs = {(v["from_project"], v["to_project"]) for v in out}
    assert (("A", "A") in pairs) is False
    assert (("B", "B") in pairs) is False
    # Cross-pairs are valid (A→B and B→A both reachable).
    assert ("A", "B") in pairs
    assert ("B", "A") in pairs


def test_evaluate_returns_empty_when_no_rules() -> None:
    projects = _projects_doc(_proj("A"))
    edges = _edges_doc()
    assert evaluate(projects, edges, {}) == []


# ---------------------------------------------------------------------------
# summarise_rules()
# ---------------------------------------------------------------------------

def test_summarise_rules_pass_and_fail() -> None:
    projects = _projects_doc(
        _proj("A", category="app"),
        _proj("C", category="infra"),
        _proj("D", category="docs"),
    )
    edges = _edges_doc(("A", "C"))
    rules = {
        "boundaries": [
            {"name": "fails", "from": "A", "not_to": "C",
             "transitive": False, "severity": "error"},
            {"name": "passes", "from": "A", "not_to": "D",
             "transitive": False, "severity": "warning"},
        ],
    }
    summary = summarise_rules(projects, edges, rules)
    by_name = {s["name"]: s for s in summary}
    assert by_name["fails"]["status"] == "fail"
    assert by_name["fails"]["violation_count"] == 1
    assert by_name["fails"]["severity"] == "error"
    assert by_name["passes"]["status"] == "pass"
    assert by_name["passes"]["violation_count"] == 0


def test_summarise_rules_empty_doc_returns_empty() -> None:
    assert summarise_rules(_projects_doc(), _edges_doc(), {}) == []


# ---------------------------------------------------------------------------
# has_blocking_violations()
# ---------------------------------------------------------------------------

def test_has_blocking_violations_true_for_error() -> None:
    assert has_blocking_violations([{"severity": "error"}]) is True


def test_has_blocking_violations_false_for_warnings_and_info() -> None:
    assert has_blocking_violations([
        {"severity": "warning"},
        {"severity": "info"},
    ]) is False


def test_has_blocking_violations_false_for_empty() -> None:
    assert has_blocking_violations([]) is False


# ---------------------------------------------------------------------------
# SCAFFOLD_JSON validity
# ---------------------------------------------------------------------------

def test_scaffold_json_is_valid_json() -> None:
    doc = json.loads(SCAFFOLD_JSON)
    assert isinstance(doc, dict)
    assert doc.get("schema_version") == "1"
    assert isinstance(doc.get("boundaries"), list)


def test_scaffold_json_round_trips_through_load(tmp_path: Path) -> None:
    # The scaffold has `_doc` fields for human guidance — those must NOT
    # break load() validation.
    storage = tmp_path / "storage"
    storage.mkdir()
    _write(storage / "repo-boundaries.json", SCAFFOLD_JSON)

    doc = load(storage)
    assert isinstance(doc, dict)
    assert doc.get("schema_version") == "1"
    assert len(doc.get("boundaries", [])) >= 1
    # The example rule is still present.
    rule = doc["boundaries"][0]
    assert rule["from"] == "app"
    assert rule["not_to"] == "infra"

"""Render `.codeatlas/boundaries.md` — human-readable DMZ rule listing.

Per-rule pass/fail + resolved system sets. Intended for humans reviewing the
contract; the authoritative source is `.codeatlas/boundaries.json`.
"""
from __future__ import annotations

from typing import List

from codeatlas import boundaries as boundaries_mod


def render(systems_doc: dict, boundaries_doc: dict) -> str:
    lines: List[str] = [
        "# CodeAtlas — Boundaries (DMZ rules)",
        "",
        "Forbidden system-to-system edges declared in `.codeatlas/boundaries.json`.",
        "This file regenerates on every `codeatlas refresh` / `codeatlas render`.",
        "",
        "_Authoritative source: `.codeatlas/boundaries.json`. Edit that, not this file._",
        "",
    ]

    if not boundaries_doc:
        lines += [
            "## No boundaries configured",
            "",
            "Run `codeatlas boundaries init` to scaffold a `.codeatlas/boundaries.json`",
            "with examples and inline schema comments.",
            "",
        ]
        return "\n".join(lines) + "\n"

    rules = boundaries_mod.summarise_rules(systems_doc, boundaries_doc)
    violations = boundaries_mod.evaluate(systems_doc, boundaries_doc)

    err_n = sum(1 for v in violations if v["severity"] == "error")
    warn_n = sum(1 for v in violations if v["severity"] == "warning")
    info_n = sum(1 for v in violations if v["severity"] == "info")

    lines += [
        f"## Summary — {len(rules)} rule(s), {len(violations)} violation(s)",
        "",
        f"- **Errors**: {err_n}  (`codeatlas check` will fail CI if > 0)",
        f"- **Warnings**: {warn_n}",
        f"- **Infos**: {info_n}",
        "",
    ]

    # Layers section.
    layers = boundaries_doc.get("layers") or {}
    if layers:
        lines += ["## Layers", "",
                  "| Layer | Matches |", "|-------|---------|"]
        for name, selectors in sorted(layers.items()):
            if name == "_doc":
                continue
            lines.append(f"| `{name}` | {', '.join(f'`{s}`' for s in selectors)} |")
        lines.append("")

    # Per-rule table.
    lines += ["## Rules", "",
              "| Status | Severity | Rule | From → Not-To | Resolved From | Resolved Not-To | Violations |",
              "|--------|----------|------|---------------|---------------|-----------------|------------|"]
    for r in rules:
        badge = "✅" if r["status"] == "pass" else "❌"
        from_label = f"`{r['from_selector']}`"
        not_to_label = f"`{r['not_to_selector']}`"
        resolved_from = ", ".join(f"`{n}`" for n in r["resolved_from"][:3])
        if len(r["resolved_from"]) > 3:
            resolved_from += f" (+{len(r['resolved_from']) - 3})"
        resolved_not_to = ", ".join(f"`{n}`" for n in r["resolved_not_to"][:3])
        if len(r["resolved_not_to"]) > 3:
            resolved_not_to += f" (+{len(r['resolved_not_to']) - 3})"
        lines.append(
            f"| {badge} | {r['severity']} | {r['name']} | {from_label} → {not_to_label} "
            f"| {resolved_from or '—'} | {resolved_not_to or '—'} | {r['violation_count']} |"
        )
    lines.append("")

    # Violations detail.
    if violations:
        lines += ["## Violations (current)", ""]
        for v in violations:
            arrow = " → ".join(f"`{p}`" for p in v["path"])
            kind = "direct" if v["direct_edge"] else "transitive"
            lines += [
                f"### {v['severity'].upper()} — {v['rule_name']}",
                "",
                f"**Path ({kind})**: {arrow}",
                "",
            ]
            if v.get("rationale"):
                lines += [f"_Rationale_: {v['rationale']}", ""]
    else:
        lines += ["## Violations", "", "✅ None.", ""]

    # Rationales section for passing rules too — keeps the *why* visible.
    if any(r["rationale"] for r in rules):
        lines += ["## Rule rationales", ""]
        for r in rules:
            if r.get("rationale"):
                lines.append(f"- **{r['name']}** — {r['rationale']}")
        lines.append("")

    lines += [
        "## How to change the rules",
        "",
        "1. Edit `.codeatlas/boundaries.json` — add / remove rules or tweak selectors",
        "2. `codeatlas boundaries validate` — check for typos (empty selector resolutions)",
        "3. `codeatlas check` — see which rules pass or fail",
        "4. `codeatlas render` — regenerate this view (also runs on every `codeatlas refresh`)",
        "",
    ]
    return "\n".join(lines) + "\n"

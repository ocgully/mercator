# mercator

A layered, AI-friendly codemap CLI. Produces structured views of a project's
code (systems → contracts → symbols → assets) under `.mercator/`, and — more
importantly — exposes a **query API** that agents use to pull minimal,
typed slices on demand instead of reading whole MD files.

> **Renamed from `codemap`** (April 2026). Honours Gerardus Mercator, who
> published the first book to use "atlas" as the term for a collection of
> maps. Ecosystem rhythm is now **mercator · hopewell · pedia**.
>
> The `codemap` CLI entrypoint still ships for one release cycle as a
> deprecation shim: it prints a stderr warning and forwards to `mercator`.
> Storage directory renamed from `.codemap/` to `.mercator/`; use
> `mercator migrate` to rename it in place.

**Design goals** (in order):

1. **Agents query the CLI; they don't read `.mercator/*.md` files.** A
   targeted `mercator query contract <system>` is orders of magnitude smaller
   than the equivalent rendered MD — less context consumed, faster
   answers, typed output.
2. **Zero-cost to keep current.** A post-commit hook incrementally regenerates
   only the slices affected by a commit. No manual refresh in the loop.
3. **Portable outputs.** No absolute paths in committed JSON; timestamps live
   in `meta.json` only. Safe to commit `.mercator/` and diff structural change
   over time.
4. **Graceful degradation.** If a stack or layer isn't implemented yet, the
   CLI says so with an actionable message. Agents relay the message; they
   don't invent answers.

## Install

```bash
pip install mercator
# or from source:
git clone https://github.com/ocgully/mercator
pip install -e mercator/
```

## Migrating from `codemap`

If your project already has a `.codemap/` directory from the previous
release:

```bash
mercator migrate           # or: mercator migrate --dry-run to preview
```

This renames `.codemap/` → `.mercator/`, rewrites any hard-coded
`.codemap/` references inside the stored JSON/MD files, and updates a
matching entry in `.claudeignore` if present. Idempotent: re-running is a
no-op once migration has completed.

The legacy `codemap` CLI entry point still works for one release cycle —
it prints a one-line stderr deprecation warning and forwards to
`mercator`. Update your hooks / scripts to call `mercator` directly when
convenient; the shim will be removed in the release after next.

## Quick start

From a project root:

```bash
mercator init
```

Then — from any working directory inside the project — query:

```bash
mercator query systems                    # Layer 1, full view
mercator query deps <system>              # who depends on / is depended by
mercator query contract <system>          # Layer 2, public surface (Rust today)
mercator query symbol <name>              # Layer 3 def lookup
mercator query touches <path>             # which system owns this file?
mercator query system <name>              # composite: Layer 1 entry + deps + contract
```

Install the git hook so the map stays current:

```bash
mercator hooks install
```

After each commit, a post-commit hook runs `mercator refresh --files <changed>`
which regenerates only the systems whose files changed. No manual step.

## Boundaries (DMZs / forbidden edges)

Independent of what code currently does, the project declares **what the
code must never do**: view must not reach sim, domain must not reach
infrastructure, and so on. These rules live in `.mercator/boundaries.json`
(committed, architect-authored) and the CLI evaluates them against the
current dep graph every refresh.

```bash
mercator boundaries init         # scaffold a template with inline schema docs
mercator boundaries validate     # check selectors resolve to real systems
mercator query boundaries        # rule list + per-rule pass/fail
mercator query violations        # just the failing ones, with paths
mercator check                   # CI gate — exit 1 on error-severity
```

`boundaries.json` schema (example for a game engine):

```json
{
  "schema_version": "1",
  "layers": {
    "view": ["view_*", "ui_*"],
    "sim":  ["sim_*", "gameplay_*"]
  },
  "boundaries": [
    {
      "name": "View must not reach Simulation",
      "rationale": "Sim is headless / deterministic. View is presentation-only.",
      "severity": "error",
      "from": "view",
      "not_to": "sim",
      "transitive": true
    }
  ]
}
```

Selectors resolve in order: exact system name > layer name (from the `layers`
map) > glob pattern (`fnmatch`-style, e.g. `view_*`). `transitive: true` (the
default) flags paths through any number of intermediate systems; `false`
checks direct edges only.

Severity:
- `info` — factual, no action required
- `warning` — worth reviewing; **does not** fail CI
- `error` — fails `mercator check` (exit 1)

## Human-viewable visual output

`mercator refresh` regenerates two human-readable files alongside the JSON:

- `.mercator/graph.md` — mermaid diagrams of the dep graph and the DMZ overlay (forbidden edges dashed red, violations drawn prominently). Layers appear as mermaid subgraphs so grouping is visible at a glance.
- `.mercator/boundaries.md` — pass/fail table for every rule, resolved system sets, violation paths with rationales.

Both files render natively in GitHub, VS Code's markdown preview, Obsidian,
and any tool that understands mermaid code blocks — no LLM and no extra
install required. They are **derived outputs**: edit `boundaries.json`,
run `mercator refresh`, views regenerate deterministically.

Use `mercator render` to regenerate just the visual views without touching
Layer 1/2 JSON (useful when you've only edited `boundaries.json`).

## What you get under `.mercator/`

```
.mercator/
├── README.md                  pointer to this tool
├── meta.json                  stack, tool versions, last-refresh time, git HEAD
├── systems.json               Layer 1 (all systems + deps)
├── systems.md                 Layer 1 rendered (table + mermaid, ≤20 nodes)
├── contracts/
│   ├── {system}.json          Layer 2 per system (Rust today)
│   └── {system}.md            Layer 2 rendered (humans only)
├── symbols/                   Layer 3 is queried on demand; no persisted index yet
└── assets/                    Layer 4 stub
```

Committing `.mercator/` into the repo is recommended — structural-change
history over time is valuable, and the outputs are deterministic + free of
absolute paths.

## Supported stacks

| Stack | Detection | Layer 1 | Layer 2 | Layer 3 |
|-------|-----------|---------|---------|---------|
| Rust | `Cargo.toml` at root | `cargo metadata` | in-tree `pub`-item scanner | definition lookup (class/struct/trait/fn); refs need rust-analyzer |
| Unity | `Assets/` + `ProjectSettings/` + `Packages/manifest.json` | `.asmdef` files + `.cs` file walk (`.csproj` ignored — editor-generated, untrustworthy) | TBD | TBD |
| Dart/Flutter | `pubspec.yaml` at root | walk for nested `pubspec.yaml` (monorepo-aware) | TBD | TBD |
| TypeScript | `package.json` + `tsconfig.json` project refs | implemented | TBD | TBD |
| Python | `pyproject.toml` / `setup.py` | TBD | TBD | TBD |
| Go | `go.mod` / `go.work` | TBD | TBD | TBD |

Unknown stacks exit with code 3 and a message listing what would unlock support.

## CLI reference

```
mercator init                       Detect stack, init .mercator/, run all implemented layers
mercator refresh                    Full regenerate
mercator refresh --files …          Incremental — regen only systems whose files changed
mercator info                       Project root, detected stack, meta.json
mercator hooks install              Install post-commit git hook
mercator hooks uninstall            Remove it
mercator migrate                    Rename legacy .codemap/ to .mercator/ + rewrite internal refs
mercator render                     Regenerate visual views (.mercator/graph.md + boundaries.md)
mercator check                      CI gate — exit 1 on error-severity DMZ violation
mercator boundaries init            Scaffold a .mercator/boundaries.json template
mercator boundaries validate        Check selectors resolve to real systems
mercator query systems              Full Layer 1 JSON
mercator query deps <system>        Dependents + dependencies
mercator query contract <system>    Layer 2 per-system JSON
mercator query symbol <name>        Layer 3 def lookup (--kind, --kinds)
mercator query touches <path>       Which system owns this file
mercator query system <name>        Layer 1 entry + edges + Layer 2 combined
mercator query boundaries           DMZ rules + per-rule pass/fail
mercator query violations           Just the failing rules, with paths
mercator --help                     Full help
mercator --version                  Version + schema version
```

All `query` output is JSON; agents parse it directly. The `.md` files under
`.mercator/contracts/` and `.mercator/systems.md` exist for humans browsing the
repo and are deterministic (no timestamps) so diffs stay clean.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Usage error |
| 2 | Missing prerequisite (cargo, python, etc.) |
| 3 | Unsupported / unrecognised stack |
| 4 | Internal failure (parser crash, malformed input) |

## Integration with `/bootstrap-from-roadmap`

Every project migrated via `/bootstrap-from-roadmap` runs `mercator init`
during bootstrap. It also installs the post-commit hook. New projects land
with a populated `.mercator/` and an auto-refresh loop wired up.

## Integration with the `mercator-keeper` core agent

The `mercator-keeper` agent (core marketplace, previously `codemap-keeper`)
is the librarian for this data. When other agents need structural context —
"does `view` reach `sim`?", "what's the public surface of `core-engine`?",
"which system owns this file?" — they ask `mercator-keeper`, which invokes
the CLI and returns a structured, cited slice. Agents don't hand-search and
they don't read `.mercator/*.md`. The CLI is the interface.

## Regenerating manually

```bash
mercator refresh                                  # full regen
mercator refresh --files crates/foo/src/lib.rs    # incremental
```

Or delete `.mercator/` and re-run `init`. Outputs are deterministic.

## Known limitations (v1)

- **Rust Layer 2** — line-scans `pub` items at file top level. Misses items
  declared inside inline `mod { ... }` blocks and macro-generated items.
  Higher fidelity is available via `cargo install cargo-public-api` (nightly
  toolchain) — not yet wired into the CLI but on the roadmap.
- **Unity Layer 2/3** — not yet. Pending design of a suitable C# scanner.
- **Dart Layer 2/3** — not yet.
- **Call-site resolution** — `mercator query symbol` returns definitions only.
  Callers / references require rust-analyzer LSP integration, which is a
  future evolution.
- **YAML subset for pubspec** — we parse only the top-level keys and the
  `dependencies:` / `dev_dependencies:` / `dependency_overrides:` blocks.
  Flow-style YAML and anchors in those blocks aren't supported.

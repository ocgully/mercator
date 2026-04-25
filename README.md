# mercator

A layered, AI-friendly codemap CLI for **monorepos and single-project repos**.
Produces structured views of every project in a repo
(projects → systems → contracts → symbols → assets) under `.mercator/`, and —
more importantly — exposes a **query API** that agents use to pull minimal,
typed slices on demand instead of reading whole MD files.

A **project** is a self-contained build unit identified by a stack manifest
(`Cargo.toml`, `package.json`, `pyproject.toml`, `pubspec.yaml`, ...). A repo
has 1..N projects. Mercator detects them automatically, refreshes them in
isolation, and infers implicit cross-project edges (an `apps/web` consuming
`packages/shared` shows up as a real graph edge). The atlas adapts to the
project count: single-project repos get a familiar single-page atlas;
multi-project repos get a repo overview page with a project-graph + cards
linking into per-project atlases.

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

From a repo root:

```bash
mercator init                             # detect projects, refresh all, render atlas
mercator projects list                    # see what was detected
```

Then — from any working directory inside the repo — query:

```bash
mercator query projects                   # repo-level: detected projects
mercator query repo-edges                 # implicit cross-project edges
mercator query systems --project <id>     # Layer 1 for one project (--project optional when N=1)
mercator query deps <system> --project <id>
mercator query contract <system> --project <id>
mercator query symbol <name> --project <id>
mercator query touches <path>             # locates project + system; works repo-wide
mercator query system <name> --project <id>
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

`mercator refresh` regenerates three human-readable artefacts alongside the JSON:

- `.mercator/graph.md` — mermaid diagrams of the dep graph and the DMZ overlay (forbidden edges dashed red, violations drawn prominently). Layers appear as mermaid subgraphs so grouping is visible at a glance.
- `.mercator/boundaries.md` — pass/fail table for every rule, resolved system sets, violation paths with rationales.
- `.mercator/atlas.html` — a single-file interactive **code atlas** (think "modern doxygen"): searchable systems/symbols, per-system dep subgraphs, DMZ overlay, assets/strings browsers, and a **query console** that builds the exact `mercator query ...` invocation each view maps to. Double-click to open — no server, no build step.

Markdown files render natively in GitHub, VS Code's markdown preview, Obsidian,
and any tool that understands mermaid code blocks. The atlas opens in any
browser from a `file://` URL (Mermaid is loaded from a CDN, with a graceful
fallback to source when offline). All three are **derived outputs**: edit
`boundaries.json`, run `mercator refresh`, views regenerate deterministically.

Use `mercator render` to regenerate just the visual views without touching
Layer 1/2 JSON (useful when you've only edited `boundaries.json`).
Use `mercator atlas` to regenerate only the atlas; `--open` also opens it in
your default browser.

## What you get under `.mercator/`

```
.mercator/
├── projects.json              detected projects (auto, source of truth for layout)
├── repo-edges.json            implicit cross-project edges
├── repo.toml                  optional overrides (include/exclude/per-project tags)
├── meta.json                  repo-level: schema, generated_at, git HEAD
├── atlas.html                 interactive code atlas (entry point)
├── atlas/
│   └── projects/
│       └── {id}.html          per-project atlas (multi-project repos only)
└── projects/
    └── {id}/                  one slot per detected project
        ├── meta.json          stack, tool versions, last refresh, git HEAD
        ├── systems.json       Layer 1 (all systems + deps)
        ├── systems.md         Layer 1 rendered (humans)
        ├── contracts/
        │   ├── {system}.json  Layer 2 per system
        │   └── {system}.md    Layer 2 rendered
        ├── boundaries.json    user-authored DMZ rules (optional)
        ├── boundaries.md      pass/fail table (humans)
        ├── graph.md           dependency + DMZ mermaid diagrams (humans)
        ├── assets.json        Layer 4
        └── strings.json       Layer 4
```

The layout is identical for single-project and multi-project repos — the
atlas decides how to render based on `projects.json`. A single-project repo
gets the per-project atlas at `atlas.html`; a multi-project repo gets the
repo overview there, with per-project pages under `atlas/projects/<id>.html`.

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

## Continuous integration — `mercator check` as a CI gate

Wiring `mercator check` into CI catches DMZ violations and structural drift
at PR time, before they soak up reviewer attention. It complements (not
replaces) type-check and test: those tell you the code runs; `mercator check`
tells you the code respects the architecture you declared in
`boundaries.json`.

The bare-minimum CI step is one line:

```yaml
- run: pip install "mercator>=0.5,<1" && mercator init && mercator check
```

For a richer setup — caching `.mercator/` between runs, uploading a JSON
violations report as an artifact, and posting an optional PR comment summary
— see the example workflow at
[`.github/workflows/mercator-check.yml`](.github/workflows/mercator-check.yml).
It's under 80 lines and intended to be copied as-is or trimmed.

`mercator check` exits non-zero only on `error`-severity violations; see the
[Exit codes](#exit-codes) table above for the full mapping. For repos with
multiple projects, all are checked by default; pass `--project <id>` to scope
to one.

## CLI reference

Repo-level (no `--project` needed):

```
mercator init                       Detect projects, refresh all, render atlas
mercator refresh                    Full regenerate (every project)
mercator refresh --project <id>     Refresh one project
mercator refresh --files …          Incremental — auto-attribute files to projects
mercator projects list              Show detected projects
mercator projects detect            Re-run project detection (write projects.json)
mercator query projects             Repo-level project manifest as JSON
mercator query repo-edges           Implicit cross-project edges
mercator query touches <path>       Which project + system owns this file
mercator atlas [--open]             Regenerate `.mercator/atlas.html`
mercator render                     Regenerate visual views (graph.md, boundaries.md, atlas)
mercator check                      CI gate — exit 1 on error-severity DMZ violation across ALL projects
mercator info                       Repo root, detected stack(s), meta.json
mercator hooks install              Install post-commit git hook
mercator hooks uninstall            Remove it
mercator migrate                    Rename legacy `.codemap/` to `.mercator/`
```

Project-scoped (`--project <id>` is required when the repo has >1 project):

```
mercator query systems              Full Layer 1 JSON
mercator query deps <system>        Dependents + dependencies
mercator query contract <system>    Layer 2 per-system JSON
mercator query symbol <name>        Layer 3 def lookup (--kind, --kinds)
mercator query system <name>        Layer 1 entry + edges + Layer 2 combined
mercator query boundaries           DMZ rules + per-rule pass/fail
mercator query violations           Just the failing rules, with paths
mercator query assets               Layer 4 asset inventory (--system, --asset-kind)
mercator query strings              Layer 4 user-facing strings (--system, --key, --file)
mercator boundaries init            Scaffold this project's boundaries.json
mercator boundaries validate        Check selectors resolve to real systems
```

Global flags:

```
--project-root <path>               Override repo-root detection
--storage-dir <path>                Redirect .mercator/ storage (analyse a project without writing inside it)
--version                           Version + schema version
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

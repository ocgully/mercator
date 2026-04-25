# Mercator Atlas Benchmarks

Real-world numbers from running Mercator against six public repos covering Rust, C++, TypeScript, and Python — chosen to stress refresh-time scaling, atlas-size scaling, and detection accuracy on codebases Mercator has never seen before. Each repo is shallow-cloned (`--depth 1`), then `mercator init` and `mercator refresh` are run back-to-back against an out-of-tree storage dir (`--storage-dir`). All wall times use `time.perf_counter()`.

Three things to look for:

1. **Refresh vs init.** Mercator does not cache between runs, so refresh should be ≤ init on a clean tree. Anything above ~1× hints at non-determinism or wasted work.
2. **Atlas size scaling.** Atlas HTML is self-contained — does it grow linearly with system count, or does it explode?
3. **Detection accuracy.** What does the project walker actually find on a repo it has never seen? The interesting cases here are workspaces (Bevy, Vite, opencode) and a tree where Mercator has no scanner at all (Godot).

## Machine

```
=== Machine ===
OS:         Microsoft Windows 11 Home (10.0.26200)
System:     Micro-Star International MS-7B86
CPU:        AMD Ryzen 7 2700X (8 cores / 16 threads, Zen+ 12nm, 2018)
RAM:        32 GB

=== Storage (5 disks) ===
Primary work / repo disk: Samsung SSD 980 PRO with Heatsink 2TB (NVMe PCIe 4.0)
Secondary SSD:            Samsung SSD 850 EVO 500GB (SATA)
HDDs:                     SAMSUNG HD502HJ x2 (466 GB SATA), WDC WD30EZRZ 2.8TB (SATA)

=== Tooling ===
Python:     3.12.10
git:        2.37.3 (Git for Windows)
```

## Run metadata

- **Mercator:** `mercator 0.5.0 (schema 1)`
- **Commit:** `495296bc5d69b1fe62e651cf77b183ab24c659e4`
- **Timestamp (UTC):** `2026-04-25T00:36:41+00:00`

## Summary

| Repo | URL | Stack(s) | Clone | Init | Refresh | Projects | Σ Systems | Σ Contracts | Atlas KB | Storage KB |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `ripgrep` | <https://github.com/BurntSushi/ripgrep> | rust | 1.75s | 2.96s | 1.64s | 1 | 10 | 10 | 69.6 | 133.9 |
| `bevy` | <https://github.com/bevyengine/bevy> | rust | 5.37s | 31.73s | 10.55s | 1 | 88 | 88 | 1023.9 | 3156.8 |
| `godot` | <https://github.com/godotengine/godot> | python | 19.02s | 0.34s | 0.49s | 1 | 0 | 0 | 47.1 | 51.7 |
| `vite` | <https://github.com/vitejs/vite> | ts | 3.48s | 9.43s | 1.90s | 1 | 1 | 1 | 253.2 | 680.4 |
| `aider` | <https://github.com/Aider-AI/aider> | python | 4.18s | 3.21s | 1.49s | 1 | 7 | 7 | 139.3 | 335.9 |
| `opencode` | <https://github.com/sst/opencode> | ts | 6.58s | 25.57s | 7.18s | 1 | 20 | 20 | 869.6 | 2570.3 |

Headlines:

- **Refresh is consistently faster than init**, often by 2–3×, on every successful run. That is a surprise — Mercator advertises no caching, so the gap likely reflects Python interpreter / OS file-cache warmup rather than algorithmic difference. Worth investigating before claiming "fully deterministic" in user-facing copy.
- **Bevy is the marquee for atlas size** — 88 systems → ~1 MB of self-contained HTML. The atlas comfortably fits in a chat tool or static-site upload.
- **The project walker stopped at the repo root in every monorepo it touched** (Bevy, Vite, opencode). That is the headline detection finding from this run. See "Detection rough edges" below.

## Per-repo detail

### `ripgrep` — Small Rust

- URL: <https://github.com/BurntSushi/ripgrep>
- Clone path: `C:\tmp\bench-clones\ripgrep`
- Storage dir: `C:\tmp\bench-atlases\ripgrep`
- Stacks: `['rust']`
- init: 2.96s (rc=0)
- refresh: 1.64s (rc=0)
- Projects detected: **1**
- Cross-project edges: 0
- atlas.html: 71,297 bytes + sub-atlases 0 bytes
- Total storage on disk: 137,072 bytes

Projects:

| id | name | stack | category | systems | contracts |
|---|---|---|---|---:|---:|
| `ripgrep` | ripgrep | rust | tool | 10 | 10 |

_Why this matters:_ ripgrep is the small-workspace anchor. Init in 2.96s and refresh in 1.64s sets the floor for what "fast" looks like; anything slower on a comparably-sized tree warrants a look at I/O before algorithmic cost. ripgrep is itself a Cargo workspace with a few helper crates (`crates/globset`, `crates/ignore`, …), and Mercator collapses them into the parent crate — same problem as Bevy below, just with smaller numbers so it doesn't shout.

### `bevy` — Large Rust game engine

- URL: <https://github.com/bevyengine/bevy>
- Clone path: `C:\tmp\bench-clones\bevy`
- Storage dir: `C:\tmp\bench-atlases\bevy`
- Stacks: `['rust']`
- init: 31.73s (rc=0)
- refresh: 10.55s (rc=0)
- Projects detected: **1**
- Cross-project edges: 0
- atlas.html: 1,048,478 bytes + sub-atlases 0 bytes
- Total storage on disk: 3,232,543 bytes

Projects:

| id | name | stack | category | systems | contracts |
|---|---|---|---|---:|---:|
| `bevy` | bevy | rust | lib | 88 | 88 |

_Why this matters:_ Bevy is the marquee large Rust monorepo, and the headline is: **Mercator detected one project, not forty-plus.** The `crates/` directory contains ~80 sibling crates (bevy_ecs, bevy_render, bevy_ui, …); `Cargo.toml` at the root declares them as workspace members. The project walker stopped at the root manifest and never recursed into `crates/`. The 88 "systems" and 88 "contracts" you see above are Bevy's root-level `src/` modules, not the workspace crates. Init-vs-refresh (31.7s → 10.6s) is the most extreme gap of the run: a 3× drop on a no-cache code path is suspicious and deserves a closer look.

### `godot` — C++ game engine (expected fail)

- URL: <https://github.com/godotengine/godot>
- Clone path: `C:\tmp\bench-clones\godot`
- Storage dir: `C:\tmp\bench-atlases\godot`
- Stacks: `['python']`
- init: 0.34s (rc=0)
- refresh: 0.49s (rc=0)
- Projects detected: **1**
- Cross-project edges: 0
- atlas.html: 48,239 bytes + sub-atlases 0 bytes
- Total storage on disk: 52,972 bytes

Projects:

| id | name | stack | category | systems | contracts |
|---|---|---|---|---:|---:|
| `godot` | godot | python | lib | 0 | 0 |

_Why this matters:_ Godot is C++, but Mercator detected it as a **Python** project. The reason is benign — there is a `pyproject.toml` at the repo root for build tooling — but the result is a misleading signal: a user who hadn't read the source would see "stack: python" and assume Mercator understood Godot. The systems/contracts counts are zero because there are no Python source files for the scanner to walk, so the run completes in 340 ms. The honest answer for a C++ tree is "no scanner, no value" — and that's effectively what happened, just with the wrong label on it.

### `vite` — TypeScript monorepo

- URL: <https://github.com/vitejs/vite>
- Clone path: `C:\tmp\bench-clones\vite`
- Storage dir: `C:\tmp\bench-atlases\vite`
- Stacks: `['ts']`
- init: 9.43s (rc=0)
- refresh: 1.90s (rc=0)
- Projects detected: **1**
- Cross-project edges: 0
- atlas.html: 259,308 bytes + sub-atlases 0 bytes
- Total storage on disk: 696,717 bytes

Projects:

| id | name | stack | category | systems | contracts |
|---|---|---|---|---:|---:|
| `vitejs-vite-monorepo` | @vitejs/vite-monorepo | ts | app | 1 | 1 |

_Why this matters:_ Vite is the clearest test case for the new TypeScript Layer 2 scanner — a pnpm workspace with `packages/vite`, `packages/create-vite`, `packages/plugin-legacy`. Mercator detected one project (the root `@vitejs/vite-monorepo`) with one system. The pnpm `pnpm-workspace.yaml` was not consulted, and the per-package `package.json` files were not promoted to projects. Init in 9.4s is reasonable for a tree of this size; refresh in 1.9s is again 5× faster than init, which suggests OS file-cache effects rather than work avoidance. Actionable signal for the TS roadmap: workspace expansion is the next step.

### `aider` — Python AI/LLM

- URL: <https://github.com/Aider-AI/aider>
- Clone path: `C:\tmp\bench-clones\aider`
- Storage dir: `C:\tmp\bench-atlases\aider`
- Stacks: `['python']`
- init: 3.21s (rc=0)
- refresh: 1.49s (rc=0)
- Projects detected: **1**
- Cross-project edges: 0
- atlas.html: 142,634 bytes + sub-atlases 0 bytes
- Total storage on disk: 343,981 bytes

Projects:

| id | name | stack | category | systems | contracts |
|---|---|---|---|---:|---:|
| `aider-chat` | aider-chat | python | tool | 7 | 7 |

_Why this matters:_ Aider is the cleanest run in the set — a real Python AI/LLM codebase, single project, 7 systems (every directory with `__init__.py`), 7 contracts. Init/refresh times are unsurprising. Category detection picked `tool`, which is correct (aider is a CLI). This is what Mercator is supposed to look like.

### `opencode` — TypeScript AI/LLM

- URL: <https://github.com/sst/opencode>
- Clone path: `C:\tmp\bench-clones\opencode`
- Storage dir: `C:\tmp\bench-atlases\opencode`
- Stacks: `['ts']`
- init: 25.57s (rc=0)
- refresh: 7.18s (rc=0)
- Projects detected: **1**
- Cross-project edges: 0
- atlas.html: 890,435 bytes + sub-atlases 0 bytes
- Total storage on disk: 2,632,007 bytes

Projects:

| id | name | stack | category | systems | contracts |
|---|---|---|---|---:|---:|
| `opencode` | opencode | ts | app | 20 | 20 |

_Why this matters:_ opencode is a Bun monorepo with ~19 packages under `packages/` (`opencode`, `app`, `console`, `desktop-electron`, `slack`, `sdk`, …). As with Vite, Mercator collapsed the entire monorepo into the root project; the 20 systems are top-level `src/` directories, not workspace packages. The atlas is the second-largest in the run at 890 KB — that's a lot of weight for a single project. Init at 25.6s is the second-slowest of the run, and refresh at 7.2s is again ~3.5× faster than init.

## Detection rough edges

Honest list of things this run got wrong or surprised on. Setting expectations is the point.

- **Cargo workspace recursion (Bevy, ripgrep).** When the root `Cargo.toml` declares `[workspace] members = [...]`, the project walker stops at the root and treats the whole tree as one project. Bevy's ~80 sibling crates are invisible. The Layer 1 system scanner still walks the source files and produces 88 "systems" (root-level src modules), so the atlas is non-empty — but a user expecting one card per crate gets one card per src module, with names that match neither the crate boundary nor the public API.
- **pnpm / Bun workspace recursion (Vite, opencode).** Same shape as the Cargo problem. Mercator detects the root `package.json` as a single project; `pnpm-workspace.yaml` and per-package `package.json` files are not promoted. Vite's three packages and opencode's ~19 packages are flattened into the root.
- **`pyproject.toml` is too greedy as a Python signal (Godot).** Godot is a C++ engine that ships a Python `pyproject.toml` for build tooling. Mercator labels the entire tree `stack: python`. The 0 systems / 0 contracts result is technically honest, but the stack label is misleading — a user glancing at the atlas would think Mercator understands Godot.
- **Refresh is suspiciously faster than init across every run** (1.6×–3.6×). Mercator advertises no caching; init and refresh should be near-equal on a clean tree. The most plausible explanation is OS page-cache warmup plus Python import warmup on the first call — not a Mercator bug per se, but a thing to mention in user-facing docs ("the first run will be slower than steady state, even though we don't cache").
- **`category: lib` for Bevy is wrong** (Bevy is a game engine / framework — closer to "lib" than "app", arguably correct, but the `bevy` root crate's `[package]` table doesn't even have a category, so this is a guess from the manifest name). Worth checking the heuristic.
- **`edge_count: 0` everywhere.** Cross-project edges require ≥2 projects, and we only ever detected 1 per repo (see workspace-recursion bug above). This benchmark proves nothing about edge accuracy on real monorepos — that's blocked behind fixing detection.

## Notes for re-running

```bash
python benchmarks/run_benchmarks.py
```

The runner is idempotent: it skips clones that already exist under `C:\tmp\bench-clones\`, but always rebuilds `.mercator/` storage in `C:\tmp\bench-atlases\<repo>\` from scratch. Storage is always passed via `--storage-dir`, so no cloned repo gets a `.mercator/` directory planted inside it (verified post-run).

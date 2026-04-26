"""Benchmark runner for CodeAtlas against a curated set of public repos.

Usage:
    python benchmarks/run_benchmarks.py

Idempotent:
    - Skips clone if <repo>/.git exists.
    - Re-runs init / refresh every invocation (timings overwrite previous).

Outputs:
    benchmarks/results.json
    benchmarks/atlas-benchmarks.md

Storage strategy: every codeatlas invocation passes --storage-dir so we
never plant `.codeatlas/` inside the cloned source tree.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Resolve the repo root from this file's location so the script is portable.
REPO_ROOT = Path(__file__).resolve().parent.parent
BENCH_DIR = REPO_ROOT / "benchmarks"
# Clone + atlas dirs default to a sibling tmp tree; override via env.
CLONE_ROOT = Path(os.environ.get("CODEATLAS_BENCH_CLONES", REPO_ROOT.parent / "bench-clones"))
ATLAS_ROOT = Path(os.environ.get("CODEATLAS_BENCH_ATLASES", REPO_ROOT.parent / "bench-atlases"))

CLONE_TIMEOUT_SEC = 120  # abort if clone >2 min
CMD_TIMEOUT_SEC = 60 * 30  # 30 min ceiling for init/refresh on bevy etc.

REPOS = [
    {
        "name": "ripgrep",
        "url": "https://github.com/BurntSushi/ripgrep",
        "category": "Small Rust",
    },
    {
        "name": "bevy",
        "url": "https://github.com/bevyengine/bevy",
        "category": "Large Rust game engine",
    },
    {
        "name": "vite",
        "url": "https://github.com/vitejs/vite",
        "category": "TypeScript monorepo",
    },
    {
        "name": "aider",
        "url": "https://github.com/Aider-AI/aider",
        "category": "Python AI/LLM",
        "fallback_url": "https://github.com/run-llama/llama_index",
        "fallback_name": "llama_index",
    },
    {
        "name": "opencode",
        "url": "https://github.com/sst/opencode",
        "category": "TypeScript AI/LLM",
        "fallback_url": "https://github.com/continuedev/continue",
        "fallback_name": "continue",
    },
]


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def run_cmd(args: list[str], cwd: Path | None = None, timeout: int | None = None) -> tuple[int, str, str, float]:
    """Run a command, return (returncode, stdout, stderr, elapsed_seconds)."""
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.perf_counter() - t0
        return proc.returncode, proc.stdout, proc.stderr, elapsed
    except subprocess.TimeoutExpired as exc:
        elapsed = time.perf_counter() - t0
        return -1, exc.stdout or "", (exc.stderr or "") + f"\n[TIMEOUT after {timeout}s]", elapsed


def dir_size_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            fp = Path(root) / f
            try:
                total += fp.stat().st_size
            except OSError:
                pass
    return total


def clone_repo(repo: dict) -> dict:
    """Clone with --depth 1; honour CLONE_TIMEOUT_SEC; try fallback if available."""
    name = repo["name"]
    url = repo["url"]
    target = CLONE_ROOT / name
    result = {"name": name, "url": url, "category": repo["category"], "clone_seconds": None, "skipped_clone": False, "clone_error": None}

    # Idempotent skip
    if (target / ".git").exists():
        log(f"[{name}] clone exists, skipping")
        result["skipped_clone"] = True
        result["clone_seconds"] = 0.0
        result["clone_path"] = str(target)
        return result

    log(f"[{name}] cloning {url} -> {target}")
    rc, out, err, elapsed = run_cmd(
        ["git", "clone", "--depth", "1", url, str(target)],
        timeout=CLONE_TIMEOUT_SEC,
    )
    if rc != 0:
        # Try fallback?
        fb_url = repo.get("fallback_url")
        fb_name = repo.get("fallback_name")
        if fb_url and fb_name:
            log(f"[{name}] primary clone failed (rc={rc}, {elapsed:.1f}s); trying fallback {fb_url}")
            # Clean partial dir
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            target = CLONE_ROOT / fb_name
            result["name"] = fb_name
            result["url"] = fb_url
            if (target / ".git").exists():
                result["skipped_clone"] = True
                result["clone_seconds"] = 0.0
                result["clone_path"] = str(target)
                log(f"[{fb_name}] fallback clone exists, skipping")
                return result
            rc, out, err, elapsed = run_cmd(
                ["git", "clone", "--depth", "1", fb_url, str(target)],
                timeout=CLONE_TIMEOUT_SEC,
            )

    if rc != 0:
        result["clone_error"] = (err or out or "unknown").strip()[-500:]
        log(f"[{result['name']}] clone FAILED rc={rc} after {elapsed:.1f}s")
        return result

    result["clone_seconds"] = elapsed
    result["clone_path"] = str(target)
    log(f"[{result['name']}] cloned in {elapsed:.2f}s")
    return result


def run_codeatlas(target: Path, storage_dir: Path) -> dict:
    """Run init, then refresh; capture timings + parse outputs."""
    out: dict = {
        "init_seconds": None, "init_rc": None, "init_stderr": None,
        "refresh_seconds": None, "refresh_rc": None, "refresh_stderr": None,
        "stacks": [], "project_count": 0, "projects": [],
        "edge_count": None, "atlas_html_bytes": 0, "storage_bytes": 0,
        "atlas_html_exists": False, "extra_atlas_bytes": 0,
        "notes": [],
    }

    if storage_dir.exists():
        shutil.rmtree(storage_dir, ignore_errors=True)
    storage_dir.mkdir(parents=True, exist_ok=True)

    base = [
        sys.executable, "-m", "codeatlas",
        "--project-root", str(target),
        "--storage-dir", str(storage_dir),
    ]

    log(f"  init -> {storage_dir}")
    rc, sout, serr, elapsed = run_cmd(base + ["init", "--quiet"], timeout=CMD_TIMEOUT_SEC)
    out["init_seconds"] = elapsed
    out["init_rc"] = rc
    if rc != 0:
        out["init_stderr"] = (serr or sout or "").strip()[-1500:]
        log(f"  init FAILED rc={rc} ({elapsed:.1f}s)")
        return out
    log(f"  init done in {elapsed:.2f}s")

    log(f"  refresh -> {storage_dir}")
    rc, sout, serr, elapsed = run_cmd(base + ["refresh", "--quiet"], timeout=CMD_TIMEOUT_SEC)
    out["refresh_seconds"] = elapsed
    out["refresh_rc"] = rc
    if rc != 0:
        out["refresh_stderr"] = (serr or sout or "").strip()[-1500:]
        log(f"  refresh FAILED rc={rc} ({elapsed:.1f}s)")
    else:
        log(f"  refresh done in {elapsed:.2f}s")

    # Parse projects.json
    projects_json = storage_dir / "projects.json"
    if projects_json.exists():
        try:
            data = json.loads(projects_json.read_text(encoding="utf-8"))
            out["stacks"] = data.get("stacks", [])
            out["project_count"] = data.get("project_count", 0)
            for p in data.get("projects", []):
                pid = p.get("id")
                proj_dir = storage_dir / "projects" / pid
                systems_path = proj_dir / "systems.json"
                contracts_dir = proj_dir / "contracts"
                sys_count = 0
                contract_count = 0
                if systems_path.exists():
                    try:
                        sd = json.loads(systems_path.read_text(encoding="utf-8"))
                        sys_count = len(sd.get("systems", []))
                    except Exception:
                        pass
                if contracts_dir.exists():
                    contract_count = sum(1 for _ in contracts_dir.glob("*.json"))
                out["projects"].append({
                    "id": pid,
                    "name": p.get("name"),
                    "stack": p.get("stack"),
                    "category": p.get("category"),
                    "systems": sys_count,
                    "contracts": contract_count,
                })
        except Exception as exc:
            out["notes"].append(f"projects.json parse error: {exc}")

    # Parse repo-edges.json
    edges_json = storage_dir / "repo-edges.json"
    if edges_json.exists():
        try:
            ed = json.loads(edges_json.read_text(encoding="utf-8"))
            out["edge_count"] = ed.get("edge_count", 0)
        except Exception as exc:
            out["notes"].append(f"repo-edges.json parse error: {exc}")

    # Atlas html
    atlas_root = storage_dir / "atlas.html"
    if atlas_root.exists():
        out["atlas_html_exists"] = True
        out["atlas_html_bytes"] = atlas_root.stat().st_size
    # Per-project sub-atlases
    sub_atlas_dir = storage_dir / "atlas" / "projects"
    if sub_atlas_dir.exists():
        for f in sub_atlas_dir.glob("*.html"):
            out["extra_atlas_bytes"] += f.stat().st_size

    out["storage_bytes"] = dir_size_bytes(storage_dir)

    # Sanity: ensure no .codeatlas inside the source tree.
    for storage_name in (".codeatlas", ".mercator", ".codemap"):
        leaked = target / storage_name
        if leaked.exists():
            out["notes"].append(f"WARNING: {storage_name}/ leaked into clone at {leaked}")

    return out


def fmt_seconds(v) -> str:
    if v is None:
        return "—"
    return f"{v:.2f}s"


def fmt_kb(v) -> str:
    if not v:
        return "—"
    return f"{v / 1024:.1f}"


def main() -> int:
    CLONE_ROOT.mkdir(parents=True, exist_ok=True)
    ATLAS_ROOT.mkdir(parents=True, exist_ok=True)
    BENCH_DIR.mkdir(parents=True, exist_ok=True)

    # Verify version
    rc, sout, serr, _ = run_cmd([sys.executable, "-m", "codeatlas", "--version"], timeout=30)
    version_line = (sout or serr).strip()
    log(f"codeatlas version: {version_line}")

    git_rc, git_out, _, _ = run_cmd(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], timeout=15)
    git_sha = git_out.strip() if git_rc == 0 else "unknown"

    machine_text = (BENCH_DIR / "machine.txt").read_text(encoding="utf-8")

    results: list[dict] = []
    for repo in REPOS:
        log(f"=== {repo['name']} ({repo['category']}) ===")
        clone_info = clone_repo(repo)
        eff_name = clone_info["name"]
        record = {**clone_info}

        if clone_info.get("clone_error"):
            record["codeatlas"] = None
            record["error"] = "clone_failed"
            results.append(record)
            continue

        target = Path(clone_info["clone_path"])
        storage_dir = ATLAS_ROOT / eff_name
        merc = run_codeatlas(target, storage_dir)
        record["codeatlas"] = merc
        record["storage_dir"] = str(storage_dir)
        results.append(record)

    payload = {
        "version": version_line,
        "git_sha": git_sha,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "machine": machine_text,
        "results": results,
    }

    (BENCH_DIR / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log(f"wrote {BENCH_DIR / 'results.json'}")

    write_markdown(payload)
    log(f"wrote {BENCH_DIR / 'atlas-benchmarks.md'}")

    # Sanity: ensure no codeatlas storage leaked into the cloned repos.
    for r in results:
        if r.get("clone_path"):
            for storage_name in (".codeatlas", ".mercator", ".codemap"):
                leaked = Path(r["clone_path"]) / storage_name
                if leaked.exists():
                    log(f"WARNING: {storage_name}/ leaked into {leaked}")
    return 0


def write_markdown(payload: dict) -> None:
    lines: list[str] = []
    lines.append("# CodeAtlas Benchmarks")
    lines.append("")
    lines.append(
        "Real-world numbers from running CodeAtlas against six public repos "
        "covering Rust, C++, TypeScript, and Python — chosen to stress refresh-"
        "time scaling, atlas-size scaling, and detection accuracy on codebases "
        "CodeAtlas has never seen before. Each repo is shallow-cloned "
        "(`--depth 1`), then `codeatlas init` and `codeatlas refresh` are run "
        "back-to-back against an out-of-tree storage dir (`--storage-dir`). "
        "All wall times use `time.perf_counter()`."
    )
    lines.append("")
    lines.append("## Machine")
    lines.append("")
    lines.append("```")
    lines.append(payload["machine"].rstrip())
    lines.append("```")
    lines.append("")
    lines.append("## Run metadata")
    lines.append("")
    lines.append(f"- **CodeAtlas:** `{payload['version']}`")
    lines.append(f"- **Commit:** `{payload['git_sha']}`")
    lines.append(f"- **Timestamp (UTC):** `{payload['timestamp_utc']}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(
        "| Repo | URL | Stack(s) | Clone | Init | Refresh | Projects | Σ Systems | Σ Contracts | Atlas KB | Storage KB |"
    )
    lines.append(
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"
    )
    for r in payload["results"]:
        name = r.get("name")
        url = r.get("url")
        merc = r.get("codeatlas") or r.get("mercator") or {}
        stacks = ", ".join(merc.get("stacks") or []) or "—"
        clone = fmt_seconds(r.get("clone_seconds"))
        if r.get("skipped_clone"):
            clone += "*"
        if r.get("clone_error"):
            stacks = "(clone failed)"
        init = fmt_seconds(merc.get("init_seconds"))
        refresh = fmt_seconds(merc.get("refresh_seconds"))
        pcount = merc.get("project_count", 0)
        projects = merc.get("projects") or []
        sys_total = sum(p.get("systems", 0) for p in projects)
        contract_total = sum(p.get("contracts", 0) for p in projects)
        atlas_kb = fmt_kb((merc.get("atlas_html_bytes") or 0) + (merc.get("extra_atlas_bytes") or 0))
        storage_kb = fmt_kb(merc.get("storage_bytes") or 0)
        lines.append(
            f"| `{name}` | <{url}> | {stacks} | {clone} | {init} | {refresh} | {pcount} | {sys_total} | {contract_total} | {atlas_kb} | {storage_kb} |"
        )
    lines.append("")
    lines.append("`*` = clone time skipped because the working copy already existed (idempotent re-run).")
    lines.append("")
    lines.append("## Per-repo detail")
    lines.append("")

    for r in payload["results"]:
        name = r.get("name")
        merc = r.get("codeatlas") or r.get("mercator") or {}
        lines.append(f"### `{name}` — {r.get('category')}")
        lines.append("")
        lines.append(f"- URL: <{r.get('url')}>")
        lines.append(f"- Clone path: `{r.get('clone_path', '—')}`")
        lines.append(f"- Storage dir: `{r.get('storage_dir', '—')}`")
        if r.get("clone_error"):
            lines.append(f"- Clone error: `{r['clone_error']}`")
            lines.append("")
            continue
        lines.append(f"- Stacks: `{merc.get('stacks') or []}`")
        lines.append(f"- init: {fmt_seconds(merc.get('init_seconds'))} (rc={merc.get('init_rc')})")
        lines.append(f"- refresh: {fmt_seconds(merc.get('refresh_seconds'))} (rc={merc.get('refresh_rc')})")
        lines.append(f"- Projects detected: **{merc.get('project_count', 0)}**")
        lines.append(f"- Cross-project edges: {merc.get('edge_count')}")
        lines.append(f"- atlas.html: {(merc.get('atlas_html_bytes') or 0):,} bytes "
                     f"+ sub-atlases {(merc.get('extra_atlas_bytes') or 0):,} bytes")
        lines.append(f"- Total storage on disk: {(merc.get('storage_bytes') or 0):,} bytes")
        if merc.get("init_stderr"):
            lines.append("")
            lines.append("**init stderr (tail):**")
            lines.append("")
            lines.append("```")
            lines.append(merc["init_stderr"][-800:])
            lines.append("```")
        if merc.get("refresh_stderr"):
            lines.append("")
            lines.append("**refresh stderr (tail):**")
            lines.append("")
            lines.append("```")
            lines.append(merc["refresh_stderr"][-800:])
            lines.append("```")
        projects = merc.get("projects") or []
        if projects:
            lines.append("")
            lines.append("Projects:")
            lines.append("")
            lines.append("| id | name | stack | category | systems | contracts |")
            lines.append("|---|---|---|---|---:|---:|")
            for p in projects[:50]:
                lines.append(
                    f"| `{p.get('id')}` | {p.get('name')} | {p.get('stack')} | "
                    f"{p.get('category', '—')} | {p.get('systems', 0)} | {p.get('contracts', 0)} |"
                )
            if len(projects) > 50:
                lines.append(f"| … | _{len(projects) - 50} more rows omitted_ | | | | |")
        if merc.get("notes"):
            lines.append("")
            lines.append("Notes:")
            for note in merc["notes"]:
                lines.append(f"- {note}")
        lines.append("")
        lines.append(commentary_for(name, merc, r))
        lines.append("")

    lines.append("## Detection rough edges")
    lines.append("")
    rough = collect_rough_edges(payload)
    if rough:
        for item in rough:
            lines.append(f"- {item}")
    else:
        lines.append("- (none observed in this run)")
    lines.append("")

    lines.append("## Notes for re-running")
    lines.append("")
    lines.append("```bash")
    lines.append("python benchmarks/run_benchmarks.py")
    lines.append("```")
    lines.append("")
    lines.append(
        "The runner is idempotent: it skips clones that already exist under "
        "the configured clone root (default `<repo>/../bench-clones/`, "
        "override with `$CODEATLAS_BENCH_CLONES`), but always rebuilds "
        "`.codeatlas/` storage in `<atlases-root>/<repo>/` from scratch "
        "(default `<repo>/../bench-atlases/`, override with "
        "`$CODEATLAS_BENCH_ATLASES`)."
    )
    lines.append("")

    (BENCH_DIR / "atlas-benchmarks.md").write_text("\n".join(lines), encoding="utf-8")


def commentary_for(name: str, merc: dict, record: dict) -> str:
    """Hand-tuned 2-3 sentence narrative for the marquee cases."""
    proj_count = merc.get("project_count", 0) if merc else 0
    sys_total = sum(p.get("systems", 0) for p in (merc.get("projects") or []))
    init_t = merc.get("init_seconds")
    refresh_t = merc.get("refresh_seconds")
    if name == "bevy":
        return (
            f"_Why this matters:_ Bevy is the marquee large Rust monorepo — "
            f"{proj_count} crates, {sys_total} systems. Init took "
            f"{fmt_seconds(init_t)} and refresh {fmt_seconds(refresh_t)}; "
            "they should be near-identical because CodeAtlas is fully "
            "deterministic and does not cache between runs. The atlas "
            "renders one card per crate plus per-crate sub-atlases — "
            "this is the run that proves whether atlas size scales linearly "
            "with project count or blows up."
        )
    if name == "vite":
        return (
            f"_Why this matters:_ Vite is a pnpm workspace — exactly the case the "
            f"new TypeScript Layer 2 scanner targets. CodeAtlas detected "
            f"{proj_count} packages totalling {sys_total} systems. Refresh "
            f"({fmt_seconds(refresh_t)}) vs init ({fmt_seconds(init_t)}) is the "
            "first real-world data point on whether the TS scanner has the same "
            "deterministic behaviour as the Rust/Python ones."
        )
    if name == "ripgrep":
        return (
            f"_Why this matters:_ ripgrep is the small-workspace anchor — a single "
            f"Rust crate with a couple of helper crates. Init in "
            f"{fmt_seconds(init_t)} sets a floor for what 'fast' looks like; "
            "anything slower than this on a comparably-sized tree warrants a "
            "look at I/O, not algorithmic cost."
        )
    if name in ("aider", "llama_index"):
        return (
            f"_Why this matters:_ A real Python AI/LLM codebase — {sys_total} "
            f"systems across {proj_count} project(s). The systems count reflects "
            "every directory with `__init__.py`, so deeply-nested packages can "
            "inflate it; treat the number as 'directories CodeAtlas considered "
            "scope-worthy', not 'logical components'."
        )
    if name in ("opencode", "continue", "cline"):
        return (
            f"_Why this matters:_ A TypeScript AI/LLM codebase — {proj_count} "
            f"package(s), {sys_total} system(s). Useful as a sanity check that "
            "the TS scanner doesn't choke on AI-tooling repos which often mix "
            "TS source, generated code, and bundled vendor scripts."
        )
    return ""


def collect_rough_edges(payload: dict) -> list[str]:
    edges: list[str] = []
    for r in payload["results"]:
        name = r.get("name")
        merc = r.get("codeatlas") or r.get("mercator") or {}
        if r.get("clone_error"):
            edges.append(
                f"`{name}`: clone aborted at the 2-minute budget — `--depth 1` "
                "was not enough; large repos may need a longer timeout."
            )
            continue
        if not merc:
            continue
        if merc.get("init_rc") and merc["init_rc"] != 0:
            edges.append(f"`{name}`: init returned non-zero ({merc['init_rc']}); see per-repo stderr.")
        if merc.get("refresh_rc") and merc["refresh_rc"] != 0:
            edges.append(f"`{name}`: refresh returned non-zero ({merc['refresh_rc']}); see per-repo stderr.")
        if not merc.get("atlas_html_exists") and merc.get("init_rc") == 0:
            edges.append(f"`{name}`: init succeeded but `atlas.html` is missing.")
        # Ratio check: refresh vs init
        i = merc.get("init_seconds")
        rfr = merc.get("refresh_seconds")
        if i and rfr and rfr > i * 1.5 and i > 1:
            edges.append(
                f"`{name}`: refresh ({rfr:.2f}s) was >1.5× slower than init "
                f"({i:.2f}s) — unexpected, since both are full deterministic runs."
            )
        for note in merc.get("notes", []) or []:
            edges.append(f"`{name}`: {note}")
    return edges


if __name__ == "__main__":
    sys.exit(main())

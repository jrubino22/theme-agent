import argparse
import re
import json
from datetime import datetime
from pathlib import Path
import hashlib
from agent.tools.repo_recon import theme_structure_check, top_level_dirs, rg_hits
from agent.tools.cmd import run_allowed
from agent.tools.theme_summary import summarize_theme
from agent.tools.theme_check import run_theme_check
from agent.tools.theme_check_parse import count_theme_check
from agent.tools.planner import create_plan
from agent.tools.plan_policy import validate_plan, PlanError
from agent.tools.patch_apply import apply_plan_ops, ApplyError

def validate_workdir_is_theme(workdir: Path) -> None:
    required = ["sections", "snippets", "templates", "config"]
    missing = [d for d in required if not (workdir / d).is_dir()]
    if missing:
        missing_str = ", ".join(missing)
        raise SystemExit(
            "Workdir does not look like a Shopify theme.\n"
            f"Workdir: {workdir}\n"
            f"Missing required folders: {missing_str}\n\n"
            "Tip: set THEME_DIR to your Horizon theme folder and pass --workdir /work/theme in Docker.\n"
            "Example:\n"
            "  export THEME_DIR=\"$HOME/Desktop/brand-theme\"\n"
            "  docker compose -f docker/docker-compose.yml run --rm theme-agent "
            "python -m agent.cli run --workdir /work/theme --task /app/tasks/test.md --runs-dir /app/runs\n"
        )

def theme_key_from_path(workdir: Path) -> str:
    # Simple stable key: hash of resolved path string
    return hashlib.sha256(str(workdir).encode("utf-8")).hexdigest()[:12]

def load_json(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)

def parse_task_md(task_text: str) -> dict:
    urls = re.findall(r"https?://(?:www\.)?figma\.com/[^\s)]+", task_text)
    return {
        "raw": task_text,
        "figma_links": sorted(set(urls)),
    }

def main():
    parser = argparse.ArgumentParser(prog="theme-agent")
    sub = parser.add_subparsers(dest="cmd", required=True)
    doc_p = sub.add_parser("doctor", help="Verify environment + allowed commands")
    doc_p.add_argument("--workdir", required=True, help="Path to the Horizon theme folder (pure theme code)")

    run_p = sub.add_parser("run", help="Run a single task against a workdir (theme folder)")
    run_p.add_argument("--workdir", required=True, help="Path to the Horizon theme folder (pure theme code)")
    run_p.add_argument("--task", required=True, help="Path to a task markdown file")
    run_p.add_argument("--runs-dir", default="runs", help="Where to store run artifacts")
    run_p.add_argument("--theme-check", action="store_true", help="Run `shopify theme check`")
    run_p.add_argument("--fail-on-regression", action="store_true", help="Exit non-zero if theme check errors/warnings exceed baseline")

    apply_p = sub.add_parser("apply", help="Apply a plan.json to a theme folder (writes files), then verify")
    apply_p.add_argument("--workdir", required=True, help="Path to the Horizon theme folder (pure theme code)")
    apply_p.add_argument("--plan", required=True, help="Path to plan.json (usually from a prior run)")
    apply_p.add_argument("--runs-dir", default="runs", help="Where to store run artifacts")
    apply_p.add_argument("--theme-check", action="store_true", help="Run `shopify theme check` after applying")
    apply_p.add_argument("--fail-on-regression", action="store_true", help="Exit non-zero if errors/warnings exceed baseline")


    args = parser.parse_args()

    if args.cmd == "doctor":
        workdir = Path(args.workdir).expanduser().resolve()
        validate_workdir_is_theme(workdir)

        allowed = [
            ["rg", "--version"],
            ["git", "--version"],
            ["python", "--version"],
            ["shopify", "version"],
        ]
        for c in allowed:
            res = run_allowed(c, cwd=workdir, allowed_prefixes=allowed, timeout_sec=30)
            print(f"$ {' '.join(c)}")
            print(res.stdout.strip() or res.stderr.strip())
        return

    if args.cmd == "apply":
        workdir = Path(args.workdir).expanduser().resolve()
        plan_path = Path(args.plan).expanduser().resolve()
        runs_dir = Path(args.runs_dir).expanduser().resolve()

        # strict allowlist
        allowed = [
            ["shopify", "version"],
            ["shopify", "theme", "check"],
        ]

        if not workdir.exists() or not workdir.is_dir():
            raise SystemExit(f"workdir does not exist or is not a directory: {workdir}")
        if not plan_path.exists() or not plan_path.is_file():
            raise SystemExit(f"plan file does not exist or is not a file: {plan_path}")

        validate_workdir_is_theme(workdir)

        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_dir = runs_dir / f"{run_id}-apply"
        ensure_dir(out_dir)

        # copy inputs to artifacts folder
        raw_plan = json.loads(plan_path.read_text(encoding="utf-8"))

        # policy gate
        try:
            plan = validate_plan(raw_plan)
        except PlanError as e:
            (out_dir / "apply_error.txt").write_text(str(e) + "\n", encoding="utf-8")
            raise SystemExit(f"Plan rejected by policy: {e}")

        (out_dir / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")

        # apply
        try:
            result = apply_plan_ops(plan, workdir)
        except ApplyError as e:
            (out_dir / "apply_error.txt").write_text(str(e) + "\n", encoding="utf-8")
            raise SystemExit(f"Apply failed: {e}")

        apply_meta = {
            "run_id": run_id,
            "workdir": str(workdir),
            "plan_path": str(plan_path),
            "changed_files": result.changed_files,
            "applied_ops": result.applied_ops,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        (out_dir / "apply_meta.json").write_text(json.dumps(apply_meta, indent=2), encoding="utf-8")

        # verify (optional)
        checks = None
        baseline = None
        counts = None
        regression = False
        baseline_path = None

        if args.theme_check:
            checks = run_theme_check(workdir, allowed_prefixes=allowed)
            counts = count_theme_check(checks.get("stdout", ""), checks.get("stderr", ""))
            checks["counts"] = counts

            (out_dir / "theme_check.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
            (out_dir / "theme_check.out.txt").write_text((checks.get("stdout") or "") + "\n", encoding="utf-8")
            (out_dir / "theme_check.err.txt").write_text((checks.get("stderr") or "") + "\n", encoding="utf-8")

            baseline_dir = Path("/app/baselines")
            ensure_dir(baseline_dir)

            theme_key = theme_key_from_path(workdir)
            baseline_path = baseline_dir / f"{theme_key}.json"

            baseline = load_json(baseline_path)
            if baseline is None:
                # If no baseline exists yet, create one now (still safe)
                baseline = {
                    "theme_key": theme_key,
                    "workdir": str(workdir),
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "counts": counts,
                }
                baseline_path.write_text(json.dumps(baseline, indent=2), encoding="utf-8")

            base_counts = baseline.get("counts", {"errors": 0, "warnings": 0})
            delta_errors = counts["errors"] - base_counts.get("errors", 0)
            delta_warnings = counts["warnings"] - base_counts.get("warnings", 0)
            regression = getattr(args, "fail_on_regression", False) and (delta_errors > 0 or delta_warnings > 0)

        # write report
        report = [
            f"# Apply {run_id}",
            "",
            f"**Workdir:** `{workdir}`",
            f"**Plan:** `{plan_path}`",
            "",
            "## Applied ops",
        ]
        for op in result.applied_ops:
            report.append(f"- `{op['type']}` → `{op['path']}`")

        report += ["", "## Changed files"]
        if result.changed_files:
            report += [f"- `{p}`" for p in result.changed_files]
        else:
            report.append("- (no changes)")

        report += ["", "## Created files"]
        if result.created_files:
            report += [f"- `{p}`" for p in result.created_files]
        else:
            report.append("- (none)")

        report += ["", "## Shopify theme check"]
        if checks is None:
            report.append("- (skipped)")
        else:
            base_counts = (baseline or {}).get("counts", {"errors": 0, "warnings": 0})
            delta_errors = counts["errors"] - base_counts.get("errors", 0)
            delta_warnings = counts["warnings"] - base_counts.get("warnings", 0)
            report += [
                f"- Exit code: **{checks['returncode']}**",
                f"- Baseline errors/warnings: **{base_counts['errors']} / {base_counts['warnings']}**",
                f"- Current errors/warnings: **{counts['errors']} / {counts['warnings']}**",
                f"- Delta vs baseline: **{delta_errors:+d} errors**, **{delta_warnings:+d} warnings**",
            ]
            if baseline_path:
                report += [f"- Baseline file: `{baseline_path}`"]

        (out_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

        if regression:
            raise SystemExit("Theme check regression: errors/warnings increased vs baseline")

        print(f"✅ Applied plan. Artifacts at: {out_dir}")
        print(f"   Open: {out_dir / 'report.md'}")
        return

    if args.cmd == "run":
        workdir = Path(args.workdir).expanduser().resolve()
        task_path = Path(args.task).expanduser().resolve()
        runs_dir = Path(args.runs_dir).expanduser().resolve()

        # Strict command allowlist for this command (expand deliberately over time)
        allowed = [
            ["rg", "--files-with-matches"],
            ["rg", "--version"],
            ["git", "--version"],
            ["shopify", "version"],
            ["shopify", "theme", "check"],
        ]

        # ---- Validate inputs early (fail fast) ----
        if not workdir.exists() or not workdir.is_dir():
            raise SystemExit(f"workdir does not exist or is not a directory: {workdir}")
        if not task_path.exists():
            raise SystemExit(f"task file does not exist: {task_path}")

        validate_workdir_is_theme(workdir)

        # ---- Read task + parse context (read-only) ----
        task_text = read_text(task_path)
        task = parse_task_md(task_text)

        # ---- Create run folder + write minimal artifacts ASAP ----
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_dir = runs_dir / run_id
        ensure_dir(out_dir)

        meta = {
            "run_id": run_id,
            "workdir": str(workdir),
            "task_path": str(task_path),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "figma_links": task["figma_links"],
        }
        (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        (out_dir / "task.md").write_text(task_text, encoding="utf-8")

        # ---- Theme summary (static inventory / map) ----
        theme_summary = summarize_theme(workdir)
        (out_dir / "theme_summary.json").write_text(json.dumps(theme_summary, indent=2), encoding="utf-8")

        # ---- Reconnaissance (search hits / proof for DRY decisions) ----
        recon = {
            "theme_check": theme_structure_check(workdir),
            "top_level_dirs": top_level_dirs(workdir),
            "search_hits": rg_hits(
                workdir,
                patterns=[
                    "product-form", "buy-buttons", "media", "gallery",
                    "accordion", "drawer", "modal",
                    "card", "button", "price",
                    "schema", "\"settings\"", "\"blocks\"",
                ],
                max_files_per_pattern=25,
            ),
        }
        (out_dir / "recon.json").write_text(json.dumps(recon, indent=2), encoding="utf-8")

        # ---- Shopify theme check + baseline/regression ----
        checks = None
        baseline = None
        counts = None
        baseline_path = None

        if args.theme_check:
            # Run the check
            checks = run_theme_check(workdir, allowed_prefixes=allowed)

            # Count warnings/errors in a simple way (no dependency on CLI summary format)
            counts = count_theme_check(checks.get("stdout", ""), checks.get("stderr", ""))
            checks["counts"] = counts

            # Persist raw + structured outputs
            (out_dir / "theme_check.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
            (out_dir / "theme_check.out.txt").write_text((checks.get("stdout") or "") + "\n", encoding="utf-8")
            (out_dir / "theme_check.err.txt").write_text((checks.get("stderr") or "") + "\n", encoding="utf-8")

            # Baseline (stored outside theme; safe in agent repo)
            baseline_dir = Path("/app/baselines")
            ensure_dir(baseline_dir)

            theme_key = theme_key_from_path(workdir)
            baseline_path = baseline_dir / f"{theme_key}.json"

            baseline = load_json(baseline_path)
            if baseline is None:
                baseline = {
                    "theme_key": theme_key,
                    "workdir": str(workdir),
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "counts": counts,
                }
                baseline_path.write_text(json.dumps(baseline, indent=2), encoding="utf-8")

            # Optional gate (only if you pass --fail-on-regression)
            base_counts = baseline.get("counts", {"errors": 0, "warnings": 0})
            delta_errors = counts["errors"] - base_counts.get("errors", 0)
            delta_warnings = counts["warnings"] - base_counts.get("warnings", 0)

            regression = getattr(args, "fail_on_regression", False) and (delta_errors > 0 or delta_warnings > 0)


        # ---- Build report (single pass at end) ----
        report = [
            f"# Run {run_id}",
            "",
            f"**Workdir:** `{workdir}`",
            f"**Task:** `{task_path}`",
            "",
            "## Detected Figma links",
        ]
        if task["figma_links"]:
            report += [f"- {u}" for u in task["figma_links"]]
        else:
            report += ["- (none found)"]

        report += [
            "",
            "## Repo reconnaissance",
            f"- Looks like Shopify theme: **{recon['theme_check']['looks_like_theme']}**",
            "- Required dirs present:",
        ]
        for k, v in recon["theme_check"]["required_present"].items():
            report.append(f"  - `{k}`: {v}")

        report += [
            "",
            "## Theme summary",
            f"- Sections (liquid): **{theme_summary['file_counts']['sections_liquid']}**",
            f"- Snippets (liquid): **{theme_summary['file_counts']['snippets_liquid']}**",
            f"- Templates (json): **{theme_summary['file_counts']['templates_json']}**",
            f"- Assets JS: **{theme_summary['file_counts']['assets_js']}**",
            f"- Assets CSS: **{theme_summary['file_counts']['assets_css']}**",
            "",
            "### Entrypoints found (guesses)",
        ]
        for k, hits in theme_summary["entrypoints"].items():
            if hits:
                report.append(f"- **{k}**: " + ", ".join(f"`{h}`" for h in hits))
            else:
                report.append(f"- **{k}**: (none matched common names)")

        report += ["", "### Search hits (sample)"]
        if recon["search_hits"]:
            for h in recon["search_hits"][:20]:
                report.append(f"- `{h['pattern']}` → `{h['file']}`")
        else:
            report.append("- (no matches)")

        report += ["", "## Shopify theme check"]
        if checks is None:
            report += ["- (skipped) Run with `--theme-check` to execute `shopify theme check`"]
        else:
            base_counts = (baseline or {}).get("counts", {"errors": 0, "warnings": 0})
            delta_errors = counts["errors"] - base_counts.get("errors", 0)
            delta_warnings = counts["warnings"] - base_counts.get("warnings", 0)

            report += [
                f"- Shopify CLI: `{checks.get('shopify_version_stdout') or 'unknown'}`",
                f"- Exit code: **{checks['returncode']}**",
                f"- Baseline errors/warnings: **{base_counts['errors']} / {base_counts['warnings']}**",
                f"- Current errors/warnings: **{counts['errors']} / {counts['warnings']}**",
                f"- Delta vs baseline: **{delta_errors:+d} errors**, **{delta_warnings:+d} warnings**",
            ]
            if checks["returncode"] == 0:
                report += ["- ✅ No issues found (exit code 0)"]
            else:
                report += ["- ⚠️ Issues detected — see `theme_check.out.txt` / `theme_check.err.txt`"]

            if baseline_path:
                report += [f"- Baseline file: `{baseline_path}`"]

        plan = create_plan(task, recon, theme_summary, checks=checks, baseline=baseline)
        (out_dir / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")

        report += [
            "",
            "## Planned changes",
            "- See `plan.json` (no files modified yet)",
            "",
            "## Next steps (not implemented yet)",
            "- Plan minimal diffs",
            "- Implement + run checks + screenshots",
        ]

        (out_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

        if regression:
            raise SystemExit("Theme check regression: errors/warnings increased vs baseline")

        print(f"✅ Created run artifacts at: {out_dir}")
        print(f"   Open: {out_dir / 'report.md'}")

if __name__ == "__main__":
    main()

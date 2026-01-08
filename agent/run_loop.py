from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Console
from rich.panel import Panel

from agent.llm_openai_compat import OpenAICompatChat, ToolSpec
from agent.tools.context_files import read_task_bundle
from agent.tools.fs_theme import ThemeFS, ThemeScopeError
from agent.tools.cmd import run_allowed, CommandNotAllowed
from agent.tools.repo_recon import theme_structure_check
from agent.tools.theme_summary import summarize_theme
from agent.tools.theme_check import run_theme_check
from agent.tools.playwright_verify import run_playwright_verify
from agent.tools.mcp_stdio import MCPClient, MCPError
from agent.tools.artifacts_fs import ArtifactFS, ArtifactScopeError
from agent.tools.human_gate import wait_for_continue
from agent.tools.theme_dev_manager import start_theme_dev, read_theme_dev_output, ThemeDevError, ThemeDevProcess

console = Console()


@dataclass
class VerifyResult:
    ok: bool
    theme_check_ok: bool
    playwright_ok: bool
    theme_check_summary: str
    playwright_summary: str
    artifacts_dir: Path


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _allowed_cmd_prefixes() -> List[List[str]]:
    return [
        ["shopify", "theme", "check"],
        ["shopify", "theme", "dev"],
        ["shopify", "whoami"],
        ["shopify", "theme", "info"],
        ["shopify", "theme", "list"],
        ["rg"],
        ["node", "/app/agent/verify/verify.js"],
        ["node", "/app/agent/verify/visual_diff.js"],
    ]

def _seed_asserts_file(tasks_dir: Path, run_dir: Path) -> None:
    """
    Copy tasks/asserts.json into runs/<run_id>/asserts.json if present.
    If the run asserts already exists, do nothing (agent may have written it).
    """
    src = (tasks_dir / "asserts.json").resolve()
    dst = (run_dir / "asserts.json").resolve()

    if dst.exists():
        return
    if not src.exists():
        # no asserts provided; leave absent
        return

    try:
        dst.write_text(src.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    except Exception:
        # don't fail the run just because asserts couldn't be copied
        return


def _tool_error(msg: str) -> Dict[str, Any]:
    return {"ok": False, "error": msg}


def run_agent_loop(
    *,
    theme_root: Path,
    tasks_dir: Path,
    runs_dir: Path,
    max_iters: int,
    base_url: Optional[str],
    routes: List[str],
    run_theme_check: bool,
    run_playwright: bool,
    allow_dirty: bool,
    cmd_timeout_sec: int,
    llm_cfg: Dict[str, Any],
    mcp_cfg: Dict[str, Optional[str]],
) -> None:
    theme_structure_check(theme_root)

    run_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    run_dir = (runs_dir / run_id).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    console.print(Panel.fit(f"run_id: {run_id}\nworkdir: {theme_root}", title="theme-agent"))

    fs = ThemeFS(theme_root)
    artifacts = ArtifactFS(run_dir)
    allowed_cmds = _allowed_cmd_prefixes()

    figma_mcp = MCPClient.from_cmd(mcp_cfg.get("figma_cmd"), name="figma") if mcp_cfg.get("figma_cmd") else None
    shopify_mcp = MCPClient.from_cmd(mcp_cfg.get("shopify_cmd"), name="shopify") if mcp_cfg.get("shopify_cmd") else None

    chat = OpenAICompatChat(
        base_url=llm_cfg["base_url"],
        api_key=llm_cfg["api_key"],
        model=llm_cfg["model"],
        temperature=llm_cfg["temperature"],
    )

    theme_summary = summarize_theme(theme_root)
    _write_text(run_dir / "theme_summary.json", json.dumps(theme_summary, indent=2))

    last_verify: Optional[VerifyResult] = None

    # Auto start theme dev if Playwright is enabled but base_url not provided.
    dev_proc: Optional[ThemeDevProcess] = None
    effective_base_url = base_url
    if run_playwright and not base_url:
        try:
            console.print("Starting shopify theme dev automatically...")
            dev_proc = start_theme_dev(theme_root=theme_root, host="0.0.0.0", port=9292)
            effective_base_url = "http://127.0.0.1:9292"
            out = read_theme_dev_output(dev_proc)
            if out:
                _write_text(run_dir / "theme_dev_output.txt", out)
        except ThemeDevError as e:
            console.print(Panel.fit(str(e), title="theme dev error"))
            effective_base_url = None

    tools: List[ToolSpec] = _build_tool_specs()

    def call_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if name == "theme.read_file":
                return {"ok": True, "content": fs.read_text(args["path"])}
            if name == "theme.write_file":
                fs.write_text(args["path"], args["content"])
                return {"ok": True}
            if name == "theme.list_files":
                return {"ok": True, "files": fs.list_files(args.get("glob", "**/*"))}
            if name == "theme.search":
                pattern = args["pattern"]
                cmd = ["rg", "-n", "--hidden", "--no-heading", pattern, str(theme_root)]
                r = run_allowed(cmd, cwd=theme_root, allowed_prefixes=allowed_cmds, timeout_sec=cmd_timeout_sec)
                return {"ok": True, "stdout": r.stdout[:40000], "stderr": r.stderr[:40000], "returncode": r.returncode}

            if name == "artifacts.write_text":
                p = artifacts.write_text(args["path"], args["content"])
                return {"ok": True, "path": p}
            if name == "artifacts.write_base64":
                p = artifacts.write_base64(args["path"], args["base64"])
                return {"ok": True, "path": p}

            if name == "verify.run":
                vr = _run_verify(
                    theme_root=theme_root,
                    run_dir=run_dir,
                    allowed_cmds=allowed_cmds,
                    cmd_timeout_sec=cmd_timeout_sec,
                    base_url=effective_base_url,
                    routes=routes,
                    run_theme_check=run_theme_check,
                    run_playwright=run_playwright,
                    design_dir=str((run_dir / "design").resolve()),
                )
                nonlocal last_verify
                last_verify = vr
                return {
                    "ok": True,
                    "verify": {
                        "ok": vr.ok,
                        "theme_check_ok": vr.theme_check_ok,
                        "playwright_ok": vr.playwright_ok,
                        "theme_check_summary": vr.theme_check_summary,
                        "playwright_summary": vr.playwright_summary,
                        "artifacts_dir": str(vr.artifacts_dir),
                    },
                }

            if name == "human.pause_for_admin_updates":
                # Writes admin_steps.md and pauses until tasks/continue.txt says "continue"
                steps = args.get("admin_steps", "").strip()
                if not steps:
                    return _tool_error("admin_steps is required.")
                artifacts.write_text("admin_steps.md", steps)
                console.print(Panel.fit("Paused for admin updates. See runs/<run_id>/admin_steps.md", title="needs human"))
                wait_for_continue(tasks_dir)
                return {"ok": True, "resumed": True}

            if name == "mcp.figma.list_tools":
                if not figma_mcp:
                    return _tool_error("FIGMA_MCP_CMD not set; figma MCP client not available.")
                return {"ok": True, "tools": figma_mcp.list_tools()}

            if name == "mcp.figma.call":
                if not figma_mcp:
                    return _tool_error("FIGMA_MCP_CMD not set; figma MCP client not available.")
                return {"ok": True, "result": figma_mcp.call_tool(args["tool_name"], args.get("arguments", {}))}

            if name == "mcp.shopify.list_tools":
                if not shopify_mcp:
                    return _tool_error("SHOPIFY_MCP_CMD not set; shopify MCP client not available.")
                return {"ok": True, "tools": shopify_mcp.list_tools()}

            if name == "mcp.shopify.call":
                if not shopify_mcp:
                    return _tool_error("SHOPIFY_MCP_CMD not set; shopify MCP client not available.")
                return {"ok": True, "result": shopify_mcp.call_tool(args["tool_name"], args.get("arguments", {}))}

            return _tool_error(f"Unknown tool: {name}")

        except (ThemeScopeError, ArtifactScopeError) as e:
            return _tool_error(str(e))
        except (CommandNotAllowed, FileNotFoundError) as e:
            return _tool_error(str(e))
        except MCPError as e:
            return _tool_error(f"MCP error: {e}")
        except Exception as e:
            return _tool_error(f"Unhandled tool error: {type(e).__name__}: {e}")

    system = _system_prompt(theme_root=theme_root)
    messages: List[Dict[str, Any]] = [{"role": "system", "content": system}]

    try:
        for i in range(1, max_iters + 1):
            bundle = read_task_bundle(tasks_dir)
            _write_text(run_dir / "task_bundle.json", json.dumps(bundle, indent=2))

            iteration_dir = run_dir / f"iter_{i:02d}"
            iteration_dir.mkdir(parents=True, exist_ok=True)
            _seed_asserts_file(tasks_dir, run_dir)

            verify_context = ""
            if last_verify:
                verify_context = (
                    f"\nLast verification:\n"
                    f"- ok: {last_verify.ok}\n"
                    f"- theme_check_ok: {last_verify.theme_check_ok}\n"
                    f"- playwright_ok: {last_verify.playwright_ok}\n"
                    f"- theme_check_summary: {last_verify.theme_check_summary}\n"
                    f"- playwright_summary: {last_verify.playwright_summary}\n"
                    f"- artifacts_dir: {last_verify.artifacts_dir}\n"
                )

            user_msg = _build_user_message(
                iteration=i,
                theme_summary=theme_summary,
                task_bundle=bundle,
                verify_context=verify_context,
                base_url=effective_base_url,
                routes=routes,
                run_dir=run_dir,
            )
            messages.append({"role": "user", "content": user_msg})

            console.print(Panel.fit(f"Iteration {i}/{max_iters}", title="loop"))

            decision, messages = chat.run_with_tools(
                messages=messages,
                tools=tools,
                tool_handler=call_tool,
                max_tool_round_trips=40,
            )

            _write_text(iteration_dir / "decision.json", json.dumps(decision, indent=2))

            status = decision.get("status")
            if status == "done":
                console.print(Panel.fit("Agent marked task as done.", title="complete"))
                break

            if status == "needs_human":
                admin_steps = (decision.get("admin_steps") or "").strip()
                if admin_steps:
                    artifacts.write_text("admin_steps.md", admin_steps)
                    console.print(Panel.fit("Admin updates required. Written to runs/<run_id>/admin_steps.md", title="needs human"))
                # Pause until user signals continue
                console.print("Waiting for tasks/continue.txt to contain the word 'continue' ...")
                wait_for_continue(tasks_dir)
                console.print("Resuming after human updates...")
                continue

            if status == "error":
                console.print(Panel.fit(decision.get("error", "unknown error"), title="error"))
                break

        # Always leave a simple pointer file
        _write_text(run_dir / "RUN_COMPLETE.txt", f"completed_at={_now_iso()}\n")

    finally:
        if figma_mcp:
            figma_mcp.close()
        if shopify_mcp:
            shopify_mcp.close()
        if dev_proc:
            dev_proc.stop()


def _system_prompt(*, theme_root: Path) -> str:
    return (
        "You are an autonomous Shopify Horizon theme engineer.\n"
        "Complete the user's task by directly editing theme files and verifying changes.\n\n"
        "Hard constraints:\n"
        f"- You can ONLY read/write within the theme root: {theme_root}\n"
        "- You can ONLY write under: sections/, snippets/, templates/, layout/, assets/, config/, locales/\n"
        "- Do NOT add image/video assets or content directly into theme files.\n"
        "- Do NOT embed base64 images or large data URIs.\n"
        "- All content/images must be provided via Shopify admin/theme editor settings or metafields.\n"
        "- If designs require content or images, you must output clear admin steps and pause.\n"
        "- Never write agent code into the theme.\n\n"
        "Workflow:\n"
        "- Make small coherent edits.\n"
        "- Use Figma MCP to export reference images to runs/<run_id>/design when available.\n"
        "- Use verify.run frequently (theme check + Playwright screenshots + optional visual diff).\n"
        "- If content/admin setup is needed (metafields, settings, image uploads), return status=needs_human and provide admin_steps.\n"
        "- After resuming, verify again with updated content.\n\n"
        "Responses must be a JSON decision:\n"
        '{ "status": "continue", "notes": "..." }\n'
        '{ "status": "needs_human", "admin_steps": "..." }\n'
        '{ "status": "done", "notes": "..." }\n'
        '{ "status": "error", "error": "..." }\n'
    )


def _build_user_message(
    *,
    iteration: int,
    theme_summary: Dict[str, Any],
    task_bundle: Dict[str, str],
    verify_context: str,
    base_url: Optional[str],
    routes: List[str],
    run_dir: Path,
) -> str:
    return (
        f"Iteration: {iteration}\n\n"
        "Task files (authoritative):\n"
        f"- task.md:\n{task_bundle.get('task.md','')}\n\n"
        f"- context.md:\n{task_bundle.get('context.md','')}\n\n"
        f"- mid-task-changes.md:\n{task_bundle.get('mid-task-changes.md','')}\n\n"
        f"{verify_context}\n"
        "Theme summary (JSON):\n"
        f"{json.dumps(theme_summary)[:30000]}\n\n"
        "Verification:\n"
        f"- base_url={base_url}\n"
        f"- routes={routes}\n\n"
        "Artifacts:\n"
        f"- design dir for figma exports: {str((run_dir / 'design').resolve())}\n\n"
        "Proceed autonomously. Use tools. Run verify.run often.\n"
        "If you need admin content (images/text/metafields/settings), return status=needs_human with admin_steps.\n"
    )


def _build_tool_specs() -> List[ToolSpec]:
    return [
        ToolSpec(
            name="theme.read_file",
            description="Read a theme file as text (theme-root scoped).",
            schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        ),
        ToolSpec(
            name="theme.write_file",
            description="Write a theme file as text (theme-root scoped).",
            schema={
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        ),
        ToolSpec(
            name="theme.list_files",
            description="List files under the theme root matching a glob.",
            schema={"type": "object", "properties": {"glob": {"type": "string"}}, "required": []},
        ),
        ToolSpec(
            name="theme.search",
            description="Search theme files using ripgrep (rg).",
            schema={"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]},
        ),
        ToolSpec(
            name="artifacts.write_text",
            description="Write an artifact text file under runs/<run_id>/ (safe).",
            schema={
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        ),
        ToolSpec(
            name="artifacts.write_base64",
            description="Write an artifact binary file from base64 under runs/<run_id>/ (safe).",
            schema={
                "type": "object",
                "properties": {"path": {"type": "string"}, "base64": {"type": "string"}},
                "required": ["path", "base64"],
            },
        ),
        ToolSpec(
            name="verify.run",
            description="Run theme check + Playwright verification; saves artifacts under runs/<run_id>/verify.",
            schema={"type": "object", "properties": {}, "required": []},
        ),
        ToolSpec(
            name="human.pause_for_admin_updates",
            description="Write admin steps and pause until tasks/continue.txt contains 'continue'.",
            schema={
                "type": "object",
                "properties": {"admin_steps": {"type": "string"}},
                "required": ["admin_steps"],
            },
        ),
        ToolSpec(
            name="mcp.figma.list_tools",
            description="List tools exposed by the Figma MCP server (FIGMA_MCP_CMD).",
            schema={"type": "object", "properties": {}, "required": []},
        ),
        ToolSpec(
            name="mcp.figma.call",
            description="Call a tool on the Figma MCP server.",
            schema={
                "type": "object",
                "properties": {"tool_name": {"type": "string"}, "arguments": {"type": "object"}},
                "required": ["tool_name"],
            },
        ),
        ToolSpec(
            name="mcp.shopify.list_tools",
            description="List tools exposed by the Shopify/docs MCP server (SHOPIFY_MCP_CMD).",
            schema={"type": "object", "properties": {}, "required": []},
        ),
        ToolSpec(
            name="mcp.shopify.call",
            description="Call a tool on the Shopify/docs MCP server.",
            schema={
                "type": "object",
                "properties": {"tool_name": {"type": "string"}, "arguments": {"type": "object"}},
                "required": ["tool_name"],
            },
        ),
    ]


def _run_verify(
    *,
    theme_root: Path,
    run_dir: Path,
    allowed_cmds: List[List[str]],
    cmd_timeout_sec: int,
    base_url: Optional[str],
    routes: List[str],
    run_theme_check: bool,
    run_playwright: bool,
    design_dir: str,
) -> VerifyResult:
    artifacts_dir = run_dir / "verify" / time.strftime("%Y%m%d_%H%M%S")
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    theme_ok = True
    theme_summary = "skipped"
    if run_theme_check:
        res = run_theme_check(theme_root, artifacts_dir=artifacts_dir, allowed_cmds=allowed_cmds, timeout_sec=cmd_timeout_sec)
        theme_ok = bool(res["ok"])
        theme_summary = str(res["summary"])

    pw_ok = True
    pw_summary = "skipped"
    if run_playwright:
        if not base_url:
            pw_ok = False
            pw_summary = "Playwright enabled but base_url not available (theme dev failed or not provided)."
        else:
            res = run_playwright_verify(
                theme_root=theme_root,
                artifacts_dir=artifacts_dir,
                allowed_cmds=allowed_cmds,
                timeout_sec=cmd_timeout_sec,
                base_url=base_url,
                routes=routes,
                asserts_path=str((run_dir / "asserts.json").resolve()),
                design_dir=design_dir,
            )
            pw_ok = bool(res["ok"])
            pw_summary = str(res["summary"])

    ok = theme_ok and pw_ok
    _write_text(artifacts_dir / "verify_summary.txt", f"ok={ok}\ntheme_ok={theme_ok}\npw_ok={pw_ok}\n")
    return VerifyResult(
        ok=ok,
        theme_check_ok=theme_ok,
        playwright_ok=pw_ok,
        theme_check_summary=theme_summary,
        playwright_summary=pw_summary,
        artifacts_dir=artifacts_dir,
    )

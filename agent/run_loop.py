from __future__ import annotations

import inspect
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel

from agent.llm_openai_compat import OpenAICompatChat, ToolSpec
from agent.tools.artifacts_fs import ArtifactFS, ArtifactScopeError
from agent.tools.cmd import CommandNotAllowed, run_allowed
from agent.tools.fs_theme import ThemeFS, ThemeScopeError
from agent.tools.human_gate import wait_for_continue
from agent.tools.mcp_stdio import MCPClient, MCPError
from agent.tools.playwright_verify import run_playwright_verify
from agent.tools.repo_recon import theme_structure_check
from agent.tools.theme_check import run_theme_check
from agent.tools.theme_dev_manager import ThemeDevError, ThemeDevProcess, start_theme_dev
from agent.tools.theme_summary import summarize_theme

console = Console()


def _construct(cls, **preferred_kwargs):
    """
    Construct dataclass/objects even if their __init__ parameter names differ.
    Example: ThemeFS(root=...) vs ThemeFS(theme_root=...) vs ThemeFS(workdir=...)
    """
    sig = inspect.signature(cls.__init__)
    params = set(sig.parameters.keys())
    params.discard("self")

    filtered = {k: v for k, v in preferred_kwargs.items() if k in params}

    if not filtered and len(params) == 1:
        only = next(iter(preferred_kwargs.values()))
        return cls(only)

    return cls(**filtered)


@dataclass
class VerifyResult:
    ok: bool
    theme_check_ok: bool
    playwright_ok: bool
    theme_check_summary: str
    playwright_summary: str
    artifacts_dir: Path


def _allowed_cmd_prefixes() -> List[List[str]]:
    return [
        ["shopify", "theme", "check"],
        ["shopify", "theme", "dev"],
        ["shopify", "theme", "info"],
        ["shopify", "theme", "list"],
        ["rg"],
        ["node", "/app/agent/verify/verify.js"],
        ["node", "/app/agent/verify/visual_diff.js"],
    ]


def _seed_asserts_file(tasks_dir: Path, run_dir: Path) -> None:
    """
    If tasks/asserts.json exists, copy it to run_dir for reproducibility.
    """
    src = tasks_dir / "asserts.json"
    if src.exists():
        (run_dir / "asserts.json").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _tool_error(msg: str) -> Dict[str, Any]:
    return {"ok": False, "error": msg}


def _build_system_prompt(
    *,
    task_md: str,
    context_md: Optional[str],
    mid_task_changes_md: Optional[str],
    horizon_context_md: Optional[str],
    theme_summary_json: str,
    base_url: Optional[str],
    routes: List[str],
    run_theme_check_enabled: bool,
    run_playwright_enabled: bool,
) -> str:
    routes_txt = ", ".join(routes) if routes else "(none)"

    return (
        "You are an autonomous agent that edits Shopify theme files in a git repo.\n"
        "You MUST follow these constraints:\n"
        "- Only edit theme files inside the repo (sections/snippets/templates/assets/config/locales).\n"
        "- Never add new content or image assets. Content lives in Shopify admin.\n"
        "- Keep changes minimal and surgical.\n"
        "- Prefer existing theme conventions.\n"
        "- You can run verification tools.\n"
        "- If you need admin content (images/text/metafields/settings), return status=needs_human with admin_steps.\n"
        "\n"
        + (
            "Horizon theme architecture rules (must follow):\n"
            + horizon_context_md.strip()
            + "\n\n"
            if horizon_context_md and horizon_context_md.strip()
            else ""
        )
        + f"Local preview base_url: {base_url or '(not running)'}\n"
        + f"Routes to verify: {routes_txt}\n"
        + f"Verification enabled: theme_check={run_theme_check_enabled}, playwright={run_playwright_enabled}\n"
        "\n"
        "Task:\n"
        f"{task_md.strip()}\n"
        + ("\nContext:\n" + context_md.strip() + "\n" if context_md else "")
        + ("\nMid-task changes:\n" + mid_task_changes_md.strip() + "\n" if mid_task_changes_md else "")
        + "\nTheme summary (json):\n"
        + theme_summary_json.strip()
        + "\n\n"
        "Output JSON only with keys:\n"
        "- status: done | continue | needs_human\n"
        "- plan: short text\n"
        "- edits: short text\n"
        "- admin_steps: only if needs_human\n"
        "- verify: optional (call verify tool as needed)\n"
        "- horizon_ack: 2-5 bullets of Horizon rules you will follow (from horizon-context.md)\n"
    )


def _build_tool_specs() -> List[ToolSpec]:
    # OpenAI tools require function.name to match ^[a-zA-Z0-9_-]+$ (no dots)
    return [
        ToolSpec(
            name="theme_read_file",
            description="Read a theme file as text (theme-root scoped).",
            schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        ),
        ToolSpec(
            name="theme_write_file",
            description="Write a theme file as text (theme-root scoped).",
            schema={
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        ),
        ToolSpec(
            name="theme_list_files",
            description="List files under the theme root matching a glob.",
            schema={"type": "object", "properties": {"glob": {"type": "string"}}, "required": []},
        ),
        ToolSpec(
            name="theme_search",
            description="Ripgrep search across theme files.",
            schema={"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]},
        ),
        ToolSpec(
            name="artifacts_write_text",
            description="Write a text artifact into the run artifacts directory.",
            schema={
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        ),
        ToolSpec(
            name="artifacts_write_base64",
            description="Write a base64 artifact into the run artifacts directory.",
            schema={
                "type": "object",
                "properties": {"path": {"type": "string"}, "base64": {"type": "string"}},
                "required": ["path", "base64"],
            },
        ),
        ToolSpec(
            name="verify_run",
            description="Run verification: theme check and/or Playwright smoke. Returns summaries and ok flags.",
            schema={"type": "object", "properties": {}, "required": []},
        ),
        ToolSpec(
            name="human_pause_for_admin_updates",
            description="Pause and wait for human to apply Shopify-admin-only steps, then continue.",
            schema={"type": "object", "properties": {"admin_steps": {"type": "string"}}, "required": ["admin_steps"]},
        ),
        ToolSpec(
            name="mcp_figma_list_tools",
            description="List available MCP tools from Figma server.",
            schema={"type": "object", "properties": {}, "required": []},
        ),
        ToolSpec(
            name="mcp_figma_call",
            description="Call a tool on the Figma MCP server.",
            schema={
                "type": "object",
                "properties": {"name": {"type": "string"}, "arguments": {"type": "object"}},
                "required": ["name", "arguments"],
            },
        ),
        ToolSpec(
            name="mcp_shopify_list_tools",
            description="List available MCP tools from Shopify docs/best-practices server.",
            schema={"type": "object", "properties": {}, "required": []},
        ),
        ToolSpec(
            name="mcp_shopify_call",
            description="Call a tool on the Shopify MCP server.",
            schema={
                "type": "object",
                "properties": {"name": {"type": "string"}, "arguments": {"type": "object"}},
                "required": ["name", "arguments"],
            },
        ),
    ]


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
    allow_dirty: bool,  # kept for CLI compatibility; not enforced here
    cmd_timeout_sec: int,
    llm_cfg: Dict[str, Any],
    mcp_cfg: Dict[str, Optional[str]],
) -> None:
    # repo check
    theme_structure_check(theme_root)

    run_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    console.print(Panel.fit(f"run_id: {run_id}\nworkdir: {theme_root}", title="theme-agent"))
    _seed_asserts_file(tasks_dir, run_dir)

    fs = _construct(ThemeFS, root=theme_root, theme_root=theme_root, workdir=theme_root)
    artifacts = _construct(ArtifactFS, root=run_dir, run_dir=run_dir, artifacts_dir=run_dir)

    # --- Task bundle: read directly from disk ---
    console.print(f" tasks_dir={tasks_dir}")
    task_path = tasks_dir / "task.md"
    context_path = tasks_dir / "context.md"
    mid_path = tasks_dir / "mid-task-changes.md"
    horizon_context_path = tasks_dir / "horizon-context.md"

    console.print(f" task.md exists? {task_path.exists()} ({task_path})")
    if not task_path.exists():
        try:
            listing = "\n".join([p.name for p in sorted(tasks_dir.iterdir())])
        except Exception as e:
            listing = f"<failed to list tasks_dir: {type(e).__name__}: {e}>"
        raise RuntimeError(f"task.md not found in tasks_dir={tasks_dir}\ncontents:\n{listing}")

    task_md = task_path.read_text(encoding="utf-8")

    context_md = ""
    if context_path.exists():
        context_md = context_path.read_text(encoding="utf-8")

    mid_task_changes_md = ""
    if mid_path.exists():
        mid_task_changes_md = mid_path.read_text(encoding="utf-8")

    horizon_context_md = ""
    if horizon_context_path.exists():
        horizon_context_md = horizon_context_path.read_text(encoding="utf-8")

    artifacts.write_text("task.md", task_md)
    if context_md.strip():
        artifacts.write_text("context.md", context_md)
    if mid_task_changes_md.strip():
        artifacts.write_text("mid-task-changes.md", mid_task_changes_md)
    if horizon_context_md.strip():
        artifacts.write_text("horizon-context.md", horizon_context_md)

    # --- MCP clients ---
    figma_mcp: Optional[MCPClient] = None
    shopify_mcp: Optional[MCPClient] = None

    if mcp_cfg.get("figma_cmd"):
        try:
            console.print(" starting Figma MCP…")
            figma_mcp = MCPClient.from_cmd(mcp_cfg["figma_cmd"], name="figma")
            console.print(" Figma MCP ready")
        except Exception as e:
            raise MCPError(f"figma MCP error: {e}")

    if mcp_cfg.get("shopify_cmd"):
        try:
            console.print(" starting Shopify MCP…")
            shopify_mcp = MCPClient.from_cmd(mcp_cfg["shopify_cmd"], name="shopify")
            console.print(" Shopify MCP ready")
        except Exception as e:
            raise MCPError(f"shopify MCP error: {e}")

    # --- LLM ---
    chat = OpenAICompatChat(
        base_url=llm_cfg["base_url"],
        api_key=llm_cfg["api_key"],
        model=llm_cfg["model"],
        temperature=llm_cfg["temperature"],
    )

    theme_summary = summarize_theme(theme_root)
    _write_text(run_dir / "theme_summary.json", json.dumps(theme_summary, indent=2))

    last_verify: Optional[VerifyResult] = None

    # --- Theme dev (optional) ---
    dev_proc: Optional[ThemeDevProcess] = None
    effective_base_url = base_url

    if run_playwright and not base_url:
        try:
            console.print("Starting shopify theme dev automatically...")
            console.print(f" calling start_theme_dev(host=0.0.0.0, port=9292)")
            dev_proc = start_theme_dev(theme_root=theme_root, host="0.0.0.0", port=9292)
            console.print(" start_theme_dev returned")
            effective_base_url = "http://127.0.0.1:9292"
            console.print(" not waiting for CLI readiness; sleeping 3s")
            time.sleep(3)
        except ThemeDevError as e:
            console.print(Panel.fit(str(e), title="theme dev error"))
            effective_base_url = None

    tools: List[ToolSpec] = _build_tool_specs()

    def call_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            # Accept both underscore tool names (new) and dotted names (legacy)
            if name in ("theme_read_file", "theme.read_file"):
                return {"ok": True, "content": fs.read_text(args["path"])}

            if name in ("theme_write_file", "theme.write_file"):
                fs.write_text(args["path"], args["content"])
                return {"ok": True}

            if name in ("theme_list_files", "theme.list_files"):
                return {"ok": True, "files": fs.list_files(args.get("glob", "**/*"))}

            if name in ("theme_search", "theme.search"):
                pattern = args["pattern"]
                cmd = ["rg", "-n", "--hidden", "--no-heading", pattern, str(theme_root)]
                r = run_allowed(cmd, cwd=theme_root, allowed_prefixes=_allowed_cmd_prefixes(), timeout_sec=cmd_timeout_sec)
                return {"ok": True, "stdout": r.stdout[:40000], "stderr": r.stderr[:40000], "returncode": r.returncode}

            if name in ("artifacts_write_text", "artifacts.write_text"):
                p = artifacts.write_text(args["path"], args["content"])
                return {"ok": True, "path": str(p)}

            if name in ("artifacts_write_base64", "artifacts.write_base64"):
                p = artifacts.write_base64(args["path"], args["base64"])
                return {"ok": True, "path": str(p)}

            if name in ("verify_run", "verify.run"):
                vr = _run_verify(
                    theme_root=theme_root,
                    run_dir=run_dir,
                    allowed_cmds=_allowed_cmd_prefixes(),
                    cmd_timeout_sec=cmd_timeout_sec,
                    base_url=effective_base_url,
                    routes=routes,
                    do_theme_check=run_theme_check,
                    do_playwright=run_playwright,
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

            if name in ("human_pause_for_admin_updates", "human.pause_for_admin_updates"):
                steps = (args.get("admin_steps") or "").strip()
                if not steps:
                    return _tool_error("admin_steps is required.")
                artifacts.write_text("admin_steps.md", steps)
                console.print(Panel.fit("Paused for admin updates. See runs/<run_id>/admin_steps.md", title="needs human"))
                wait_for_continue(tasks_dir)
                return {"ok": True, "resumed": True}

            if name in ("mcp_figma_list_tools", "mcp.figma.list_tools"):
                if not figma_mcp:
                    return _tool_error("FIGMA_MCP_CMD not set; figma MCP client not available.")
                return {"ok": True, "tools": figma_mcp.list_tools()}

            if name in ("mcp_figma_call", "mcp.figma.call"):
                if not figma_mcp:
                    return _tool_error("FIGMA_MCP_CMD not set; figma MCP client not available.")
                tool_name = args.get("name")
                tool_args = args.get("arguments") or {}
                if not tool_name:
                    return _tool_error("name is required.")
                return {"ok": True, "result": figma_mcp.call_tool(tool_name, tool_args)}

            if name in ("mcp_shopify_list_tools", "mcp.shopify.list_tools"):
                if not shopify_mcp:
                    return _tool_error("SHOPIFY_MCP_CMD not set; shopify MCP client not available.")
                return {"ok": True, "tools": shopify_mcp.list_tools()}

            if name in ("mcp_shopify_call", "mcp.shopify.call"):
                if not shopify_mcp:
                    return _tool_error("SHOPIFY_MCP_CMD not set; shopify MCP client not available.")
                tool_name = args.get("name")
                tool_args = args.get("arguments") or {}
                if not tool_name:
                    return _tool_error("name is required.")
                return {"ok": True, "result": shopify_mcp.call_tool(tool_name, tool_args)}

            return _tool_error(f"Unknown tool: {name}")

        except (ThemeScopeError, ArtifactScopeError, CommandNotAllowed) as e:
            return _tool_error(f"{type(e).__name__}: {e}")
        except Exception as e:
            return _tool_error(f"{type(e).__name__}: {e}")

    system = _build_system_prompt(
        task_md=task_md,
        context_md=(context_md if context_md.strip() else None),
        mid_task_changes_md=(mid_task_changes_md if mid_task_changes_md.strip() else None),
        horizon_context_md=(horizon_context_md if horizon_context_md.strip() else None),
        theme_summary_json=(run_dir / "theme_summary.json").read_text(encoding="utf-8", errors="ignore"),
        base_url=effective_base_url,
        routes=routes,
        run_theme_check_enabled=run_theme_check,
        run_playwright_enabled=run_playwright,
    )

    messages: List[Dict[str, Any]] = [{"role": "system", "content": system}]

    for i in range(1, max_iters + 1):
        console.print(Panel.fit(f"Iteration {i}/{max_iters}", title="loop"))
        console.print(f"[debug {time.strftime('%H:%M:%S')}] calling LLM run_with_tools; tools={len(tools)} messages={len(messages)}")

        decision, messages = chat.run_with_tools(
            messages=messages,
            tools=tools,
            tool_handler=call_tool,
            max_tool_round_trips=40,
        )

        _write_text(run_dir / f"iter_{i:02d}_decision.json", json.dumps(decision, indent=2))
        status = (decision or {}).get("status")

        if status == "done":
            console.print(Panel.fit("Agent marked task as done.", title="complete"))
            break

        if status == "needs_human":
            steps = (decision or {}).get("admin_steps", "").strip()
            if steps:
                artifacts.write_text("admin_steps.md", steps)
            console.print(Panel.fit("Waiting for human to apply Shopify admin steps…", title="human"))
            wait_for_continue(tasks_dir)
            continue

    # cleanup
    if dev_proc is not None:
        try:
            dev_proc.stop()
        except Exception:
            pass

    if figma_mcp is not None:
        try:
            figma_mcp.close()
        except Exception:
            pass

    if shopify_mcp is not None:
        try:
            shopify_mcp.close()
        except Exception:
            pass


def _run_verify(
    *,
    theme_root: Path,
    run_dir: Path,
    allowed_cmds: List[List[str]],
    cmd_timeout_sec: int,
    base_url: Optional[str],
    routes: List[str],
    do_theme_check: bool,
    do_playwright: bool,
) -> VerifyResult:
    artifacts_dir = run_dir / "verify"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    theme_check_ok = True
    playwright_ok = True
    theme_check_summary = ""
    playwright_summary = ""

    if do_theme_check:
        r = run_theme_check(theme_root)
        theme_check_ok = r.ok
        theme_check_summary = r.summary
        _write_text(artifacts_dir / "theme_check.txt", r.raw_output)

    if do_playwright:
        r = run_playwright_verify(base_url=base_url, routes=routes)
        playwright_ok = r.ok
        playwright_summary = r.summary
        _write_text(artifacts_dir / "playwright.txt", r.raw_output)

    ok = theme_check_ok and playwright_ok
    return VerifyResult(
        ok=ok,
        theme_check_ok=theme_check_ok,
        playwright_ok=playwright_ok,
        theme_check_summary=theme_check_summary,
        playwright_summary=playwright_summary,
        artifacts_dir=artifacts_dir,
    )

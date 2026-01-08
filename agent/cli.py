import argparse
import os
from pathlib import Path

from agent.run_loop import run_agent_loop
from agent.tools.shopify_cli import shopify_login, shopify_theme_dev
from agent.tools.doctor import run_doctor


def _as_path(p: str) -> Path:
    return Path(p).expanduser().resolve()


def main() -> None:
    parser = argparse.ArgumentParser(prog="theme-agent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    doctor = sub.add_parser("doctor", help="Validate Shopify CLI auth, store, and theme access")
    doctor.add_argument("--workdir", required=True, help="Mounted theme root (Shopify theme directory)")
    doctor.add_argument("--timeout-sec", type=int, default=60)

    # --- agent loop ---
    run = sub.add_parser("run", help="Run the autonomous theme agent loop")
    run.add_argument("--workdir", required=True, help="Mounted theme root (Shopify theme directory)")
    run.add_argument("--tasks-dir", default="/app/tasks", help="Directory containing task.md, context.md, mid-task-changes.md")
    run.add_argument("--runs-dir", default="/app/runs", help="Directory to write run artifacts")
    run.add_argument("--max-iters", type=int, default=12, help="Max outer iterations (edit->verify cycles)")

    run.add_argument("--base-url", default=None, help="Base URL Playwright should test (e.g. http://127.0.0.1:9292)")
    run.add_argument("--routes", default=None, help="Comma-separated routes to test (e.g. /products/handle,/cart)")
    run.add_argument("--no-theme-check", action="store_true", help="Skip 'shopify theme check' verification")
    run.add_argument("--no-playwright", action="store_true", help="Skip Playwright verification")

    run.add_argument("--allow-dirty", action="store_true", help="Allow running with existing modifications in theme dir")
    run.add_argument("--timeout-sec", type=int, default=180, help="Command timeout seconds")

    # --- shopify login helper ---
    login = sub.add_parser("login", help="Login to Shopify CLI inside container (open URL on host browser)")
    login.add_argument("--workdir", required=True, help="Mounted theme root (Shopify theme directory)")
    login.add_argument("--timeout-sec", type=int, default=600, help="Login command timeout seconds")

    # --- shopify theme dev helper ---
    dev = sub.add_parser("theme-dev", help="Run 'shopify theme dev' bound to 0.0.0.0 for Docker port mapping")
    dev.add_argument("--workdir", required=True, help="Mounted theme root (Shopify theme directory)")
    dev.add_argument("--host", default="0.0.0.0", help="Host bind address (default 0.0.0.0)")
    dev.add_argument("--port", type=int, default=9292, help="Port (default 9292)")
    dev.add_argument("--timeout-sec", type=int, default=0, help="0 = no timeout (recommended for dev server)")

    args = parser.parse_args()

    if args.cmd == "doctor":
        theme_root = _as_path(args.workdir)
        run_doctor(theme_root=theme_root, timeout_sec=args.timeout_sec)
        return

    if args.cmd == "login":
        theme_root = _as_path(args.workdir)
        shopify_login(theme_root=theme_root, timeout_sec=args.timeout_sec)
        return

    if args.cmd == "theme-dev":
        theme_root = _as_path(args.workdir)
        shopify_theme_dev(theme_root=theme_root, host=args.host, port=args.port, timeout_sec=args.timeout_sec)
        return

    # run agent loop
    theme_root = _as_path(args.workdir)
    tasks_dir = _as_path(args.tasks_dir)
    runs_dir = _as_path(args.runs_dir)

    routes = []
    if args.routes:
        routes = [r.strip() for r in args.routes.split(",") if r.strip()]

    llm_cfg = {
        "base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "api_key": os.environ.get("OPENAI_API_KEY"),
        "model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
        "temperature": float(os.environ.get("OPENAI_TEMPERATURE", "0.2")),
    }

    mcp_cfg = {
        "figma_cmd": os.environ.get("FIGMA_MCP_CMD"),
        "shopify_cmd": os.environ.get("SHOPIFY_MCP_CMD"),
    }

    run_agent_loop(
        theme_root=theme_root,
        tasks_dir=tasks_dir,
        runs_dir=runs_dir,
        max_iters=args.max_iters,
        base_url=args.base_url,
        routes=routes,
        run_theme_check=(not args.no_theme_check),
        run_playwright=(not args.no_playwright),
        allow_dirty=args.allow_dirty,
        cmd_timeout_sec=args.timeout_sec,
        llm_cfg=llm_cfg,
        mcp_cfg=mcp_cfg,
    )


if __name__ == "__main__":
    main()

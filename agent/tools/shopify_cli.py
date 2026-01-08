from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from agent.tools.cmd import run_allowed


def _allowed_cmd_prefixes() -> List[List[str]]:
    return [
        ["shopify", "auth", "login"],
        ["shopify", "theme", "dev"],
        ["shopify", "theme", "check"],
        ["shopify", "theme", "list"],
        ["shopify", "theme", "info"],
        ["rg"],
        ["node", "/app/agent/verify/verify.js"],
    ]


def _require_store() -> None:
    # Shopify CLI requires a store for theme commands; docs show --store / SHOPIFY_FLAG_STORE. :contentReference[oaicite:9]{index=9}
    if not os.environ.get("SHOPIFY_FLAG_STORE"):
        raise SystemExit(
            "Missing SHOPIFY_FLAG_STORE. Set it to your-store.myshopify.com (or store prefix)."
        )


def shopify_login(*, theme_root: Path, timeout_sec: int = 600) -> None:
    """
    Interactive login (browser on host). You still need SHOPIFY_FLAG_STORE for theme dev later.
    """
    cmd = ["shopify", "auth", "login"]
    res = run_allowed(cmd, cwd=theme_root, allowed_prefixes=_allowed_cmd_prefixes(), timeout_sec=timeout_sec)
    if res.stdout:
        print(res.stdout)
    if res.stderr:
        print(res.stderr)


def shopify_theme_dev(
    *,
    theme_root: Path,
    host: str = "0.0.0.0",
    port: int = 9292,
    timeout_sec: int = 0,
    store: Optional[str] = None,
    theme: Optional[str] = None,
    password: Optional[str] = None,
    store_password: Optional[str] = None,
) -> None:
    """
    Runs `shopify theme dev` bound to Docker-reachable host/port.
    Store/theme/token can come from env vars:
      - SHOPIFY_FLAG_STORE (required) :contentReference[oaicite:10]{index=10}
      - SHOPIFY_FLAG_THEME_ID (optional) :contentReference[oaicite:11]{index=11}
      - SHOPIFY_CLI_THEME_TOKEN (optional; Theme Access password) :contentReference[oaicite:12]{index=12}
      - SHOPIFY_FLAG_STORE_PASSWORD (optional) :contentReference[oaicite:13]{index=13}
    """
    # Ensure store is present either via arg or env.
    if store:
        os.environ["SHOPIFY_FLAG_STORE"] = store
    _require_store()

    # If provided, override env values for this invocation.
    if theme:
        os.environ["SHOPIFY_FLAG_THEME_ID"] = theme
    if password:
        os.environ["SHOPIFY_CLI_THEME_TOKEN"] = password
    if store_password:
        os.environ["SHOPIFY_FLAG_STORE_PASSWORD"] = store_password

    cmd = ["shopify", "theme", "dev", "--host", host, "--port", str(port)]

    actual_timeout = None if timeout_sec == 0 else timeout_sec
    res = run_allowed(cmd, cwd=theme_root, allowed_prefixes=_allowed_cmd_prefixes(), timeout_sec=actual_timeout)

    if res.stdout:
        print(res.stdout)
    if res.stderr:
        print(res.stderr)

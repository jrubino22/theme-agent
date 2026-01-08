from __future__ import annotations

import os
from pathlib import Path
from typing import List

from agent.tools.cmd import run_allowed, CmdResult


def _allowed_cmd_prefixes() -> List[List[str]]:
    return [
        ["shopify", "version"],
        ["shopify", "theme", "info"],
        ["shopify", "theme", "list"],
    ]


def _print_cmd_result(res: CmdResult) -> None:
    out = (res.stdout or "").strip()
    err = (res.stderr or "").strip()
    if out:
        print(out)
    if err:
        print(err)
    if not out and not err:
        print(f"(no output, rc={res.returncode})")


def run_doctor(*, theme_root: Path, timeout_sec: int = 60) -> None:
    store = os.environ.get("SHOPIFY_FLAG_STORE")
    if not store:
        raise SystemExit(
            "SHOPIFY_FLAG_STORE is not set. "
            "Set it to your-store.myshopify.com before running."
        )

    print(f"Using store: {store}")

    print("\nChecking Shopify CLI version (shopify version)...")
    res = run_allowed(
        ["shopify", "version"],
        cwd=theme_root,
        allowed_prefixes=_allowed_cmd_prefixes(),
        timeout_sec=timeout_sec,
    )
    _print_cmd_result(res)

    print("\nChecking theme access (shopify theme info)...")
    res = run_allowed(
        ["shopify", "theme", "info"],
        cwd=theme_root,
        allowed_prefixes=_allowed_cmd_prefixes(),
        timeout_sec=timeout_sec,
    )
    _print_cmd_result(res)

    if res.returncode != 0:
        print(
            "\nIt looks like Shopify CLI is not authenticated or cannot access the store/theme.\n"
            "Next step (run this):\n"
            "  docker compose -f docker/docker-compose.yml run --rm theme-agent sh -lc "
            "\"shopify auth login --store $SHOPIFY_FLAG_STORE\"\n"
            "Then rerun doctor."
        )
        return

    print("\nListing available themes (shopify theme list)...")
    res = run_allowed(
        ["shopify", "theme", "list"],
        cwd=theme_root,
        allowed_prefixes=_allowed_cmd_prefixes(),
        timeout_sec=timeout_sec,
    )
    _print_cmd_result(res)

    print("\nDoctor completed. If no errors appeared above, your setup is valid.")

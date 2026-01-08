from __future__ import annotations

import os
from pathlib import Path
from typing import List

from agent.tools.cmd import run_allowed


def _allowed_cmd_prefixes() -> List[List[str]]:
    return [
        ["shopify", "whoami"],
        ["shopify", "theme", "info"],
        ["shopify", "theme", "list"],
    ]


def run_doctor(*, theme_root: Path, timeout_sec: int = 60) -> None:
    """
    Validates Shopify CLI environment:
    - CLI is authenticated
    - Store is configured
    - Theme access works
    """

    store = os.environ.get("SHOPIFY_FLAG_STORE")
    if not store:
        raise SystemExit(
            "SHOPIFY_FLAG_STORE is not set. "
            "Set it to your-store.myshopify.com before running."
        )

    print(f"Using store: {store}")

    print("\nChecking Shopify CLI authentication (shopify whoami)...")
    res = run_allowed(
        ["shopify", "whoami"],
        cwd=theme_root,
        allowed_prefixes=_allowed_cmd_prefixes(),
        timeout_sec=timeout_sec,
    )
    print(res.stdout or res.stderr)

    print("\nChecking theme access (shopify theme info)...")
    res = run_allowed(
        ["shopify", "theme", "info"],
        cwd=theme_root,
        allowed_prefixes=_allowed_cmd_prefixes(),
        timeout_sec=timeout_sec,
    )
    print(res.stdout or res.stderr)

    print("\nListing available themes (shopify theme list)...")
    res = run_allowed(
        ["shopify", "theme", "list"],
        cwd=theme_root,
        allowed_prefixes=_allowed_cmd_prefixes(),
        timeout_sec=timeout_sec,
    )
    print(res.stdout or res.stderr)

    print("\nDoctor completed. If no errors appeared above, your setup is valid.")

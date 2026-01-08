# Shopify Theme Agent (Horizon)

This project is an autonomous AI agent designed to work directly on Shopify Horizon themes.

The agent:
- edits theme files directly (sections, snippets, templates, layout, assets, config, locales)
- enforces a strict theme-root-only sandbox
- can use Figma MCP and Shopify Docs MCP when available
- verifies work using `shopify theme check` and Playwright screenshots
- optionally performs pixel-level visual diffs between Figma exports and Playwright screenshots
- iterates autonomously until complete

Content rule:
- The agent must never add image/video assets or “content” directly to the theme.
- Images and content should be configured through Shopify admin/theme editor settings and/or metafields.
- If a design requires admin-configured content, the agent must:
  1) finish writing the theme files first
  2) output clear human admin steps
  3) pause until the human confirms updates are done
  4) resume verification

---

## Requirements

- macOS
- Docker Desktop
- Shopify CLI access to a store
- A local Shopify theme directory (Horizon or compatible)
- OpenAI-compatible API key

---

## Project Structure

theme-agent/
  agent/            agent runtime and tools
  docker/           Docker and docker-compose config
  tasks/            task.md, context.md, mid-task-changes.md, continue.txt (signal file)
  runs/             per-run artifacts (screenshots, logs, summaries, admin_steps.md)
  README.md

---

## Environment Variables

Required:

- OPENAI_API_KEY
  API key for the LLM provider.

- SHOPIFY_FLAG_STORE
  Shopify store domain or prefix.
  Example: my-store.myshopify.com

- THEME_DIR
  Absolute path on your machine to the local Shopify theme directory.

Optional:

- OPENAI_BASE_URL
  Defaults to https://api.openai.com/v1

- OPENAI_MODEL
  Defaults to gpt-4.1-mini

- OPENAI_TEMPERATURE
  Defaults to 0.2

- SHOPIFY_FLAG_THEME_ID
  Remote theme ID or name to target.
  If not set, Shopify CLI uses a development theme.

- SHOPIFY_CLI_THEME_TOKEN
  Theme Access password for non-interactive authentication.

- SHOPIFY_FLAG_STORE_PASSWORD
  Storefront password if the storefront is locked.

- FIGMA_MCP_CMD
  Command that starts a Figma MCP stdio server.

- SHOPIFY_MCP_CMD
  Command that starts a Shopify Docs MCP stdio server.

---

## One-Time Setup

Create directories to persist Shopify CLI authentication:

mkdir -p .shopify_config .shopify_cache

Set environment variables:

export THEME_DIR="/absolute/path/to/your/theme"
export SHOPIFY_FLAG_STORE="your-store.myshopify.com"
export OPENAI_API_KEY="..."

---

## Login to Shopify (Docker-safe)

Run this once. Authentication is persisted between runs.

docker compose -f docker/docker-compose.yml run --rm theme-agent login --workdir /work/theme

The CLI will print a login URL.
Open it in your macOS browser.
The OAuth callback completes via port 3456.

---

## Validate Setup (Doctor)

docker compose -f docker/docker-compose.yml run --rm theme-agent doctor --workdir /work/theme

---

## Define a Task

Edit:

- tasks/task.md
  Primary task description.

- tasks/context.md
  Optional background or constraints.

- tasks/mid-task-changes.md
  Add changes or corrections while the agent is running.

Optional signal file:

- tasks/continue.txt
  Used to resume after admin updates.
  Put the word "continue" in this file to resume.

---

## Run the Agent (Auto theme dev)

The agent can start `shopify theme dev` automatically if you do not provide --base-url.

docker compose -f docker/docker-compose.yml run --rm theme-agent run \
  --workdir /work/theme \
  --routes /,/products/example-handle,/cart

The agent will:
- start theme dev on port 9292
- run theme check and Playwright
- iterate until complete

---

## Run the Agent (Manual base URL)

If you already have a preview server running, pass the base URL:

docker compose -f docker/docker-compose.yml run --rm theme-agent run \
  --workdir /work/theme \
  --base-url http://127.0.0.1:9292 \
  --routes /,/products/example-handle,/cart

---

## Admin Steps Pause / Resume

If the agent needs content that must be configured in Shopify admin (images, text, metafields, settings):
- it writes runs/<run_id>/admin_steps.md
- it pauses and waits

To resume:
1) perform the admin steps in Shopify
2) set tasks/continue.txt to contain the word "continue"
3) the agent will resume and re-verify

---

## Artifacts

Artifacts are written to runs/<run_id>/:
- verify/ : Playwright screenshots, HTML dumps, logs
- design/ : optional Figma exports (if MCP provides them)
- admin_steps.md : human steps when needed

---

## Design Constraints

- The agent can only read and write inside the theme directory
- Only theme directories are writable: sections/, snippets/, templates/, layout/, assets/, config/, locales/
- The agent cannot write image/video assets into the theme
- The agent must request admin steps for content/images/metafields
- No agent code is injected into the theme

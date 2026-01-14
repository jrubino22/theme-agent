SHELL := /bin/bash

THEME_DIR = /Users/jrubino/Desktop/client-projects/enhanced/enhanced-horizon

# Compose + service
COMPOSE_FILE := docker/docker-compose.yml
COMPOSE := THEME_DIR="$(THEME_DIR)" docker compose -f $(COMPOSE_FILE)
SERVICE := theme-agent


# Default flags you always type
WORKDIR = /work/theme

.PHONY: doctor login run run-nomcp theme-dev shell build rebuild logs down config

doctor:
	$(COMPOSE) run --rm $(SERVICE) doctor --workdir $(WORKDIR)

login:
	$(COMPOSE) run -it --service-ports --entrypoint shopify $(SERVICE) auth login

run:
	$(COMPOSE) run --rm $(SERVICE) run --workdir $(WORKDIR)

# Useful for smoke tests if MCP is flaky:
run-nomcp:
	FIGMA_MCP_CMD= SHOPIFY_MCP_CMD= $(COMPOSE) run --rm $(SERVICE) run --workdir $(WORKDIR)

theme-dev:
	$(COMPOSE) run -it --service-ports $(SERVICE) theme-dev --workdir $(WORKDIR)

shell:
	$(COMPOSE) run -it --entrypoint bash $(SERVICE)

build:
	$(COMPOSE) build $(SERVICE)

rebuild:
	$(COMPOSE) build --no-cache $(SERVICE)

logs:
	$(COMPOSE) logs -f $(SERVICE)

down:
	$(COMPOSE) down

config:
	$(COMPOSE) config | sed -n '/volumes:/,/ports:/p'
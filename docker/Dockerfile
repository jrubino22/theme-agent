FROM mcr.microsoft.com/playwright:v1.49.0-jammy

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip \
    ripgrep \
    ca-certificates curl \
  && rm -rf /var/lib/apt/lists/*

# Shopify CLI (theme)
RUN npm i -g @shopify/cli @shopify/theme

COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt

COPY agent /app/agent
COPY tasks /app/tasks
RUN mkdir -p /app/runs

# Avoid CLI trying to open a browser inside the container.
# It will print the URL; you open it on macOS.
ENV BROWSER=echo

# Create no-op openers to avoid "spawn xdg-open ENOENT" type failures.
RUN printf '#!/bin/sh\necho "Open this URL on your host browser: $*"\nexit 0\n' > /usr/local/bin/xdg-open \
 && chmod +x /usr/local/bin/xdg-open \
 && printf '#!/bin/sh\necho "Open this URL on your host browser: $*"\nexit 0\n' > /usr/local/bin/open \
 && chmod +x /usr/local/bin/open

ENV PYTHONPATH=/app

RUN mkdir -p /app/.config /app/.cache /app/runs \
 && chown -R pwuser:pwuser /app

# Use the Playwright image's non-root user for sane volume permissions on macOS.
USER pwuser

ENTRYPOINT ["python3", "-m", "agent.cli"]
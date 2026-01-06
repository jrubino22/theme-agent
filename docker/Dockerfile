FROM python:3.11-slim

# Basic tooling needed for recon and later steps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ripgrep \
    ca-certificates \
    curl \
    nodejs \
    npm \
  && rm -rf /var/lib/apt/lists/*

# Shopify CLI (v3) + theme plugin via npm
RUN npm install -g @shopify/cli @shopify/theme

WORKDIR /app

# Install python deps first (cache-friendly)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the agent code + tasks (NOT theme)
COPY agent /app/agent
COPY tasks /app/tasks

# Default
CMD ["python", "-m", "agent.cli", "--help"]

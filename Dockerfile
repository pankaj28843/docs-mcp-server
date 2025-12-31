# Use official uv Docker image for Debian (external environment)
FROM ghcr.io/astral-sh/uv:0.9.17-debian

# --- Base system setup (as root) ---
USER root

# Create non-root user for security (before copying source code to avoid cache invalidation)
# Use build args to match host user's UID/GID for volume mount permissions
ARG USER_ID=1000
ARG GROUP_ID=1000
ARG RIPGREP_VERSION=15.0.0
RUN set -eux; \
  # 1) Figure out a group to use for GROUP_ID (reuse if it already exists)
  group_name="$(getent group "${GROUP_ID}" | cut -d: -f1 || true)"; \
  if [ -z "$group_name" ]; then \
    group_name="mcp"; \
    groupadd -g "${GROUP_ID}" "$group_name"; \
  fi; \
  # 2) Create or rename a user to have USER_ID and join GROUP_ID
  if getent passwd "${USER_ID}" >/dev/null; then \
    # A user with this UID already exists — rename it to mcp and move the home
    existing_user="$(getent passwd "${USER_ID}" | cut -d: -f1)"; \
    usermod -l mcp -d /home/mcp -m "$existing_user"; \
    usermod -g "${GROUP_ID}" mcp; \
  else \
    useradd -u "${USER_ID}" -g "${GROUP_ID}" -m -d /home/mcp mcp; \
  fi; \
  chown -R mcp:"${GROUP_ID}" /home/mcp

# uv env
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=300

# System dependencies for Playwright + utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
  curl \
  libasound2 \
  libatk-bridge2.0-0 \
  libatk1.0-0 \
  libatspi2.0-0 \
  libcairo2 \
  libcups2 \
  libdbus-1-3 \
  libdrm2 \
  libgbm1 \
  libnspr4 \
  libnss3 \
  libpango-1.0-0 \
  libxcomposite1 \
  libxdamage1 \
  libxfixes3 \
  libxkbcommon0 \
  libxrandr2 \
  && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
  archive="ripgrep-v${RIPGREP_VERSION}-x86_64-unknown-linux-musl.tar.gz"; \
  curl --fail -L -o "/tmp/${archive}" "https://github.com/microsoft/ripgrep-prebuilt/releases/download/v${RIPGREP_VERSION}/${archive}"; \
  tar -xzf "/tmp/${archive}" -C /tmp; \
  mv /tmp/rg /usr/local/bin/rg; \
  chmod +x /usr/local/bin/rg; \
  rm -rf "/tmp/${archive}" "/tmp/ripgrep-v${RIPGREP_VERSION}-x86_64-unknown-linux-musl"

# Switch to user and set HOME explicitly
USER mcp
ENV HOME=/home/mcp

# Create app dir AS mcp so it's writable without chown
WORKDIR /home/mcp
RUN mkdir -p app
WORKDIR /home/mcp/app

# Copy dependency manifests separately so doc edits do not bust the cache
COPY --chown=mcp:mcp pyproject.toml uv.lock ./

# Create venv + install deps (skip project install so README changes don't break caching)
RUN set -eux; \
  : > README.md; \
  uv sync --no-dev --no-install-project; \
  uv run playwright install chromium

# Copy the source (owned by mcp)
COPY --chown=mcp:mcp src/ ./src/

# Bring over docs after deps are cached to keep README edits cheap
COPY --chown=mcp:mcp README.md ./

# Editable install
RUN uv pip install --no-deps -e .

# Expose default port
EXPOSE 8000

# MCP server env
ENV MCP_HOST=0.0.0.0 \
    MCP_PORT=8000 \
    DOCS_MCP_PRELOAD=true

# Health check
HEALTHCHECK --interval=10s --timeout=10s --start-period=60s --retries=3 \
  CMD curl --silent --fail --noproxy localhost http://localhost:${MCP_PORT}/health || exit 1

# Start the DRF MCP server
CMD [".venv/bin/python", "-m", "docs_mcp_server"]

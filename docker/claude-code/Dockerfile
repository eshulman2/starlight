FROM node:22-slim

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# ── MCP server packages ────────────────────────────────────────────────────────
# MCP servers declared in the YAML are installed automatically at container
# startup by entrypoint.sh — you do NOT need to add them here.
#
# The orchestrator detects the npm package from the 'npx -y <package>' args
# and passes it as STARLIGHT_MCP_PACKAGES to the container. The entrypoint
# runs 'npm install -g <package>' before starting Claude Code.
#
# Pre-install here ONLY if you want to skip the per-run install for speed,
# or if your MCP server can't be installed via npm at runtime (e.g. private
# registry, offline environment):
#
#   RUN npm install -g @modelcontextprotocol/server-github
# ──────────────────────────────────────────────────────────────────────────────

# ── Claude Code skills (plugins) ──────────────────────────────────────────────
# Skills declared with `skills: - id@publisher` in the YAML are resolved from
# the host's ~/.claude/plugins/cache/ and mounted read-only into the container
# by the orchestrator. No installation is needed here.
#
# Skills declared with `github: owner/repo` are git-cloned by the orchestrator
# at evaluation time and also mounted in — no installation needed here either.
#
# The only case where you'd add something here is a skill that can't be
# resolved from the host or GitHub (e.g. a private package):
#
#   COPY ./my-private-skill /home/agent/.claude/plugins/cache/my-org/my-skill/1.0.0
# ──────────────────────────────────────────────────────────────────────────────

# Google Cloud SDK for Vertex AI authentication (Application Default Credentials)
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends curl ca-certificates python3 && \
    curl -sSL https://sdk.cloud.google.com | bash -s -- --disable-prompts --install-dir=/opt && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/google-cloud-sdk/bin:$PATH"

# Run as non-root — required for Claude Code's --dangerously-skip-permissions flag
RUN useradd -m -s /bin/bash agent

# Configure a user-writable npm prefix so 'npm install -g' works for the agent user.
# The entrypoint installs MCP server packages here at startup.
RUN mkdir -p /home/agent/.npm-global && chown -R agent:agent /home/agent/.npm-global

ENV NPM_CONFIG_PREFIX=/home/agent/.npm-global
ENV PATH="/home/agent/.npm-global/bin:$PATH"

# /workspace is where the orchestrator mounts the agent work directory.
# The transcript.jsonl file is written here and read back by the host after the run.
RUN mkdir -p /workspace && chown agent:agent /workspace

# Pre-create ~/.claude so that when Starlight mounts settings.json at
# /home/agent/.claude/settings.json the directory already exists and is owned
# by agent. Without this, Podman creates the parent directory as root, which
# blocks Claude Code from writing its own session files (transcripts, etc).
RUN mkdir -p /home/agent/.claude && chown -R agent:agent /home/agent/.claude

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && chown agent:agent /entrypoint.sh

USER agent
WORKDIR /repo

ENTRYPOINT ["/entrypoint.sh"]

#!/bin/bash
# Starlight Claude Code agent container entrypoint.
#
# What this script does:
#   1. Install any MCP server npm packages declared in the scenario YAML
#      (passed as STARLIGHT_MCP_PACKAGES by the orchestrator)
#   2. Run Claude Code non-interactively on STARLIGHT_TASK_PROMPT
#   3. Copy the session transcript to /workspace/transcript.jsonl so
#      Starlight can extract tool calls and the final response

set -euo pipefail

TASK_PROMPT="${STARLIGHT_TASK_PROMPT:-}"
TRANSCRIPT_DEST="/workspace/transcript.jsonl"

if [ -z "$TASK_PROMPT" ]; then
    echo "ERROR: STARLIGHT_TASK_PROMPT is not set" >&2
    exit 1
fi

# ── Step 1: Install MCP server packages ────────────────────────────────────────
# The orchestrator passes a comma-separated list of npm packages to install.
# These are auto-detected from 'npx -y <package>' args in mcp_servers YAML,
# or set explicitly via the 'install:' field on each MCP server config.
# This means you do NOT need to rebuild the container image to add new servers.
if [ -n "${STARLIGHT_MCP_PACKAGES:-}" ]; then
    echo "=== Installing MCP server packages ==="
    IFS=',' read -ra PACKAGES <<< "$STARLIGHT_MCP_PACKAGES"
    for PKG in "${PACKAGES[@]}"; do
        echo "  npm install -g $PKG"
        npm install -g "$PKG" 2>&1 || echo "WARNING: Failed to install $PKG — server may not work"
    done
    echo "======================================"
fi

# ── Step 2: Run the task ───────────────────────────────────────────────────────
echo "=== Starlight Agent: starting task ==="
echo "Task: $TASK_PROMPT"
echo "======================================"

# Mark the start time so we can find the transcript written by this run
touch /tmp/.starlight_start

# Run Claude Code in non-interactive (print) mode.
# --dangerously-skip-permissions lets the agent use tools without prompting.
# Output is saved to claude_output.txt AND shown in container logs.
# If no JSONL transcript is written (startup failure, MCP connect error, etc.)
# the captured output becomes the agent's response so the GPA judge can explain it.
CLAUDE_OUTPUT_FILE="/workspace/claude_output.txt"
claude -p "$TASK_PROMPT" \
    --dangerously-skip-permissions \
    2>&1 | tee "$CLAUDE_OUTPUT_FILE" || true
chmod 644 "$CLAUDE_OUTPUT_FILE" 2>/dev/null || true

echo "=== Starlight Agent: task complete ==="

# ── Step 3: Export transcript ──────────────────────────────────────────────────
# Claude Code writes JSONL transcripts to ~/.claude/projects/<hash>/<session>.jsonl
TRANSCRIPT=$(find ~/.claude -name "*.jsonl" -newer /tmp/.starlight_start 2>/dev/null \
    | sort | tail -1)

if [ -n "$TRANSCRIPT" ]; then
    mkdir -p "$(dirname "$TRANSCRIPT_DEST")"
    cp "$TRANSCRIPT" "$TRANSCRIPT_DEST"
    chmod 644 "$TRANSCRIPT_DEST"   # make readable by the host orchestrator
    echo "Transcript saved: $TRANSCRIPT_DEST ($(wc -l < "$TRANSCRIPT_DEST") lines)"
else
    echo "WARNING: No transcript found — claude_output.txt has the raw response"
fi

#!/usr/bin/env python3
"""
Starlight Python agent template.

Reads STARLIGHT_TASK_PROMPT, runs a multi-turn agentic loop with tool use,
exports OpenTelemetry spans to the Starlight collector so tool calls appear
in GPA scoring, and prints the final response to stdout.

Customise:
  TOOLS          — tool definitions passed to the model
  execute_tool() — your tool implementations (bash, file I/O, APIs, etc.)
  MODEL          — override via CLAUDE_MODEL env var in the YAML

Authentication (set in the YAML agent env block):
  Vertex AI:        ANTHROPIC_VERTEX_PROJECT_ID, CLOUD_ML_REGION, GOOGLE_APPLICATION_CREDENTIALS
  Direct Anthropic: ANTHROPIC_API_KEY
"""

import json
import os
import subprocess
import sys

# ── OpenTelemetry setup ────────────────────────────────────────────────────────
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

OTLP_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
SERVICE_NAME  = os.environ.get("OTEL_SERVICE_NAME", "python-agent")

provider = TracerProvider()
if OTLP_ENDPOINT:
    exporter = OTLPSpanExporter(endpoint=f"{OTLP_ENDPOINT}/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(exporter))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(SERVICE_NAME)

# ── Anthropic client ───────────────────────────────────────────────────────────
import anthropic

VERTEX_PROJECT = os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID", "")
if VERTEX_PROJECT:
    client = anthropic.AnthropicVertex(
        project_id=VERTEX_PROJECT,
        region=os.environ.get("CLOUD_ML_REGION", "us-east5"),
    )
else:
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

MODEL         = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
TASK_PROMPT   = os.environ.get("STARLIGHT_TASK_PROMPT", "")
MAX_TOKENS    = int(os.environ.get("AGENT_MAX_TOKENS", "4096"))
MAX_TURNS     = int(os.environ.get("AGENT_MAX_TURNS", "20"))

if not TASK_PROMPT:
    print("ERROR: STARLIGHT_TASK_PROMPT is not set", file=sys.stderr)
    sys.exit(1)

# ── Tool definitions ───────────────────────────────────────────────────────────
# Add, remove, or replace tools to match your agent's capabilities.

TOOLS = [
    {
        "name": "bash",
        "description": (
            "Run a shell command and return stdout + stderr. "
            "Working directory is /repo (your mounted codebase)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to run"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the contents of a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or relative file path"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file, creating it if it does not exist.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path":    {"type": "string", "description": "File path to write"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        },
    },
]


# ── Tool execution ─────────────────────────────────────────────────────────────

def execute_tool(name: str, tool_input: dict) -> str:
    """Execute a tool call and return its output as a string."""
    try:
        if name == "bash":
            result = subprocess.run(
                tool_input["command"],
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                cwd="/repo",
            )
            output = result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"
            if result.returncode != 0:
                output += f"\n[exit code: {result.returncode}]"
            return output or "(no output)"

        elif name == "read_file":
            path = tool_input["path"]
            try:
                return open(path).read()
            except FileNotFoundError:
                return f"Error: file not found: {path}"

        elif name == "write_file":
            path = tool_input["path"]
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w") as f:
                f.write(tool_input["content"])
            return f"Written {len(tool_input['content'])} bytes to {path}"

        else:
            return f"Unknown tool: {name}"

    except Exception as exc:
        return f"Tool error: {exc}"


# ── Agentic loop ───────────────────────────────────────────────────────────────

messages = [{"role": "user", "content": TASK_PROMPT}]
turns = 0

while turns < MAX_TURNS:
    turns += 1

    with tracer.start_as_current_span("llm_call") as span:
        span.set_attribute("llm.model", MODEL)
        span.set_attribute("llm.turn", turns)

        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            tools=TOOLS,
            messages=messages,
        )
        span.set_attribute("llm.stop_reason", response.stop_reason)
        span.set_attribute("llm.input_tokens", response.usage.input_tokens)
        span.set_attribute("llm.output_tokens", response.usage.output_tokens)

    # Append the full assistant response to history
    messages.append({"role": "assistant", "content": response.content})

    if response.stop_reason == "end_turn":
        # Print the final text to stdout (captured as final_response by Starlight)
        for block in response.content:
            if hasattr(block, "text"):
                print(block.text)
        break

    if response.stop_reason == "tool_use":
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            with tracer.start_as_current_span(f"tool.{block.name}") as span:
                span.set_attribute("tool.name", block.name)
                span.set_attribute("tool.input", json.dumps(block.input))

                result = execute_tool(block.name, block.input)
                span.set_attribute("tool.output", result[:2000])

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})

    else:
        # max_tokens or unexpected stop
        print(f"[agent stopped: {response.stop_reason}]", file=sys.stderr)
        break

else:
    print(f"[agent reached max turns: {MAX_TURNS}]", file=sys.stderr)

provider.shutdown()

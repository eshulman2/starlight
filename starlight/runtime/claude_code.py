import json
import logging
from pathlib import Path
from typing import Optional
from starlight.config import AgentConfig
from starlight.models import ToolCall
from starlight.runtime.base import AgentAdapter

CLAUDE_CODE_IMAGE = "starlight-claude-code:local"

log = logging.getLogger(__name__)


class ClaudeCodeAdapter(AgentAdapter):
    def get_image(self, config: AgentConfig) -> str:
        return CLAUDE_CODE_IMAGE

    def inject_env(self, config: AgentConfig, collector_endpoint: str) -> dict[str, str]:
        return {
            "OTEL_EXPORTER_OTLP_ENDPOINT": collector_endpoint,
            "OTEL_SERVICE_NAME": config.id,
            "CLAUDE_MODEL": config.model or "",
        }

    # get_volumes() is intentionally not overridden here.
    # MCP server configuration is generated from agent.mcp_servers in the orchestrator
    # and written as a fresh settings.json — no host ~/.claude files are used.

    def extract_from_transcript(
        self, transcript_path: Path
    ) -> tuple[list[ToolCall], Optional[str]]:
        """Parse a Claude Code JSONL transcript into ToolCall list + final response."""
        entries = [
            json.loads(line)
            for line in transcript_path.read_text().splitlines()
            if line.strip()
        ]

        tool_calls: list[ToolCall] = []
        pending_inputs: dict[str, dict] = {}  # tool_use_id -> input
        pending_names: dict[str, str] = {}    # tool_use_id -> name
        final_response: Optional[str] = None

        for entry in entries:
            # Claude Code v2 JSONL: messages are nested under a "message" key.
            # Outer "type" is "user"/"assistant"/"queue-operation"/"summary".
            message = entry.get("message", entry)  # fall back to entry itself for older format
            role = message.get("role")
            content = message.get("content", [])
            if not isinstance(content, list):
                continue

            if role == "assistant":
                text_parts = []
                for block in content:
                    if block.get("type") == "tool_use":
                        tid = block["id"]
                        pending_inputs[tid] = block.get("input", {})
                        pending_names[tid] = block.get("name", "")
                    elif block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                if text_parts:
                    final_response = " ".join(text_parts)

            elif role == "user":
                for block in content:
                    if block.get("type") == "tool_result":
                        tid = block.get("tool_use_id", "")
                        if tid not in pending_names:
                            # orphaned tool_result with no matching tool_use — skip
                            continue
                        output = block.get("content", "")
                        if isinstance(output, list):
                            output = " ".join(
                                b.get("text", "") for b in output if b.get("type") == "text"
                            )
                        tool_calls.append(ToolCall(
                            name=pending_names.pop(tid, "unknown"),
                            input=pending_inputs.pop(tid, {}),
                            output=str(output),
                            duration_ms=0,  # transcripts don't include timing
                        ))

        if pending_names:
            import logging
            logging.getLogger(__name__).warning(
                "Transcript has %d unmatched tool_use entries: %s",
                len(pending_names), list(pending_names.values())
            )

        return tool_calls, final_response

    def post_process(
        self, container_id: str, work_dir: Path, config: AgentConfig, collector_endpoint: str
    ) -> None:
        # Tool calls are read directly from the transcript in the orchestrator's
        # _run_agent method, so OTel export is not needed for Claude Code.
        # The collector_endpoint is only reachable from inside the container network,
        # not from the host process that calls post_process.
        pass

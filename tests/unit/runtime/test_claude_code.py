import json
import pytest
from pathlib import Path
from starlight.runtime.claude_code import ClaudeCodeAdapter
from starlight.config import AgentConfig

SAMPLE_TRANSCRIPT = [
    {"role": "user", "content": [{"type": "text", "text": "Find bugs"}]},
    {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "I'll look at the code."},
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/app/main.py"}},
        ],
    },
    {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "def foo(): pass"}],
    },
    {"role": "assistant", "content": [{"type": "text", "text": "Found a bug in foo."}]},
]

def make_agent_config():
    return AgentConfig(
        id="agent-a", runtime="claude-code", model="claude-opus-4-8",
        env={"ANTHROPIC_API_KEY": "sk-test"}
    )

def test_extract_tool_calls(tmp_path):
    transcript_file = tmp_path / "session.jsonl"
    transcript_file.write_text("\n".join(json.dumps(e) for e in SAMPLE_TRANSCRIPT))

    adapter = ClaudeCodeAdapter()
    tool_calls, final = adapter.extract_from_transcript(transcript_file)

    assert len(tool_calls) == 1
    assert tool_calls[0].name == "Read"
    assert tool_calls[0].input == {"file_path": "/app/main.py"}
    assert tool_calls[0].output == "def foo(): pass"
    assert "Found a bug" in final

def test_inject_env_adds_otel_vars():
    adapter = ClaudeCodeAdapter()
    config = make_agent_config()
    env = adapter.inject_env(config, collector_endpoint="http://collector:4318")
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://collector:4318"
    assert env["OTEL_SERVICE_NAME"] == "agent-a"

def test_get_image_uses_standard_image():
    adapter = ClaudeCodeAdapter()
    config = make_agent_config()
    image = adapter.get_image(config)
    assert "claude" in image.lower() or "starlight" in image.lower()

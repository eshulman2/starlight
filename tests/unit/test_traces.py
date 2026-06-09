import json
import pytest
from pathlib import Path
from starlight.traces import parse_traces_file

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_parse_traces_file():
    runs = parse_traces_file(FIXTURES / "sample-traces.json")
    assert "agent-a" in runs
    tool_calls = runs["agent-a"]
    assert len(tool_calls) == 1
    assert tool_calls[0].name == "Read"
    assert tool_calls[0].input == {"file_path": "/app/main.py"}
    assert tool_calls[0].output == "def foo(): pass"
    assert tool_calls[0].duration_ms == 500


def test_parse_missing_file_returns_empty(tmp_path):
    runs = parse_traces_file(tmp_path / "nonexistent.json")
    assert runs == {}

import os
import pytest
from pathlib import Path
from pydantic import ValidationError
from starlight.config import load_scenario, ScenarioConfig

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture(autouse=True)
def default_test_key(monkeypatch):
    """Set TEST_KEY by default so smoke.yaml can be loaded in basic tests."""
    monkeypatch.setenv("TEST_KEY", "sk-default-test")


def test_load_valid_scenario():
    scenario = load_scenario(FIXTURES / "smoke.yaml")
    assert scenario.name == "Smoke Test"
    assert len(scenario.tasks) == 1
    assert len(scenario.agents) == 2

def test_env_var_interpolation(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "sk-test-123")
    scenario = load_scenario(FIXTURES / "smoke.yaml")
    assert scenario.agents[0].env["ANTHROPIC_API_KEY"] == "sk-test-123"

def test_missing_env_var_raises(monkeypatch):
    monkeypatch.delenv("TEST_KEY", raising=False)
    with pytest.raises(ValueError, match="not set"):
        load_scenario(FIXTURES / "smoke.yaml")

def test_too_many_agents_raises(tmp_path):
    yaml_content = """
version: "1"
name: Too Many
tasks:
  - id: t1
    prompt: test
    ground_truth: ok
agents:
  - {id: a, runtime: claude-code, model: claude-sonnet-4-6, env: {}}
  - {id: b, runtime: claude-code, model: claude-sonnet-4-6, env: {}}
  - {id: c, runtime: claude-code, model: claude-sonnet-4-6, env: {}}
  - {id: d, runtime: claude-code, model: claude-sonnet-4-6, env: {}}
"""
    p = tmp_path / "bad.yaml"
    p.write_text(yaml_content)
    with pytest.raises(ValidationError):
        load_scenario(p)

def test_claude_code_requires_model(tmp_path):
    yaml_content = """
version: "1"
name: Bad
tasks:
  - {id: t1, prompt: test, ground_truth: ok}
agents:
  - {id: a, runtime: claude-code, env: {}}
"""
    p = tmp_path / "bad.yaml"
    p.write_text(yaml_content)
    with pytest.raises(ValidationError, match="model"):
        load_scenario(p)

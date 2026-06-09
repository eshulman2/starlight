import os
import pytest
from click.testing import CliRunner
from starlight.cli import main

pytestmark = pytest.mark.integration


@pytest.fixture
def echo_scenario(tmp_path, echo_agent_image, container_runtime):
    yaml = f"""
version: "1"
name: Echo Integration Test

tasks:
  - id: echo-task
    prompt: "Say hello"
    ground_truth: "Agent says hello"
    timeout_minutes: 2

agents:
  - id: echo-a
    runtime: custom
    image: {echo_agent_image}
    env:
      OTEL_EXPORTER_OTLP_ENDPOINT: "http://starlight-collector:4318"
  - id: echo-b
    runtime: custom
    image: {echo_agent_image}
    env:
      OTEL_EXPORTER_OTLP_ENDPOINT: "http://starlight-collector:4318"

evaluation:
  judge_model: claude-sonnet-4-6
  pass_threshold: 0.0

container:
  runtime: {container_runtime}

output:
  format: json
  file: {tmp_path}/results.json
"""
    f = tmp_path / "echo.yaml"
    f.write_text(yaml)
    return f


def test_full_run_produces_results(echo_scenario, tmp_path):
    """Run two echo agents and verify results.json is produced."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["run", str(echo_scenario), "--output", "json"],
        env={"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "sk-test")},
    )
    assert result.exit_code in (0, 1)  # 1 is OK if threshold not met
    results_file = tmp_path / "results.json"
    assert results_file.exists(), f"results.json not created. CLI output:\n{result.output}"
    import json
    data = json.loads(results_file.read_text())
    assert data["scenario_name"] == "Echo Integration Test"
    assert len(data["task_results"]) == 1
    assert "echo-a" in data["task_results"][0]["gpa_scores"]
    assert "echo-b" in data["task_results"][0]["gpa_scores"]

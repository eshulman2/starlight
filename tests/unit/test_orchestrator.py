import pytest
from unittest.mock import MagicMock, patch, call
from pathlib import Path
from starlight.orchestrator import Orchestrator
from starlight.config import ScenarioConfig, TaskConfig, AgentConfig, EvaluationConfig, ContainerConfig, OutputConfig

def make_scenario():
    return ScenarioConfig(
        name="Test",
        tasks=[TaskConfig(id="t1", prompt="Do thing", ground_truth="Thing done")],
        agents=[
            AgentConfig(id="agent-a", runtime="claude-code", model="claude-sonnet-4-6", env={}),
        ],
        evaluation=EvaluationConfig(judge_model="claude-sonnet-4-6", pass_threshold=2.0),
        container=ContainerConfig(runtime="docker"),
        output=OutputConfig(),
    )

def make_mock_runtime():
    r = MagicMock()
    r.run_container.return_value = "cid-123"
    r.wait_container.return_value = 0
    r.get_logs.return_value = "agent logs"
    return r

def test_orchestrator_creates_network(tmp_path):
    runtime = make_mock_runtime()
    orchestrator = Orchestrator(runtime=runtime, work_dir=tmp_path)
    scenario = make_scenario()
    with patch("starlight.orchestrator.CollectorSidecar"), \
         patch("starlight.orchestrator.get_adapter"), \
         patch("starlight.orchestrator.GpaEvaluator"), \
         patch("starlight.orchestrator.parse_traces_file", return_value={}):
        orchestrator.run(scenario)
    runtime.create_network.assert_called_once()

def test_orchestrator_removes_network_on_completion(tmp_path):
    runtime = make_mock_runtime()
    orchestrator = Orchestrator(runtime=runtime, work_dir=tmp_path)
    with patch("starlight.orchestrator.CollectorSidecar"), \
         patch("starlight.orchestrator.get_adapter"), \
         patch("starlight.orchestrator.GpaEvaluator"), \
         patch("starlight.orchestrator.parse_traces_file", return_value={}):
        orchestrator.run(make_scenario())
    runtime.remove_network.assert_called_once()

def test_orchestrator_removes_network_on_error(tmp_path):
    runtime = make_mock_runtime()
    runtime.run_container.side_effect = RuntimeError("container failed")
    orchestrator = Orchestrator(runtime=runtime, work_dir=tmp_path)
    with patch("starlight.orchestrator.CollectorSidecar"), \
         patch("starlight.orchestrator.get_adapter"), \
         pytest.raises(RuntimeError):
        orchestrator.run(make_scenario())
    runtime.remove_network.assert_called_once()

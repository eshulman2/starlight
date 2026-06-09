import json
from pathlib import Path
from click.testing import CliRunner
from unittest.mock import patch, MagicMock
from starlight.cli import main
from starlight.models import GpaReport, TaskResult, GpaScore, AgentRun

FIXTURES = Path(__file__).parent.parent / "fixtures"

def make_mock_report():
    score = GpaScore(
        goal_fulfillment=3, plan_quality=2, tool_selection=3,
        plan_adherence=3, tool_calling=2, logical_consistency=3, execution_efficiency=2,
        rationales={}, reasoning={},
    )
    run = AgentRun("agent-a", "t1", 0, [], "done", 1000)
    tr = TaskResult("t1", "Find bugs", "Issues filed", [run], {"agent-a": score})
    return GpaReport("Test", [tr])

def test_run_command_succeeds(monkeypatch, tmp_path):
    runner = CliRunner()
    monkeypatch.setenv("TEST_KEY", "sk-test")
    mock_report = make_mock_report()
    with patch("starlight.cli.get_runtime"), \
         patch("starlight.cli.Orchestrator") as MockOrch:
        MockOrch.return_value.run.return_value = mock_report
        result = runner.invoke(main, ["run", str(FIXTURES / "smoke.yaml"),
                                       "--output", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["scenario_name"] == "Test"

def test_run_dry_run_prints_plan_and_exits(monkeypatch):
    runner = CliRunner()
    monkeypatch.setenv("TEST_KEY", "sk-test")
    with patch("starlight.cli.get_runtime"):
        result = runner.invoke(main, ["run", str(FIXTURES / "smoke.yaml"), "--dry-run"])
    assert result.exit_code == 0
    assert "dry run" in result.output.lower() or "agent" in result.output.lower()

def test_run_missing_file_exits_nonzero():
    runner = CliRunner()
    result = runner.invoke(main, ["run", "nonexistent.yaml"])
    assert result.exit_code != 0

def test_run_exits_1_when_below_threshold(monkeypatch):
    runner = CliRunner()
    monkeypatch.setenv("TEST_KEY", "sk-test")
    bad_score = GpaScore(
        goal_fulfillment=1, plan_quality=1, tool_selection=1,
        plan_adherence=1, tool_calling=1, logical_consistency=1, execution_efficiency=1,
        rationales={}, reasoning={},
    )
    run = AgentRun("agent-a", "t1", 0, [], "failed", 1000)
    tr = TaskResult("t1", "Find bugs", "Issues filed", [run], {"agent-a": bad_score})
    low_report = GpaReport("Test", [tr])
    with patch("starlight.cli.get_runtime"), \
         patch("starlight.cli.Orchestrator") as MockOrch:
        MockOrch.return_value.run.return_value = low_report
        result = runner.invoke(main, ["run", str(FIXTURES / "smoke.yaml"),
                                       "--output", "json"])
    assert result.exit_code == 1

import pytest
from unittest.mock import MagicMock, patch
from starlight.evaluator import GpaEvaluator, METRICS
from starlight.models import AgentRun, ToolCall, GpaScore, TaskResult
from starlight.config import TaskConfig

def make_agent_run(agent_id="agent-a"):
    return AgentRun(
        agent_id=agent_id, task_id="t1", exit_code=0,
        tool_calls=[ToolCall("Read", {"file_path": "/f"}, "content", 100)],
        final_response="Found 3 bugs and filed issues.", duration_ms=3000,
    )

def make_task_config():
    return TaskConfig(id="t1", prompt="Find bugs", ground_truth="Three GitHub issues filed")

def fake_api_response(score=3, rationale="All good.", reasoning="Agent performed well."):
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock()]
    mock_resp.content[0].text = (
        f'{{"score": {score}, "rationale": "{rationale}", "reasoning": "{reasoning}"}}'
    )
    return mock_resp

def test_metrics_list_has_seven_entries():
    assert len(METRICS) == 7

def test_evaluate_returns_gpa_score(monkeypatch):
    evaluator = GpaEvaluator(judge_model="claude-sonnet-4-6", api_key="sk-test")
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_api_response()
    monkeypatch.setattr(evaluator, "_client", mock_client)

    run = make_agent_run()
    task = make_task_config()
    score = evaluator.evaluate(run=run, task=task)

    assert isinstance(score, GpaScore)
    assert score.goal_fulfillment == 3
    assert "All good" in score.rationales["goal_fulfillment"]
    assert mock_client.messages.create.call_count == 7  # one call per metric

def test_failed_run_returns_none_scores():
    evaluator = GpaEvaluator(judge_model="claude-sonnet-4-6", api_key="sk-test")
    run = AgentRun(agent_id="a", task_id="t1", exit_code=1,
                   tool_calls=[], final_response=None, duration_ms=0,
                   error="Container timed out")
    task = make_task_config()
    score = evaluator.evaluate(run=run, task=task)

    assert score.goal_fulfillment is None
    assert score.gpa == 0.0

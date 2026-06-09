import pytest
from starlight.models import ToolCall, AgentRun, TaskResult, GpaScore, GpaReport


def test_tool_call_creation():
    tc = ToolCall(name="Read", input={"file_path": "/x"}, output="contents", duration_ms=100)
    assert tc.name == "Read"
    assert tc.duration_ms == 100


def test_agent_run_defaults():
    run = AgentRun(agent_id="a", task_id="t1", exit_code=0, tool_calls=[], final_response="done", duration_ms=500)
    assert run.exit_code == 0
    assert run.tool_calls == []


def test_gpa_score_average():
    score = GpaScore(
        goal_fulfillment=3, plan_quality=2, tool_selection=3,
        plan_adherence=3, tool_calling=2, logical_consistency=3,
        execution_efficiency=2,
    )
    assert score.gpa == pytest.approx(2.571, rel=1e-2)


def test_gpa_score_partial_metrics():
    score = GpaScore(goal_fulfillment=3, plan_quality=None, tool_selection=2,
                     plan_adherence=None, tool_calling=None,
                     logical_consistency=3, execution_efficiency=2)
    assert score.gpa == pytest.approx(2.5, rel=1e-2)


def test_gpa_score_all_none_returns_zero():
    score = GpaScore(
        goal_fulfillment=None, plan_quality=None, tool_selection=None,
        plan_adherence=None, tool_calling=None,
        logical_consistency=None, execution_efficiency=None,
    )
    assert score.gpa == 0.0

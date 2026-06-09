import json
from starlight.report import render_terminal, render_json
from starlight.models import AgentRun, GpaScore, TaskResult, GpaReport, ToolCall

def make_score(gf=3, pq=2, ts=3, pa=3, tc=2, lc=3, ee=2):
    return GpaScore(
        goal_fulfillment=gf, plan_quality=pq, tool_selection=ts,
        plan_adherence=pa, tool_calling=tc, logical_consistency=lc,
        execution_efficiency=ee,
        rationales={"plan_quality": "Skipped error enumeration."},
        reasoning={"plan_quality": "The agent did not enumerate error cases before searching."},
    )

def make_report():
    run_a = AgentRun("agent-a", "t1", 0, [], "Done.", 5000)
    run_b = AgentRun("agent-b", "t1", 0, [], "Done.", 6000)
    task_result = TaskResult(
        task_id="t1", task_prompt="Find bugs",
        ground_truth="Three issues filed",
        agent_runs=[run_a, run_b],
        gpa_scores={"agent-a": make_score(), "agent-b": make_score(gf=2, ts=1, tc=1, ee=1)},
    )
    return GpaReport(scenario_name="Smoke Test", task_results=[task_result])

def test_render_json_structure():
    report = make_report()
    output = render_json(report)
    data = json.loads(output)
    assert data["scenario_name"] == "Smoke Test"
    assert len(data["task_results"]) == 1
    assert "agent-a" in data["task_results"][0]["gpa_scores"]

def test_render_json_includes_gpa_values():
    report = make_report()
    data = json.loads(render_json(report))
    score_a = data["task_results"][0]["gpa_scores"]["agent-a"]
    assert score_a["goal_fulfillment"] == 3
    assert "gpa" in score_a

def test_render_terminal_returns_string():
    report = make_report()
    output = render_terminal(report)
    assert isinstance(output, str)
    assert "agent-a" in output
    assert "agent-b" in output
    assert "Smoke Test" in output

def test_render_terminal_shows_rationale_for_low_scores():
    report = make_report()
    output = render_terminal(report)
    # agent-b scored 1 on tool_selection — rationale should appear
    assert "tool_selection" in output.lower() or "tool selection" in output.lower()

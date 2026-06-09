import json
from typing import Optional
from starlight.models import GpaReport, GpaScore, TaskResult

METRIC_LABELS = {
    "goal_fulfillment": "Goal Fulfillment",
    "plan_quality": "Plan Quality",
    "tool_selection": "Tool Selection",
    "plan_adherence": "Plan Adherence",
    "tool_calling": "Tool Calling",
    "logical_consistency": "Logical Consistency",
    "execution_efficiency": "Execution Efficiency",
}

METRIC_ATTRS = list(METRIC_LABELS.keys())


def _bar(score: Optional[int], max_score: int = 3) -> str:
    if score is None:
        return "  N/A   ░░░░░░░░"
    filled = round((score / max_score) * 8)
    bar = "█" * filled + "░" * (8 - filled)
    return f"  {score} / {max_score}   {bar}"


def _color(score: Optional[int]) -> str:
    if score is None:
        return "dim"
    if score >= 3:
        return "green"
    if score >= 2:
        return "yellow"
    return "red"


def render_terminal(report: GpaReport) -> str:
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text
    from io import StringIO

    buf = StringIO()
    console = Console(file=buf, highlight=False, width=100)

    for task_result in report.task_results:
        console.print(f"\n[bold cyan]{report.scenario_name}  ·  Task: {task_result.task_id}[/]")
        console.rule(style="dim")

        agent_ids = [run.agent_id for run in task_result.agent_runs]
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        table.add_column("Metric", style="dim", min_width=24)
        for aid in agent_ids:
            table.add_column(aid, min_width=22)

        for attr in METRIC_ATTRS:
            label = METRIC_LABELS[attr]
            row = [label]
            for aid in agent_ids:
                score_obj = task_result.gpa_scores.get(aid)
                score = getattr(score_obj, attr, None) if score_obj else None
                color = _color(score)
                row.append(Text(_bar(score), style=color))
            table.add_row(*row)

        # GPA total row
        gpa_row = ["[bold]GPA Score[/]"]
        for aid in agent_ids:
            score_obj = task_result.gpa_scores.get(aid)
            if score_obj:
                gpa = score_obj.gpa
                color = _color(round(gpa))
                symbol = "✓" if gpa >= 2.0 else "✗"
                gpa_row.append(Text(f"  {gpa:.2f} / 3   {symbol}", style=f"bold {color}"))
            else:
                gpa_row.append("  N/A")
        table.add_row(*gpa_row)
        console.print(table)

        # Detail blocks — what happened + rationales for sub-3 scores
        for run in task_result.agent_runs:
            score_obj = task_result.gpa_scores.get(run.agent_id)
            if not score_obj:
                continue

            color = "green" if score_obj.gpa >= 2.5 else ("yellow" if score_obj.gpa >= 1.5 else "red")
            console.print(f"\n  [{color}]▸ {run.agent_id}[/]")

            if run.final_response:
                # Truncate at a whole line boundary so the output doesn't end mid-sentence
                lines = run.final_response.splitlines()
                shown, chars = [], 0
                for line in lines:
                    if chars + len(line) > 400:
                        shown.append("  ...")
                        break
                    shown.append(line)
                    chars += len(line) + 1
                console.print(f"  [dim]{chr(10).join(shown)}[/]")

            any_sub3 = any(
                getattr(score_obj, attr, None) is not None
                and getattr(score_obj, attr) < 3
                for attr in METRIC_ATTRS
            )
            if not any_sub3:
                console.print("  [dim]  All metrics scored 3/3 — use --verbose to see judge reasoning.[/]")

            for attr in METRIC_ATTRS:
                score = getattr(score_obj, attr, None)
                if score is not None and score < 3:
                    rationale = score_obj.rationales.get(attr, "")
                    reasoning = score_obj.reasoning.get(attr, "")
                    label = METRIC_LABELS[attr]
                    color = _color(score)
                    console.print(f"\n  [{color}]  {label} ({score}/3)[/]")
                    if rationale:
                        console.print(f"  [dim]  {rationale}[/]")
                    if reasoning and reasoning != rationale:
                        console.print(f"  [dim]  {reasoning}[/]")

    return buf.getvalue()


def render_json(report: GpaReport) -> str:
    def score_to_dict(s: GpaScore) -> dict:
        d = {attr: getattr(s, attr) for attr in METRIC_ATTRS}
        d["gpa"] = round(s.gpa, 3)
        d["rationales"] = s.rationales
        d["reasoning"] = s.reasoning
        return d

    data = {
        "scenario_name": report.scenario_name,
        "task_results": [
            {
                "task_id": tr.task_id,
                "task_prompt": tr.task_prompt,
                "ground_truth": tr.ground_truth,
                "gpa_scores": {
                    aid: score_to_dict(s)
                    for aid, s in tr.gpa_scores.items()
                },
            }
            for tr in report.task_results
        ],
    }
    return json.dumps(data, indent=2)

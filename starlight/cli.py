import os
import sys
import json
import tempfile
from pathlib import Path
import click
from starlight.config import load_scenario, ScenarioConfig
from starlight.container import get_runtime
from starlight.models import GpaReport
from starlight.orchestrator import Orchestrator
from starlight.report import render_terminal, render_json


def _is_ci() -> bool:
    return any(os.environ.get(v) for v in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "JENKINS_URL"))


def _effective_format(fmt: str) -> str:
    if fmt == "auto":
        return "json" if _is_ci() else "table"
    return fmt


def _all_passed(report: GpaReport, threshold: float) -> bool:
    for tr in report.task_results:
        for score in tr.gpa_scores.values():
            if score.gpa < threshold:
                return False
    return True


@click.group()
def main():
    """Starlight — AI agent evaluation harness."""


@main.command()
@click.argument("scenarios", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("--task", "task_filter", multiple=True, help="Only run tasks with this ID.")
@click.option("--tag", "tag_filter", multiple=True, help="Only run tasks with this tag.")
@click.option("--dry-run", is_flag=True, help="Print execution plan without running containers.")
@click.option("--output", "output_fmt", default="auto",
              type=click.Choice(["auto", "table", "json", "junit"]),
              help="Output format (default: auto-detects CI).")
@click.option("--verbose", is_flag=True, help="Show full judge reasoning for all metrics.")
@click.option("--trace", is_flag=True, help="Show step-by-step tool call log.")
def run(scenarios, task_filter, tag_filter, dry_run, output_fmt, verbose, trace):
    """Run one or more evaluation scenario YAML files."""
    scenario_paths = [Path(s) for s in scenarios]

    loaded = []
    for path in scenario_paths:
        try:
            scenario = load_scenario(path)
        except Exception as e:
            click.echo(f"Error loading {path}: {e}", err=True)
            sys.exit(1)

        # Apply task/tag filters
        filtered_tasks = []
        for task in scenario.tasks:
            if task_filter and task.id not in task_filter:
                continue
            if tag_filter and not any(t in task.tags for t in tag_filter):
                continue
            filtered_tasks.append(task)
        scenario.tasks = filtered_tasks
        loaded.append((path, scenario))

    if dry_run:
        click.echo("Dry run — containers that would be created:\n")
        for path, scenario in loaded:
            click.echo(f"  Scenario: {scenario.name} ({path.name})")
            for task in scenario.tasks:
                for agent in scenario.agents:
                    click.echo(f"    [{agent.runtime}] {agent.id} × task:{task.id}")
        sys.exit(0)

    fmt = _effective_format(output_fmt)
    passed = True

    for path, scenario in loaded:
        if not scenario.tasks:
            continue
        try:
            runtime = get_runtime(scenario.container.runtime)
        except RuntimeError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

        with tempfile.TemporaryDirectory() as work_dir:
            orch = Orchestrator(runtime=runtime, work_dir=Path(work_dir))
            report = orch.run(scenario)

        if not _all_passed(report, scenario.evaluation.pass_threshold):
            passed = False

        output_file = Path(scenario.output.file)
        output_file.write_text(render_json(report))

        if fmt == "table":
            click.echo(render_terminal(report))
        elif fmt == "json":
            click.echo(render_json(report))

    sys.exit(0 if passed else 1)

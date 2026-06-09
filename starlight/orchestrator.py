import json
import logging
import os
import shutil
import stat
import subprocess
import uuid
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


log = logging.getLogger(__name__)


def _relabel_for_container(path: Path) -> None:
    """Set the SELinux context to container_file_t so rootless containers can write.
    No-op on non-SELinux systems or when chcon is unavailable."""
    try:
        subprocess.run(
            ["chcon", "-Rt", "container_file_t", str(path)],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass


def _resolve_skill(skill: "SkillSpec", work_dir: Path) -> tuple[Path | None, str]:
    """Return (host_path, container_path) for a skill, or (None, '') if unavailable.

    Local skills  — looked up in ~/.claude/plugins/cache/<publisher>/<name>/.
                    Mounting the version-parent dir lets Claude Code find any
                    installed version.

    GitHub skills — cloned into work_dir/_skill_<name>/ at evaluation time.
                    This ensures the container always gets a fresh, reproducible copy.
    """
    name, _, publisher = skill.id.partition("@")
    container_base = f"/home/agent/.claude/plugins/cache/{publisher}/{name}"

    if skill.github:
        dest = work_dir / f"_skill_{name}"
        log.info("Cloning skill %s from github.com/%s …", skill.id, skill.github)
        result = subprocess.run(
            ["git", "clone", "--depth=1",
             f"https://github.com/{skill.github}", str(dest)],
            capture_output=True, timeout=120,
        )
        if result.returncode != 0:
            log.warning(
                "Failed to clone skill %s from %s: %s",
                skill.id, skill.github, result.stderr.decode(errors="replace"),
            )
            return None, ""
        _relabel_for_container(dest)
        # Detect version from package.json, fall back to "git"
        pkg = dest / "package.json"
        version = "git"
        if pkg.exists():
            try:
                version = json.loads(pkg.read_text()).get("version", "git")
            except Exception:
                pass
        return dest, f"{container_base}/{version}"

    # Local skill
    if not publisher:
        log.warning("Skill %r has no publisher — expected format 'name@publisher'", skill.id)
        return None, ""
    host_path = Path.home() / ".claude" / "plugins" / "cache" / publisher / name
    if not host_path.exists():
        log.warning(
            "Skill %s not found at %s. Install it with 'claude skill install %s' first.",
            skill.id, host_path, skill.id,
        )
        return None, ""
    _relabel_for_container(host_path)
    return host_path, container_base  # mount version-parent; CC finds the right version

from starlight.collector import CollectorSidecar
from starlight.config import ScenarioConfig, AgentConfig, TaskConfig, SkillSpec
from starlight.container import ContainerRuntime, ContainerSpec
from starlight.evaluator import GpaEvaluator
from starlight.models import AgentRun, TaskResult, GpaReport
from starlight.runtime import get_adapter
from starlight.traces import parse_traces_file


class Orchestrator:
    def __init__(self, runtime: ContainerRuntime, work_dir: Path):
        self._runtime = runtime
        self._work_dir = work_dir

    def run(self, scenario: ScenarioConfig) -> GpaReport:
        run_id = uuid.uuid4().hex[:8]
        network_name = f"starlight-{run_id}"
        # Include run_id in collector name to avoid collisions if two runs are concurrent
        collector_name = f"starlight-collector-{run_id}"
        traces_dir = self._work_dir / run_id / "traces"
        traces_dir.mkdir(parents=True, exist_ok=True)

        collector = None
        # agent_runs_per_task: list of (task, list[AgentRun])
        agent_runs_per_task = []
        try:
            self._runtime.create_network(network_name)
            collector = CollectorSidecar(
                runtime=self._runtime, network=network_name, traces_dir=traces_dir,
                name=collector_name,
            )
            collector.start()
            for task in scenario.tasks:
                agent_runs = self._run_task_agents(
                    task=task,
                    agents=scenario.agents,
                    network=network_name,
                    collector_endpoint=collector.otlp_endpoint,
                )
                agent_runs_per_task.append((task, agent_runs))
        finally:
            if collector is not None:
                collector.stop()  # flush traces to disk before we read them
            self._runtime.remove_network(network_name)

        # Parse traces after collector has stopped (file is fully flushed)
        trace_map = parse_traces_file(traces_dir / "run.json")

        # Run GPA evaluation with complete trace data
        ev = scenario.evaluation
        if ev.provider == "vertex":
            evaluator = GpaEvaluator(
                judge_model=ev.judge_model,
                provider="vertex",
                vertex_project=ev.vertex_project or os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
                vertex_region=ev.vertex_region,
            )
        else:
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if not api_key:
                logging.getLogger(__name__).warning(
                    "ANTHROPIC_API_KEY is not set; GPA evaluation will fail for all metrics"
                )
            evaluator = GpaEvaluator(
                judge_model=ev.judge_model,
                provider="anthropic",
                api_key=api_key,
            )

        task_results = []
        for task, agent_runs in agent_runs_per_task:
            for run in agent_runs:
                if not run.tool_calls and run.agent_id in trace_map:
                    run.tool_calls = trace_map[run.agent_id]
            gpa_scores = {
                run.agent_id: evaluator.evaluate(run=run, task=task)
                for run in agent_runs
            }
            task_results.append(TaskResult(
                task_id=task.id,
                task_prompt=task.prompt,
                ground_truth=task.ground_truth,
                agent_runs=agent_runs,
                gpa_scores=gpa_scores,
            ))

        return GpaReport(scenario_name=scenario.name, task_results=task_results)

    def _run_task_agents(self, task, agents, network, collector_endpoint) -> list[AgentRun]:
        """Run all agents for one task concurrently."""
        agent_runs = []
        with ThreadPoolExecutor(max_workers=len(agents)) as pool:
            futures = {
                pool.submit(self._run_agent, agent, task, network, collector_endpoint): agent
                for agent in agents
            }
            for future in as_completed(futures):
                agent_runs.append(future.result())
        return agent_runs

    def _run_agent(self, agent: AgentConfig, task: TaskConfig, network: str, collector_endpoint: str) -> AgentRun:
        adapter = get_adapter(agent)
        agent_work_dir = self._work_dir / f"{agent.id}-{task.id}"
        agent_work_dir.mkdir(parents=True, exist_ok=True)
        agent_work_dir.chmod(0o777)     # allow any container user to write
        _relabel_for_container(agent_work_dir)  # SELinux: container_file_t

        env = {**agent.env, **adapter.inject_env(agent, collector_endpoint)}
        env["STARLIGHT_TASK_PROMPT"] = task.prompt
        env["STARLIGHT_TASK_ID"] = task.id

        # Tell the entrypoint which npm packages to install for MCP servers.
        # Auto-detected from npx args; overridden by explicit install: field.
        mcp_packages = [
            pkg for srv in agent.mcp_servers.values()
            if (pkg := srv.npm_package())
        ]
        if mcp_packages:
            env["STARLIGHT_MCP_PACKAGES"] = ",".join(mcp_packages)

        # Merge: harness work_dir → /workspace (for transcript), then agent-defined volumes.
        # Files with restrictive permissions (e.g. ADC credentials at mode 600) are copied
        # to the agent work dir with mode 644 so the container user can read them.
        prepared: dict[str, str] = {}
        for host_path, container_path in agent.volumes.items():
            src = Path(host_path)
            if src.is_file() and not (src.stat().st_mode & stat.S_IROTH):
                copy = agent_work_dir / f"_vol_{src.name}"
                shutil.copy2(src, copy)
                copy.chmod(0o644)
                _relabel_for_container(copy)  # SELinux: ensure container can read it
                prepared[str(copy)] = container_path
            else:
                prepared[host_path] = container_path
        # Generate a settings.json from the YAML declaration when the agent uses
        # skills or MCP servers. No host ~/.claude files are used — the container
        # gets exactly what the YAML declares, nothing more.
        if agent.mcp_servers or agent.skills:
            settings: dict = {}
            if agent.skills:
                # Resolve each skill: find locally or clone from GitHub, then mount.
                enabled: dict[str, bool] = {}
                for skill in agent.skills:
                    host_path, container_path = _resolve_skill(skill, agent_work_dir)
                    if host_path:
                        prepared[str(host_path)] = container_path
                        enabled[skill.id] = True
                    else:
                        log.warning("Skill %s could not be resolved; skipping.", skill.id)
                if enabled:
                    settings["enabledPlugins"] = enabled
            if agent.mcp_servers:
                settings["mcpServers"] = {
                    name: {
                        "command": srv.command,
                        "args": srv.args,
                        **({"env": srv.env} if srv.env else {}),
                    }
                    for name, srv in agent.mcp_servers.items()
                }
            settings_file = agent_work_dir / "_claude_settings.json"
            settings_file.write_text(json.dumps(settings, indent=2))
            settings_file.chmod(0o644)
            _relabel_for_container(settings_file)
            prepared[str(settings_file)] = "/home/agent/.claude/settings.json"

        volumes = {str(agent_work_dir): "/workspace", **prepared}

        spec = ContainerSpec(
            image=adapter.get_image(agent),
            name=f"starlight-{agent.id}-{task.id}",
            network=network,
            env=env,
            volumes=volumes,
        )

        start_ms = int(time.time() * 1000)
        container_id = None
        try:
            container_id = self._runtime.run_container(spec)
            try:
                exit_code = self._runtime.wait_container(
                    container_id, timeout_seconds=task.timeout_minutes * 60
                )
            except Exception:
                # Timeout or wait failure: kill the container and mark as failed
                self._runtime.kill_container(container_id)
                return AgentRun(
                    agent_id=agent.id, task_id=task.id, exit_code=1,
                    tool_calls=[], final_response=None,
                    duration_ms=int(time.time() * 1000) - start_ms,
                    error=f"timed out after {task.timeout_minutes} minutes",
                )
            logs = self._runtime.get_logs(container_id)
            # Convert native runtime output to OTel spans before removing container
            adapter.post_process(container_id, agent_work_dir, agent, collector_endpoint)
        finally:
            if container_id is not None:
                self._runtime.remove_container(container_id)

        duration_ms = int(time.time() * 1000) - start_ms

        # For Claude Code, read tool calls and final response directly from the
        # JSONL transcript — more reliable than parsing the last container log line.
        tool_calls: list = []
        final_response: str | None = None
        transcript_path = agent_work_dir / "transcript.jsonl"
        if transcript_path.exists() and hasattr(adapter, "extract_from_transcript"):
            try:
                tool_calls, final_response = adapter.extract_from_transcript(transcript_path)
                logging.getLogger(__name__).debug(
                    "transcript: %d tool calls, response: %.80s",
                    len(tool_calls), final_response or "",
                )
            except Exception as exc:
                logging.getLogger(__name__).warning("Could not parse transcript: %s", exc)

        # Fall back to last log line if no transcript response was found
        if not final_response:
            final_response = logs.strip().splitlines()[-1] if logs.strip() else None

        return AgentRun(
            agent_id=agent.id, task_id=task.id, exit_code=exit_code,
            tool_calls=tool_calls, final_response=final_response, duration_ms=duration_ms,
            error=None if exit_code == 0 else f"exit code {exit_code}",
        )

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ToolCall:
    name: str
    input: dict[str, Any]
    output: str
    duration_ms: int


@dataclass
class AgentRun:
    agent_id: str
    task_id: str
    exit_code: int
    tool_calls: list[ToolCall]
    final_response: Optional[str]
    duration_ms: int
    error: Optional[str] = None  # set when exit_code != 0


@dataclass
class GpaScore:
    goal_fulfillment: Optional[int]
    plan_quality: Optional[int]
    tool_selection: Optional[int]
    plan_adherence: Optional[int]
    tool_calling: Optional[int]
    logical_consistency: Optional[int]
    execution_efficiency: Optional[int]
    rationales: dict[str, str] = field(default_factory=dict)
    reasoning: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        _metric_fields = (
            'goal_fulfillment', 'plan_quality', 'tool_selection',
            'plan_adherence', 'tool_calling', 'logical_consistency',
            'execution_efficiency',
        )
        for name in _metric_fields:
            v = getattr(self, name)
            if v is not None and not (0 <= v <= 3):
                raise ValueError(f"{name} must be 0–3, got {v!r}")

    @property
    def gpa(self) -> float:
        values = [
            v for v in [
                self.goal_fulfillment, self.plan_quality, self.tool_selection,
                self.plan_adherence, self.tool_calling, self.logical_consistency,
                self.execution_efficiency,
            ]
            if v is not None
        ]
        return sum(values) / len(values) if values else 0.0


@dataclass
class TaskResult:
    task_id: str
    task_prompt: str
    ground_truth: str
    agent_runs: list[AgentRun]
    gpa_scores: dict[str, GpaScore] = field(default_factory=dict)  # agent_id -> score


@dataclass
class GpaReport:
    scenario_name: str
    task_results: list[TaskResult]

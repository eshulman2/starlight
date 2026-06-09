import json
from typing import Optional
from starlight.config import TaskConfig
from starlight.models import AgentRun, GpaScore, ToolCall

METRICS = [
    "goal_fulfillment",
    "plan_quality",
    "tool_selection",
    "plan_adherence",
    "tool_calling",
    "logical_consistency",
    "execution_efficiency",
]

METRIC_PROMPTS = {
    "goal_fulfillment": """Evaluate whether the agent's final response fulfills the stated goal.

Goal: {goal}
Ground truth (what success looks like): {ground_truth}
Agent's final response: {final_response}

Score 0-3:
3 - Fully achieves the goal; output matches ground truth
2 - Mostly achieves the goal; minor gaps or inaccuracies
1 - Partially achieves the goal; significant gaps
0 - Does not achieve the goal at all""",

    "plan_quality": """Evaluate the quality of the agent's plan for achieving the goal.

Goal: {goal}
Tool calls made (showing the plan in action): {tool_calls_summary}

Score 0-3:
3 - Excellent decomposition; each subtask has an appropriate tool; nothing missing
2 - Good plan with minor gaps or redundancy
1 - Adequate but missing important subtasks or using mismatched tools
0 - Poor or absent planning; agent acted without decomposing the goal""",

    "tool_selection": """Evaluate whether the agent selected appropriate tools for each subtask.

Goal: {goal}
Tool calls made: {tool_calls_summary}

Score 0-3:
3 - Optimal tool selection throughout; best tool chosen for each step
2 - Good selection with minor suboptimalities
1 - Adequate but frequently suboptimal choices
0 - Consistently wrong tool choices; used tools unfit for the purpose""",

    "plan_adherence": """Evaluate whether the agent followed its apparent plan.

Goal: {goal}
Tool calls in order: {tool_calls_summary}

Score 0-3:
3 - Followed a coherent plan without skipping or reordering logical steps
2 - Minor deviations, well-justified by what the agent discovered
1 - Significant deviations from a logical path; steps reordered without reason
0 - No discernible plan adherence; random-seeming sequence of actions""",

    "tool_calling": """Evaluate the correctness of the agent's tool invocations.

Tool calls with inputs and outputs: {tool_calls_detail}

Score 0-3:
3 - All tool calls use correct parameters; outputs handled appropriately
2 - Minor parameter issues; no hallucinated arguments
1 - Frequent parameter issues or hallucinated arguments; some calls failed
0 - Fundamentally broken tool calls; hallucinated tools or schemas""",

    "logical_consistency": """Evaluate the internal logical consistency of the agent's reasoning.

Goal: {goal}
Tool calls and response: {tool_calls_summary}
Final response: {final_response}

Score 0-3:
3 - Fully consistent; conclusions follow from observations; no contradictions
2 - Minor contradictions or unsupported leaps
1 - Notable contradictions between steps or between steps and conclusions
0 - Fundamentally inconsistent; conclusions contradict observations""",

    "execution_efficiency": """Evaluate whether the agent took a minimal path to achieve the goal.

Goal: {goal}
Tool calls made: {tool_calls_summary}

Score 0-3:
3 - Minimal steps; no redundant calls; each call contributed new information
2 - Minor redundancy; 1-2 unnecessary calls
1 - Significant redundancy; repeated calls returning the same data
0 - Extremely inefficient; most steps added nothing""",
}

SYSTEM_PROMPT = """You are an expert evaluator of AI agent behavior. \
You analyze agent execution traces and score them on specific dimensions.
Always respond with valid JSON in this exact format:
{"score": <integer 0-3>, "rationale": "<one sentence>", "reasoning": "<2-3 sentences>"}"""


def _summarise_tool_calls(tool_calls: list[ToolCall]) -> str:
    lines = []
    for i, tc in enumerate(tool_calls, 1):
        lines.append(f"{i}. {tc.name}({json.dumps(tc.input)}) → {tc.output[:200]}")
    return "\n".join(lines) if lines else "(no tool calls)"


def _detail_tool_calls(tool_calls: list[ToolCall]) -> str:
    lines = []
    for i, tc in enumerate(tool_calls, 1):
        lines.append(
            f"{i}. {tc.name}\n   Input: {json.dumps(tc.input)}\n   Output: {tc.output[:500]}"
        )
    return "\n".join(lines) if lines else "(no tool calls)"


class GpaEvaluator:
    def __init__(
        self,
        judge_model: str,
        provider: str = "anthropic",
        api_key: str = "",
        vertex_project: str = "",
        vertex_region: str = "us-east5",
    ):
        self._model = judge_model
        if provider == "vertex":
            from anthropic import AnthropicVertex
            self._client = AnthropicVertex(project_id=vertex_project, region=vertex_region)
        else:
            import anthropic
            self._client = anthropic.Anthropic(api_key=api_key)

    def evaluate(self, run: AgentRun, task: TaskConfig) -> GpaScore:
        if run.exit_code != 0:
            return GpaScore(
                goal_fulfillment=None, plan_quality=None, tool_selection=None,
                plan_adherence=None, tool_calling=None, logical_consistency=None,
                execution_efficiency=None,
                rationales={"error": run.error or "container failed"},
            )

        context = {
            "goal": task.prompt,
            "ground_truth": task.ground_truth,
            "final_response": run.final_response or "(no response)",
            "tool_calls_summary": _summarise_tool_calls(run.tool_calls),
            "tool_calls_detail": _detail_tool_calls(run.tool_calls),
        }

        scores: dict[str, Optional[int]] = {}
        rationales: dict[str, str] = {}
        reasoning: dict[str, str] = {}

        for metric in METRICS:
            prompt = METRIC_PROMPTS[metric].format(**context)
            try:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=1024,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = response.content[0].text.strip()
                # Strip markdown code fences if the model wrapped the JSON
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                data = json.loads(raw)
                scores[metric] = max(0, min(3, int(data["score"])))
                rationales[metric] = data.get("rationale", "")
                reasoning[metric] = data.get("reasoning", "")
            except (json.JSONDecodeError, KeyError, ValueError):
                scores[metric] = None
                rationales[metric] = "parse error"
                reasoning[metric] = ""
            except Exception as exc:
                scores[metric] = None
                rationales[metric] = f"api error: {exc}"
                reasoning[metric] = ""

        return GpaScore(
            goal_fulfillment=scores["goal_fulfillment"],
            plan_quality=scores["plan_quality"],
            tool_selection=scores["tool_selection"],
            plan_adherence=scores["plan_adherence"],
            tool_calling=scores["tool_calling"],
            logical_consistency=scores["logical_consistency"],
            execution_efficiency=scores["execution_efficiency"],
            rationales=rationales,
            reasoning=reasoning,
        )

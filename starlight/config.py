import os
import re
from pathlib import Path
from typing import Literal, Optional
import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


def _interpolate(value: str) -> str:
    def replace(m):
        var = m.group(1)
        if var not in os.environ:
            raise ValueError(f"Environment variable {var!r} is not set")
        return os.environ[var]
    return re.sub(r'\$\{([^}]+)\}', replace, value)


class TaskConfig(BaseModel):
    id: str
    tags: list[str] = []
    prompt: str
    ground_truth: str
    timeout_minutes: int = 10


class McpServerConfig(BaseModel):
    """MCP server configuration. Two transport types are supported:

    **stdio** (default) — Claude Code launches the server as a local subprocess.
    The binary is installed at container startup automatically.

        mcp_servers:
          jira:
            command: npx
            args: ["-y", "@modelcontextprotocol/server-atlassian"]
            env:
              JIRA_API_TOKEN: ${JIRA_API_TOKEN}

    **http** — Claude Code connects to a remote MCP server over HTTP.
    No binary installation is needed; `command` and `args` are ignored.

        mcp_servers:
          github:
            type: http
            url: https://api.githubcopilot.com/mcp
            headers:
              Authorization: "Bearer ${GITHUB_TOKEN}"
    """
    type: Literal["stdio", "http"] = "stdio"
    # stdio fields
    command: Optional[str] = None
    args: list[str] = []
    env: dict[str, str] = {}
    install: Optional[str] = None   # npm package; auto-detected for npx
    # http fields
    url: Optional[str] = None
    headers: dict[str, str] = {}

    @field_validator("env", mode="before")
    @classmethod
    def interpolate_env(cls, v: dict) -> dict:
        return {k: _interpolate(str(val)) for k, val in (v or {}).items()}

    @field_validator("headers", mode="before")
    @classmethod
    def interpolate_headers(cls, v: dict) -> dict:
        return {k: _interpolate(str(val)) for k, val in (v or {}).items()}

    @model_validator(mode="after")
    def check_type_fields(self):
        if self.type == "stdio" and not self.command:
            raise ValueError("stdio MCP server requires 'command'")
        if self.type == "http" and not self.url:
            raise ValueError("http MCP server requires 'url'")
        return self

    def npm_package(self) -> Optional[str]:
        """Return the npm package to install, or None (http servers need no install)."""
        if self.type == "http":
            return None
        if self.install is not None:
            return self.install or None
        if self.command == "npx":
            for arg in self.args:
                if not arg.startswith("-"):
                    return arg
        return None


class SkillSpec(BaseModel):
    """A Claude Code skill/plugin to enable for an agent.

    Two sources:
      local  — the skill is already installed on the host in ~/.claude/plugins/cache/.
               Starlight mounts it into the container automatically.
               YAML: just write the skill ID as a string, or `id: <id>`.

      github — the skill lives in a GitHub repo. Starlight clones it at
               evaluation time so the container always gets a fresh copy.
               YAML: `id: <name>@<publisher>` + `github: owner/repo`
    """
    id: str                  # Claude Code plugin ID, e.g. "superpowers@claude-plugins-official"
    github: Optional[str] = None  # "owner/repo" — clone from GitHub instead of local cache

    @classmethod
    def from_value(cls, v: "str | dict") -> "SkillSpec":
        if isinstance(v, str):
            return cls(id=v)
        return cls(**v)


class AgentConfig(BaseModel):
    id: str
    runtime: Literal["claude-code", "langchain", "custom"]
    model: Optional[str] = None
    image: Optional[str] = None
    command: Optional[str] = None
    # Claude Code skill/plugin specs. Each skill is either:
    #   - a string (local, found in ~/.claude/plugins/cache/)
    #   - an object with id + github (cloned from GitHub at evaluation time)
    skills: list[SkillSpec] = []
    # MCP servers this agent gets. Each entry is the full launch spec —
    # no host ~/.claude files are used. The binary must exist in the container image.
    mcp_servers: dict[str, McpServerConfig] = {}
    env: dict[str, str] = {}
    volumes: dict[str, str] = {}  # host_path -> container_path

    @field_validator("env", mode="before")
    @classmethod
    def interpolate_env(cls, v: dict) -> dict:
        result = {}
        for k, val in v.items():
            if val is None:
                raise ValueError(f"env key {k!r} has no value (did you forget to set it?)")
            result[k] = _interpolate(str(val))
        return result

    @field_validator("skills", mode="before")
    @classmethod
    def coerce_skills(cls, v: list) -> list:
        return [SkillSpec.from_value(item) for item in (v or [])]

    @field_validator("volumes", mode="before")
    @classmethod
    def interpolate_volumes(cls, v: dict) -> dict:
        return {_interpolate(str(k)): str(val) for k, val in v.items()}

    @model_validator(mode="after")
    def check_runtime_fields(self):
        if self.runtime == "claude-code" and not self.model:
            raise ValueError("claude-code runtime requires 'model'")
        if self.runtime in ("langchain", "custom") and not self.image:
            raise ValueError(f"{self.runtime} runtime requires 'image'")
        return self


class EvaluationConfig(BaseModel):
    provider: Literal["anthropic", "vertex"] = "anthropic"
    judge_model: str = "claude-sonnet-4-6"
    vertex_project: Optional[str] = None
    vertex_region: str = "us-east5"
    metrics: Literal["all"] | list[str] = "all"
    pass_threshold: float = 2.0

    @field_validator("vertex_project", mode="before")
    @classmethod
    def interpolate_vertex_project(cls, v: Optional[str]) -> Optional[str]:
        return _interpolate(v) if v else v

    @model_validator(mode="after")
    def check_vertex_fields(self):
        if self.provider == "vertex" and not self.vertex_project:
            raise ValueError("evaluation.vertex_project is required when provider is 'vertex'")
        return self


class ContainerConfig(BaseModel):
    runtime: Literal["docker", "podman", "auto"] = "auto"
    pull_policy: Literal["always", "never", "if_not_present"] = "if_not_present"


class OutputConfig(BaseModel):
    format: Literal["auto", "table", "json", "junit"] = "auto"
    file: str = "results.json"


class ScenarioConfig(BaseModel):
    version: Literal["1"] = "1"
    name: str
    tasks: list[TaskConfig] = Field(min_length=1)
    agents: list[AgentConfig] = Field(min_length=1, max_length=3)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)

    @model_validator(mode="after")
    def check_unique_ids(self):
        agent_ids = [a.id for a in self.agents]
        if len(agent_ids) != len(set(agent_ids)):
            raise ValueError(f"Duplicate agent ids: {agent_ids}")
        task_ids = [t.id for t in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError(f"Duplicate task ids: {task_ids}")
        return self
    container: ContainerConfig = Field(default_factory=ContainerConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)


def load_scenario(path: Path) -> ScenarioConfig:
    with path.open() as f:
        data = yaml.safe_load(f)
    return ScenarioConfig.model_validate(data)

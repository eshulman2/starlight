from starlight.config import AgentConfig
from starlight.runtime.base import AgentAdapter
from starlight.runtime.claude_code import ClaudeCodeAdapter
from starlight.runtime.langchain import LangChainAdapter
from starlight.runtime.custom import CustomAdapter


def get_adapter(config: AgentConfig) -> AgentAdapter:
    adapters = {
        "claude-code": ClaudeCodeAdapter,
        "langchain": LangChainAdapter,
        "custom": CustomAdapter,
    }
    cls = adapters.get(config.runtime)
    if cls is None:
        raise ValueError(f"Unknown runtime: {config.runtime!r}")
    return cls()

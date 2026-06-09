from starlight.config import AgentConfig
from starlight.runtime.base import AgentAdapter


class CustomAdapter(AgentAdapter):
    def get_image(self, config: AgentConfig) -> str:
        return config.image  # type: ignore[return-value]

    # inject_env and post_process are no-ops: user manages OTEL vars in their YAML env block

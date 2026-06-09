from starlight.config import AgentConfig
from starlight.runtime.base import AgentAdapter


class LangChainAdapter(AgentAdapter):
    def get_image(self, config: AgentConfig) -> str:
        return config.image  # type: ignore[return-value]

    def inject_env(self, config: AgentConfig, collector_endpoint: str) -> dict[str, str]:
        return {
            "OTEL_EXPORTER_OTLP_ENDPOINT": collector_endpoint,
            "OTEL_SERVICE_NAME": config.id,
            "OTEL_TRACES_EXPORTER": "otlp",
        }

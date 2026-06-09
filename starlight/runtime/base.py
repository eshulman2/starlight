from abc import ABC, abstractmethod
from pathlib import Path
from starlight.config import AgentConfig
from starlight.models import ToolCall


class AgentAdapter(ABC):
    @abstractmethod
    def get_image(self, config: AgentConfig) -> str: ...

    def inject_env(self, config: AgentConfig, collector_endpoint: str) -> dict[str, str]:
        return {}

    def get_volumes(self, config: AgentConfig) -> dict[str, str]:
        """Additional host→container volume mounts required by this runtime. Empty by default."""
        return {}

    def post_process(
        self, container_id: str, work_dir: Path, config: AgentConfig, collector_endpoint: str
    ) -> None:
        """Convert native runtime output to OTel spans and send to collector. No-op by default."""
        pass

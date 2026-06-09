from starlight.runtime.langchain import LangChainAdapter
from starlight.config import AgentConfig

def make_agent_config():
    return AgentConfig(
        id="agent-c", runtime="langchain",
        image="my-agent:latest", env={}
    )

def test_inject_env_adds_otel_vars():
    adapter = LangChainAdapter()
    config = make_agent_config()
    env = adapter.inject_env(config, collector_endpoint="http://collector:4318")
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://collector:4318"
    assert env["OTEL_SERVICE_NAME"] == "agent-c"
    assert env["OTEL_TRACES_EXPORTER"] == "otlp"

def test_get_image_uses_config_image():
    adapter = LangChainAdapter()
    config = make_agent_config()
    assert adapter.get_image(config) == "my-agent:latest"

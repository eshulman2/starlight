FROM python:3.12-slim

# Core dependencies: Anthropic SDK, OTel (traces go to the Starlight collector),
# and common agent utilities.
RUN pip install --no-cache-dir \
    anthropic \
    opentelemetry-sdk \
    opentelemetry-exporter-otlp-proto-http

# ── Additional tools ───────────────────────────────────────────────────────────
# Add anything your agent needs here.
# Examples:
#   RUN pip install langchain langgraph       # LangChain / LangGraph agents
#   RUN pip install llama-index               # LlamaIndex
#   RUN pip install requests beautifulsoup4   # web tools
#   RUN apt-get install -y git curl           # shell tools
# ──────────────────────────────────────────────────────────────────────────────

COPY agent.py /agent.py

# Prevent Python output buffering so logs appear immediately in container logs
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "/agent.py"]

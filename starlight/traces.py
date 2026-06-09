import json
from pathlib import Path
from starlight.models import ToolCall


def _get_attr(attributes: list[dict], key: str) -> str:
    for attr in attributes:
        if attr.get("key") == key:
            val = attr.get("value", {})
            return val.get("stringValue", "")
    return ""


def _process_resource_span(resource_span: dict, result: dict[str, list[ToolCall]]) -> None:
    resource_attrs = resource_span.get("resource", {}).get("attributes", [])
    service_name = _get_attr(resource_attrs, "service.name")

    for scope_span in resource_span.get("scopeSpans", []):
        for span in scope_span.get("spans", []):
            attrs = span.get("attributes", [])
            tool_name = _get_attr(attrs, "tool.name")
            if not tool_name:
                continue

            agent_id = _get_attr(attrs, "agent.id") or service_name
            tool_input_raw = _get_attr(attrs, "tool.input")
            try:
                tool_input = json.loads(tool_input_raw)
            except (json.JSONDecodeError, TypeError):
                tool_input = {"raw": tool_input_raw}

            start_ns = int(span.get("startTimeUnixNano", 0))
            end_ns = int(span.get("endTimeUnixNano", 0))
            duration_ms = max(0, (end_ns - start_ns) // 1_000_000)

            tc = ToolCall(
                name=tool_name,
                input=tool_input,
                output=_get_attr(attrs, "tool.output"),
                duration_ms=duration_ms,
            )
            result.setdefault(agent_id, []).append(tc)


def parse_traces_file(path: Path) -> dict[str, list[ToolCall]]:
    """
    Parse an OTLP JSON file (OTel Collector file exporter output).
    Handles both monolithic JSON format (single object with resourceSpans list)
    and NDJSON format (one ResourceSpans JSON object per line).
    Returns an empty dict if the file does not exist or is empty.
    """
    if not path.exists():
        return {}

    content = path.read_text().strip()
    if not content:
        return {}

    result: dict[str, list[ToolCall]] = {}

    # Try monolithic JSON format first
    try:
        data = json.loads(content)
        for resource_span in data.get("resourceSpans", []):
            _process_resource_span(resource_span, result)
        return result
    except json.JSONDecodeError:
        pass

    # Fall back to NDJSON format (one ResourceSpans record per line)
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            # Each line may be a full ExportTraceServiceRequest or just a ResourceSpans
            if "resourceSpans" in record:
                for resource_span in record["resourceSpans"]:
                    _process_resource_span(resource_span, result)
            else:
                # Treat the line itself as a ResourceSpans record
                _process_resource_span(record, result)
        except json.JSONDecodeError:
            continue

    return result

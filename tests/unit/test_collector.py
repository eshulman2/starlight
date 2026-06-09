import pytest
from unittest.mock import MagicMock, patch, call
from pathlib import Path
from starlight.collector import CollectorSidecar

def make_runtime():
    r = MagicMock()
    r.run_container.return_value = "collector-container-id"
    return r

def test_start_creates_container(tmp_path):
    runtime = make_runtime()
    sidecar = CollectorSidecar(runtime=runtime, network="test-net", traces_dir=tmp_path)
    sidecar.start()
    runtime.run_container.assert_called_once()
    spec = runtime.run_container.call_args[0][0]
    assert spec.image == "otel/opentelemetry-collector-contrib:0.104.0"
    assert spec.network == "test-net"
    assert spec.name == "starlight-collector"

def test_stop_removes_container(tmp_path):
    runtime = make_runtime()
    sidecar = CollectorSidecar(runtime=runtime, network="test-net", traces_dir=tmp_path)
    sidecar.start()
    sidecar.stop()
    runtime.remove_container.assert_called_once_with("collector-container-id")

def test_otlp_endpoint_property(tmp_path):
    runtime = make_runtime()
    sidecar = CollectorSidecar(runtime=runtime, network="test-net", traces_dir=tmp_path)
    assert sidecar.otlp_endpoint == "http://starlight-collector:4318"

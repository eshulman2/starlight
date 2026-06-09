import pytest
from unittest.mock import MagicMock, patch
from starlight.container import ContainerSpec, DockerRuntime, PodmanRuntime, get_runtime

def test_container_spec_defaults():
    spec = ContainerSpec(image="alpine:3", name="test", network="net")
    assert spec.env == {}
    assert spec.volumes == {}
    assert spec.command is None

def test_get_runtime_docker(monkeypatch):
    with patch("starlight.container.DockerRuntime") as MockDocker:
        mock = MagicMock()
        mock.is_available.return_value = True
        MockDocker.return_value = mock
        runtime = get_runtime("docker")
        assert runtime is mock

def test_get_runtime_auto_falls_back_to_podman(monkeypatch):
    with patch("starlight.container.DockerRuntime") as MockDocker, \
         patch("starlight.container.PodmanRuntime") as MockPodman:
        docker_mock = MagicMock()
        docker_mock.is_available.return_value = False
        MockDocker.return_value = docker_mock

        podman_mock = MagicMock()
        podman_mock.is_available.return_value = True
        MockPodman.return_value = podman_mock

        runtime = get_runtime("auto")
        assert runtime is podman_mock

def test_get_runtime_auto_raises_when_neither_available():
    with patch("starlight.container.DockerRuntime") as MockDocker, \
         patch("starlight.container.PodmanRuntime") as MockPodman:
        MockDocker.return_value.is_available.return_value = False
        MockPodman.return_value.is_available.return_value = False
        with pytest.raises(RuntimeError, match="Neither Docker nor Podman"):
            get_runtime("auto")

import shutil
import subprocess
import pytest


def _container_cli() -> str:
    """Return 'podman' if available, otherwise 'docker'."""
    if shutil.which("podman"):
        return "podman"
    return "docker"


def _container_runtime() -> str:
    """Return the scenario runtime string matching the available container engine."""
    if shutil.which("podman"):
        return "podman"
    return "docker"


@pytest.fixture(scope="session")
def container_runtime() -> str:
    """The container runtime to use in scenario YAML ('docker' or 'podman')."""
    return _container_runtime()


@pytest.fixture(scope="session")
def echo_agent_image():
    """Build the echo agent image once per test session."""
    image = "starlight-echo-agent:test"
    cli = _container_cli()
    subprocess.run(
        [cli, "build", "-t", image, "tests/fixtures/echo-agent"],
        check=True,
    )
    yield image
    subprocess.run([cli, "rmi", image], check=False)

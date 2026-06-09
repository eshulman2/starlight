import os
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class ContainerSpec:
    image: str
    name: str
    network: str
    env: dict[str, str] = field(default_factory=dict)
    command: Optional[str] = None
    volumes: dict[str, str] = field(default_factory=dict)  # host_path -> container_path


class ContainerRuntime(ABC):
    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def create_network(self, name: str) -> None: ...

    @abstractmethod
    def remove_network(self, name: str) -> None: ...

    @abstractmethod
    def run_container(self, spec: ContainerSpec) -> str: ...

    @abstractmethod
    def wait_container(self, container_id: str, timeout_seconds: int) -> int: ...

    @abstractmethod
    def kill_container(self, container_id: str) -> None: ...

    @abstractmethod
    def remove_container(self, container_id: str) -> None: ...

    @abstractmethod
    def get_logs(self, container_id: str) -> str: ...


class DockerRuntime(ContainerRuntime):
    def __init__(self):
        self._client = None

    def _client_or_raise(self):
        if self._client is None:
            import docker
            self._client = docker.from_env()
        return self._client

    def is_available(self) -> bool:
        try:
            import docker
            docker.from_env().ping()
            return True
        except Exception:
            return False

    def create_network(self, name: str) -> None:
        self._client_or_raise().networks.create(name, driver="bridge")

    def remove_network(self, name: str) -> None:
        try:
            net = self._client_or_raise().networks.get(name)
            net.remove()
        except Exception:
            pass

    def run_container(self, spec: ContainerSpec) -> str:
        client = self._client_or_raise()
        volumes = {h: {"bind": c, "mode": "rw"} for h, c in spec.volumes.items()}
        container = client.containers.run(
            spec.image,
            command=spec.command,
            name=spec.name,
            network=spec.network,
            environment=spec.env,
            volumes=volumes,
            detach=True,
            remove=False,
        )
        return container.id

    def wait_container(self, container_id: str, timeout_seconds: int) -> int:
        client = self._client_or_raise()
        container = client.containers.get(container_id)
        result = container.wait(timeout=timeout_seconds)
        return result["StatusCode"]

    def kill_container(self, container_id: str) -> None:
        try:
            self._client_or_raise().containers.get(container_id).kill()
        except Exception:
            pass

    def remove_container(self, container_id: str) -> None:
        try:
            self._client_or_raise().containers.get(container_id).remove(force=True)
        except Exception:
            pass

    def get_logs(self, container_id: str) -> str:
        container = self._client_or_raise().containers.get(container_id)
        return container.logs().decode("utf-8", errors="replace")


def _podman_socket_path() -> str:
    """Return the expected Podman REST API socket path for the current user."""
    xdg = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return f"{xdg}/podman/podman.sock"


def _ensure_podman_socket() -> str | None:
    """
    Return the Podman socket path, starting the REST API service if needed.
    Returns None if Podman CLI is not installed.
    """
    socket_path = _podman_socket_path()
    if os.path.exists(socket_path):
        return socket_path

    # Confirm the Podman CLI is installed before trying to start the service
    try:
        subprocess.run(["podman", "version"], capture_output=True, check=True, timeout=5)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None

    # Ensure the socket directory exists (Podman doesn't create it)
    os.makedirs(os.path.dirname(socket_path), exist_ok=True)

    # Start the Podman REST API service in the background.
    # --time=60 means the service exits 60 s after the last connection closes.
    subprocess.Popen(
        ["podman", "system", "service", "--time=60", f"unix://{socket_path}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait up to 5 s for the socket file to appear
    for _ in range(50):
        if os.path.exists(socket_path):
            return socket_path
        time.sleep(0.1)

    return None


class PodmanRuntime(ContainerRuntime):
    def __init__(self):
        self._client = None
        self._socket_path: str | None = None

    def _client_or_raise(self):
        if self._client is None:
            import podman
            socket = self._socket_path or _ensure_podman_socket()
            url = f"unix://{socket}" if socket else None
            self._client = podman.PodmanClient(base_url=url) if url else podman.PodmanClient()
        return self._client

    def is_available(self) -> bool:
        socket = _ensure_podman_socket()
        if not socket:
            return False
        try:
            import podman
            client = podman.PodmanClient(base_url=f"unix://{socket}")
            client.version()
            self._socket_path = socket
            return True
        except Exception:
            return False

    def create_network(self, name: str) -> None:
        self._client_or_raise().networks.create(name)

    def remove_network(self, name: str) -> None:
        try:
            self._client_or_raise().networks.get(name).remove()
        except Exception:
            pass

    def run_container(self, spec: ContainerSpec) -> str:
        client = self._client_or_raise()
        volumes = {h: {"bind": c, "mode": "rw"} for h, c in spec.volumes.items()}
        container = client.containers.run(
            spec.image,
            command=spec.command,
            name=spec.name,
            network=spec.network,
            environment=spec.env,
            volumes=volumes,
            detach=True,
        )
        return container.id

    def wait_container(self, container_id: str, timeout_seconds: int) -> int:
        container = self._client_or_raise().containers.get(container_id)
        result = container.wait(timeout=timeout_seconds)
        # Podman SDK returns the exit code directly as an int (not a dict)
        if isinstance(result, int):
            return result
        return result.get("StatusCode", 0)

    def kill_container(self, container_id: str) -> None:
        try:
            self._client_or_raise().containers.get(container_id).kill()
        except Exception:
            pass

    def remove_container(self, container_id: str) -> None:
        try:
            self._client_or_raise().containers.get(container_id).remove(force=True)
        except Exception:
            pass

    def get_logs(self, container_id: str) -> str:
        container = self._client_or_raise().containers.get(container_id)
        return b"".join(container.logs()).decode("utf-8", errors="replace")


def get_runtime(preference: Literal["docker", "podman", "auto"]) -> ContainerRuntime:
    if preference == "docker":
        return DockerRuntime()
    if preference == "podman":
        return PodmanRuntime()
    # auto
    docker = DockerRuntime()
    if docker.is_available():
        return docker
    podman = PodmanRuntime()
    if podman.is_available():
        return podman
    raise RuntimeError("Neither Docker nor Podman is available on this system")

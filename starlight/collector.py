import shutil
import subprocess
import tempfile
from pathlib import Path
from starlight.container import ContainerRuntime, ContainerSpec


def _relabel_for_container(path: Path) -> None:
    try:
        subprocess.run(["chcon", "-Rt", "container_file_t", str(path)],
                       capture_output=True, timeout=5)
    except Exception:
        pass

COLLECTOR_IMAGE = "otel/opentelemetry-collector-contrib:0.104.0"
COLLECTOR_NAME = "starlight-collector"
COLLECTOR_CONFIG = Path(__file__).parent / "runtime" / "collector-config.yaml"


class CollectorSidecar:
    def __init__(self, runtime: ContainerRuntime, network: str, traces_dir: Path, name: str = COLLECTOR_NAME):
        self._runtime = runtime
        self._network = network
        self._traces_dir = traces_dir
        self._name = name
        self._container_id: str | None = None
        self._config_dir: Path | None = None

    @property
    def otlp_endpoint(self) -> str:
        return f"http://{self._name}:4318"

    def start(self) -> None:
        self._config_dir = Path(tempfile.mkdtemp())
        # tempfile.mkdtemp() creates mode 700 (owner-only). The OTel Collector
        # runs as a non-root user and can't enter a 700 directory, so open it up.
        self._config_dir.chmod(0o755)

        config_file = self._config_dir / "config.yaml"
        shutil.copy(COLLECTOR_CONFIG, config_file)
        config_file.chmod(0o644)  # ensure collector can read it

        # SELinux: label both the directory and the file as container_file_t
        _relabel_for_container(self._config_dir)

        self._traces_dir.mkdir(parents=True, exist_ok=True)
        self._traces_dir.chmod(0o777)  # collector writes here
        _relabel_for_container(self._traces_dir)

        spec = ContainerSpec(
            image=COLLECTOR_IMAGE,
            name=self._name,
            network=self._network,
            command="--config=/etc/otel/config.yaml",
            volumes={
                str(self._config_dir): "/etc/otel",
                str(self._traces_dir): "/traces",
            },
        )
        self._container_id = self._runtime.run_container(spec)

    def stop(self) -> None:
        if self._container_id:
            self._runtime.remove_container(self._container_id)
            self._container_id = None
        if self._config_dir and self._config_dir.exists():
            shutil.rmtree(self._config_dir)
            self._config_dir = None

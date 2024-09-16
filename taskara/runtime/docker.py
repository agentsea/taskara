import json
import logging
import os
import signal
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Iterator, List, Optional, Tuple, Type, Union

import docker
from docker.api.client import APIClient
from docker.errors import NotFound
from pydantic import BaseModel
from tqdm import tqdm

from taskara.server.models import (
    V1ResourceLimits,
    V1ResourceRequests,
    V1Tracker,
    V1TrackerRuntimeConnect,
)
from taskara.util import find_open_port

from .base import Tracker, TrackerRuntime

logger = logging.getLogger(__name__)


class DockerConnectConfig(BaseModel):
    timeout: Optional[int] = None
    image: str = "us-central1-docker.pkg.dev/agentsea-dev/taskara/api:latest"


class DockerTrackerRuntime(TrackerRuntime["DockerTrackerRuntime", DockerConnectConfig]):

    def __init__(self, cfg: Optional[DockerConnectConfig] = None) -> None:
        self.docker_socket = self._configure_docker_socket()
        if not cfg:
            cfg = DockerConnectConfig()

        self.img = cfg.image

        self._cfg = cfg
        if cfg.timeout:
            self.client = docker.DockerClient(base_url=self.docker_socket, timeout=cfg.timeout)
        else:
            self.client = docker.DockerClient(base_url=self.docker_socket)
            
        # Verify connection and version
        self._check_version()


    def _configure_docker_socket(self):
        if os.path.exists("/var/run/docker.sock"):
            docker_socket = "unix:///var/run/docker.sock"
        else:
            user = os.environ.get("USER")
            if os.path.exists(f"/Users/{user}/.docker/run/docker.sock"):
                docker_socket = f"unix:///Users/{user}/.docker/run/docker.sock"
            else:
                raise FileNotFoundError(
                    (
                        "Neither '/var/run/docker.sock' nor '/Users/<USER>/.docker/run/docker.sock' are available."
                        "Please make sure you have Docker installed and running."
                    )
                )
        os.environ["DOCKER_HOST"] = docker_socket
        return docker_socket

    def _check_version(self):
            version_info = self.client.version()
            engine_version = next((component['Version'] for component in version_info.get('Components', []) 
                                if component['Name'] == 'Engine'), None)
            if not engine_version:
                raise SystemError("Unable to determine Docker Engine version")
            logger.debug(f"Connected to Docker Engine version: {engine_version}")

    @classmethod
    def name(cls) -> str:
        return "docker"

    @classmethod
    def connect_config_type(cls) -> Type[DockerConnectConfig]:
        return DockerConnectConfig

    def connect_config(self) -> DockerConnectConfig:
        return self._cfg

    @classmethod
    def connect(cls, cfg: DockerConnectConfig) -> "DockerTrackerRuntime":
        return cls(cfg)

    def call(
        self,
        name: str,
        path: str,
        method: str,
        port: int = 9070,
        data: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Tuple[int, str]:
        # Attempt to get the container by name
        try:
            container = self.client.containers.get(name)
        except NotFound:
            raise ValueError(f"Container '{name}' not found")

        # Construct the URL using the mapped port
        url = f"http://localhost:{port}{path}"

        # Create a request object based on the HTTP method
        if method.upper() == "GET":
            if data:
                query_params = urllib.parse.urlencode(data)
                url += f"?{query_params}"
            request = urllib.request.Request(url)
        else:
            request = urllib.request.Request(url, method=method.upper())
            if data:
                request.add_header("Content-Type", "application/json")
                if headers:
                    for k, v in headers.items():
                        request.add_header(k, v)
                request.data = json.dumps(data).encode("utf-8")

        # Send the request and handle the response
        try:
            response = urllib.request.urlopen(request)
            status_code = response.code
            response_text = response.read().decode("utf-8")
            return status_code, response_text
        except urllib.error.HTTPError as e:
            status_code = e.code
            error_message = e.read().decode("utf-8")
            raise SystemError(
                f"Error making HTTP request to Docker container: {status_code}: {error_message}"
            )
        finally:
            try:
                if response:  # type: ignore
                    response.close()
            except:
                pass

    def _ensure_network_exists(self, network_name: str):
        try:
            self.client.networks.get(network_name)
            logger.debug(f"Network '{network_name}' already exists.")
        except NotFound:
            logger.debug(f"Network '{network_name}' not found. Creating network.")
            self.client.networks.create(network_name)
            logger.debug(f"Network '{network_name}' created.")

    def run(
        self,
        name: str,
        env_vars: Optional[dict] = None,
        owner_id: Optional[str] = None,
        labels: Optional[Dict[str, str]] = None,
        resource_requests: V1ResourceRequests = V1ResourceRequests(),
        resource_limits: V1ResourceLimits = V1ResourceLimits(),
        auth_enabled: bool = True,
    ) -> Tracker:

        api_client = docker.APIClient(base_url=self.docker_socket)

        # Pull the image with progress tracking
        pull_image(self.img, api_client)

        _labels = {
            "provisioner": "taskara",
            "server_name": name,
        }
        if labels:
            _labels.update(labels)

        port = find_open_port(9070, 10090)
        if not port:
            raise ValueError("Could not find open port")

        if not env_vars:
            env_vars = {}

        if not auth_enabled:
            env_vars["TASK_SERVER_NO_AUTH"] = "true"

        if not self.img:
            raise ValueError("img not found")

        self._ensure_network_exists("agentsea")
        container = self.client.containers.run(
            self.img,
            network="agentsea",
            ports={9070: port},
            environment=env_vars,
            detach=True,
            labels=_labels,
            name=name,
        )
        if container and type(container) != bytes:
            logger.debug(f"ran container '{container.id}'")  # type: ignore

        return Tracker(
            name=name,
            runtime=self,
            status="running",
            port=port,
            owner_id=owner_id,
        )

    def runtime_local_addr(self, name: str, owner_id: Optional[str] = None) -> str:
        """
        Returns the local address of the agent with respect to the runtime
        """
        instances = Tracker.find(name=name, owner_id=owner_id, runtime_name=self.name())
        if not instances:
            raise ValueError(f"Task server '{name}' not found")
        instance = instances[0]

        return f"http://{instance.name}:{instance.port}"

    def _handle_logs_with_attach(self, server_name: str, attach: bool):
        if attach:
            # Setup the signal handler to catch interrupt signals
            signal.signal(signal.SIGINT, self._signal_handler(server_name))

        try:
            for line in self.logs(server_name, follow=True):
                print(line)
        except KeyboardInterrupt:
            # This block will be executed if SIGINT is caught
            print(f"Interrupt received, stopping logs for '{server_name}'")
            self.delete(server_name)
        except Exception as e:
            print(f"Error while streaming logs: {e}")

    def _signal_handler(self, server_name: str):
        def handle_signal(signum, frame):
            print(f"Signal {signum} received, stopping container '{server_name}'")
            self.delete(server_name)
            sys.exit(1)

        return handle_signal

    def requires_proxy(self) -> bool:
        """Whether this runtime requires a proxy to be used"""
        return False

    def proxy(
        self,
        name: str,
        local_port: Optional[int] = None,
        tracker_port: int = 9070,
        background: bool = True,
        owner_id: Optional[str] = None,
    ) -> Optional[int]:
        return

    def list(
        self, owner_id: Optional[str] = None, source: bool = False
    ) -> List[Tracker]:

        instances = []
        if source:
            label_filter = {"label": "provisioner=taskara"}
            containers = self.client.containers.list(filters=label_filter)

            for container in containers:
                server_name = container.name

                # Extract the TASK_SERVER_PORT environment variable
                env_vars = container.attrs.get("Config", {}).get("Env", [])
                port = next(
                    (
                        int(var.split("=")[1])
                        for var in env_vars
                        if var.startswith("TASK_SERVER_PORT=")
                    ),
                    9070,
                )

                instance = Tracker(
                    name=server_name,
                    runtime=self,
                    port=port,
                    status="running",
                    owner_id=owner_id,
                )
                instances.append(instance)
        else:
            return Tracker.find(owner_id=owner_id, runtime_name=self.name())

        return instances

    def get(
        self, name: str, owner_id: Optional[str] = None, source: bool = False
    ) -> Tracker:
        if source:
            try:
                container = self.client.containers.get(name)

                # Extract the TASK_SERVER_PORT environment variable
                env_vars = container.attrs.get("Config", {}).get("Env", [])
                port = next(
                    (
                        int(var.split("=")[1])
                        for var in env_vars
                        if var.startswith("TASK_SERVER_PORT=")
                    ),
                    9070,
                )

                return Tracker(
                    name=name,
                    runtime=self,
                    status="running",
                    port=port,
                    owner_id=owner_id,
                )
            except NotFound:
                raise ValueError(f"Container '{name}' not found")

        else:
            instances = Tracker.find(
                name=name, owner_id=owner_id, runtime_name=self.name()
            )
            if not instances:
                raise ValueError(f"Task server '{name}' not found")
            return instances[0]

    def delete(self, name: str, owner_id: Optional[str] = None) -> None:
        try:
            # Attempt to get the container by name
            container = self.client.containers.get(name)

            # If found, remove the container
            container.remove(force=True)  # type: ignore
            logger.debug(f"Successfully deleted container: {name}")
        except NotFound:
            # Handle the case where the container does not exist
            logger.debug(f"Container '{name}' does not exist.")
            raise
        except Exception as e:
            # Handle other potential errors
            logger.error(f"Failed to delete container '{name}': {e}")
            raise

    def clean(self, owner_id: Optional[str] = None) -> None:
        # Define the filter for containers with the specific label
        label_filter = {"label": ["provisioner=taskara"]}

        # Use the filter to list containers
        containers = self.client.containers.list(filters=label_filter, all=True)

        # Initialize a list to keep track of deleted container names or IDs
        deleted_containers = []

        for container in containers:
            try:
                container_name_or_id = (
                    container.name  # type: ignore
                )  # or container.id for container ID
                container.remove(force=True)  # type: ignore
                logger.debug(f"Deleted container: {container_name_or_id}")
                deleted_containers.append(container_name_or_id)
            except Exception as e:
                logger.error(f"Failed to delete container: {e}")

        return None

    def logs(
        self, name: str, follow: bool = False, owner_id: Optional[str] = None
    ) -> Union[str, Iterator[str]]:
        """
        Fetches the logs from the specified container. Can return all logs as a single string,
        or stream the logs as a generator of strings.

        Parameters:
            name (str): The name of the container.
            follow (bool): Whether to continuously follow the logs.

        Returns:
            Union[str, Iterator[str]]: All logs as a single string, or a generator that yields log lines.
        """
        try:
            container = self.client.containers.get(name)
            if follow:
                log_stream = container.logs(stream=True, follow=True)  # type: ignore
                return (line.decode("utf-8").strip() for line in log_stream)  # type: ignore
            else:
                return container.logs().decode("utf-8")  # type: ignore
        except NotFound:
            print(f"Container '{name}' does not exist.")
            raise
        except Exception as e:
            print(f"Failed to fetch logs for container '{name}': {e}")
            raise

    def refresh(self, owner_id: Optional[str] = None) -> None:
        """
        Reconciles the database against the Docker containers running.

        Parameters:
            owner_id (Optional[str]): The owner ID to filter the trackers. If None, refreshes for all owners.
        """
        # List all Docker containers with the specific label
        label_filter = {"label": "provisioner=taskara"}
        running_containers = self.client.containers.list(filters=label_filter)
        running_container_names = {container.name for container in running_containers}  # type: ignore

        # List all trackers in the database
        if owner_id:
            db_trackers = Tracker.find(owner_id=owner_id, runtime_name=self.name())
        else:
            db_trackers = Tracker.find(runtime_name=self.name())

        db_tracker_names = {tracker.name for tracker in db_trackers}

        # Determine trackers to add or remove from the database
        containers_to_add = running_container_names - db_tracker_names
        containers_to_remove = db_tracker_names - running_container_names

        # Add new containers to the database
        for container_name in containers_to_add:
            container = self.client.containers.get(container_name)
            env_vars = container.attrs.get("Config", {}).get("Env", [])
            port = next(
                (
                    int(var.split("=")[1])
                    for var in env_vars
                    if var.startswith("TASK_SERVER_PORT=")
                ),
                9070,
            )
            new_tracker = Tracker(
                name=container_name,
                runtime=self,
                port=port,
                status="running",
                owner_id=owner_id,
            )
            new_tracker.save()

        # Remove containers from the database that are no longer running
        for tracker_name in containers_to_remove:
            trackers = Tracker.find(
                name=tracker_name, owner_id=owner_id, runtime_name=self.name()
            )
            if not trackers:
                continue

            tracker = trackers[0]
            tracker.delete()

        logger.debug(
            f"Refresh completed: added {len(containers_to_add)} trackers, removed {len(containers_to_remove)} trackers."
        )


def pull_image(img: str, api_client: APIClient):
    """
    Pulls a Docker image with progress bars for each layer.

    Args:
        img (str): The Docker image to pull.
        api_client (APIClient): The Docker API client.
    """

    print(f"Pulling Docker image '{img}'...")

    progress_bars = {}
    layers = {}

    for line in api_client.pull(img, stream=True, decode=True):
        if "id" in line and "progressDetail" in line:
            layer_id = line["id"]
            progress_detail = line["progressDetail"]
            current = progress_detail.get("current", 0)
            total = progress_detail.get("total", 0)

            if total:
                if layer_id not in layers:
                    progress_bars[layer_id] = tqdm(
                        total=total,
                        desc=f"Layer {layer_id}",
                        leave=False,
                        ncols=100,
                    )
                    layers[layer_id] = 0

                layers[layer_id] = current
                progress_bars[layer_id].n = current
                progress_bars[layer_id].refresh()

    # Close all progress bars
    for bar in progress_bars.values():
        bar.n = bar.total  # Ensure the progress bar is full before closing
        bar.refresh()
        bar.close()

    print("")

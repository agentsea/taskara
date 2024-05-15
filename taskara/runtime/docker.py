from typing import List, Optional, Type, Union, Iterator, Dict, Tuple
import signal
import sys
import urllib.request
import urllib.error
import urllib.parse
import json

import docker
from docker.errors import NotFound
from taskara.util import find_open_port
from pydantic import BaseModel

from taskara.server.models import (
    V1TaskRuntimeConnect,
    V1TaskServer,
    V1ResourceLimits,
    V1ResourceRequests,
)

from .base import TaskServer, TaskServerRuntime


class DockerConnectConfig(BaseModel):
    timeout: Optional[int] = None
    image: str = "us-central1-docker.pkg.dev/agentsea-dev/taskara/api:latest"


class DockerTaskServerRuntime(
    TaskServerRuntime["DockerTaskServerRuntime", DockerConnectConfig]
):

    def __init__(self, cfg: Optional[DockerConnectConfig] = None) -> None:
        if not cfg:
            cfg = DockerConnectConfig()

        self.img = cfg.image

        self._cfg = cfg
        if cfg.timeout:
            self.client = docker.from_env(timeout=cfg.timeout)
        else:
            self.client = docker.from_env()

    @classmethod
    def name(cls) -> str:
        return "docker"

    @classmethod
    def connect_config_type(cls) -> Type[DockerConnectConfig]:
        return DockerConnectConfig

    def connect_config(self) -> DockerConnectConfig:
        return self._cfg

    @classmethod
    def connect(cls, cfg: DockerConnectConfig) -> "DockerTaskServerRuntime":
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

        # Construct the URL using the host network mode
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

    def run(
        self,
        name: str,
        env_vars: Optional[dict] = None,
        owner_id: Optional[str] = None,
        labels: Optional[Dict[str, str]] = None,
        resource_requests: V1ResourceRequests = V1ResourceRequests(),
        resource_limits: V1ResourceLimits = V1ResourceLimits(),
        auth_enabled: bool = True,
    ) -> TaskServer:
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

        env_vars["TASK_SERVER_PORT"] = str(port)
        if not auth_enabled:
            env_vars["TASK_SERVER_NO_AUTH"] = "true"

        if not self.img:
            raise ValueError("img not found")
        container = self.client.containers.run(
            self.img,
            network_mode="host",
            environment=env_vars,
            detach=True,
            labels=_labels,
            name=name,
        )
        if container and type(container) != bytes:
            print(f"ran container '{container.id}'")  # type: ignore

        return TaskServer(
            name=name,
            runtime=self,
            status="running",
            port=port,
            owner_id=owner_id,
        )

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
        task_server_port: int = 9070,
        background: bool = True,
        owner_id: Optional[str] = None,
    ) -> Optional[int]:
        print("no proxy needed")
        return

    def list(
        self, owner_id: Optional[str] = None, source: bool = False
    ) -> List[TaskServer]:

        instances = []
        if source:
            label_filter = {"label": "provisioner=taskara"}
            containers = self.client.containers.list(filters=label_filter)

            for container in containers:
                server_name = container.name

                # Extract the SURF_PORT environment variable
                env_vars = container.attrs.get("Config", {}).get("Env", [])
                port = next(
                    (
                        int(var.split("=")[1])
                        for var in env_vars
                        if var.startswith("SURF_PORT=")
                    ),
                    9070,
                )

                instance = TaskServer(
                    name=server_name,
                    runtime=self,
                    port=port,
                    status="running",
                    owner_id=owner_id,
                )
                instances.append(instance)
        else:
            return TaskServer.find(owner_id=owner_id, runtime_name=self.name())

        return instances

    def get(
        self, name: str, owner_id: Optional[str] = None, source: bool = False
    ) -> TaskServer:
        if source:
            try:
                container = self.client.containers.get(name)

                # Extract the SURF_PORT environment variable
                env_vars = container.attrs.get("Config", {}).get("Env", [])
                port = next(
                    (
                        int(var.split("=")[1])
                        for var in env_vars
                        if var.startswith("SURF_PORT=")
                    ),
                    9070,
                )

                return TaskServer(
                    name=name,
                    runtime=self,
                    status="running",
                    port=port,
                    owner_id=owner_id,
                )
            except NotFound:
                raise ValueError(f"Container '{name}' not found")

        else:
            instances = TaskServer.find(
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
            print(f"Successfully deleted container: {name}")
        except NotFound:
            # Handle the case where the container does not exist
            print(f"Container '{name}' does not exist.")
            raise
        except Exception as e:
            # Handle other potential errors
            print(f"Failed to delete container '{name}': {e}")
            raise

    def clean(self, owner_id: Optional[str] = None) -> None:
        # Define the filter for containers with the specific label
        label_filter = {"label": ["provisioner=surfkit"]}

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
                print(f"Deleted container: {container_name_or_id}")
                deleted_containers.append(container_name_or_id)
            except Exception as e:
                print(f"Failed to delete container: {e}")

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
                return (line.decode("utf-8").strip() for line in log_stream)
            else:
                return container.logs().decode("utf-8")  # type: ignore
        except NotFound:
            print(f"Container '{name}' does not exist.")
            raise
        except Exception as e:
            print(f"Failed to fetch logs for container '{name}': {e}")
            raise

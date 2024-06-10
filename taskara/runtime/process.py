import json
import logging
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Iterator, List, Optional, Tuple, Type, Union

import requests
from pydantic import BaseModel

from taskara.server.models import V1ResourceLimits, V1ResourceRequests
from taskara.util import find_open_port

from .base import Tracker, TrackerRuntime

logger = logging.getLogger(__name__)


class ProcessConnectConfig(BaseModel):
    pass


class ProcessTrackerRuntime(
    TrackerRuntime["ProcessTrackerRuntime", ProcessConnectConfig]
):

    @classmethod
    def name(cls) -> str:
        return "process"

    @classmethod
    def connect_config_type(cls) -> Type[ProcessConnectConfig]:
        return ProcessConnectConfig

    def connect_config(self) -> ProcessConnectConfig:
        return ProcessConnectConfig()

    @classmethod
    def connect(cls, cfg: ProcessConnectConfig) -> "ProcessTrackerRuntime":
        return cls()

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

        port = find_open_port(9070, 10090)
        if not port:
            raise ValueError("Could not find open port")
        logger.debug("running process")

        metadata = {
            "name": name,
            "port": port,
            "env_vars": env_vars if env_vars else {},
            "owner_id": owner_id,
        }

        server_cmd = "poetry run python -m taskara.server.app"
        command = f"TASK_SERVER_PORT={port} nohup {server_cmd} TASK_SERVER={name} TASK_SERVER_PORT={port} > ./.data/logs/{name.lower()}.log 2>&1 &"
        if not auth_enabled:
            command = "TASK_SERVER_NO_AUTH=true " + command
        metadata["command"] = command

        # Create metadata directory if it does not exist
        os.makedirs(f".data/proc", exist_ok=True)
        # Write metadata to a file
        with open(f".data/proc/{name}.json", "w") as f:
            json.dump(metadata, f, indent=4)

        os.makedirs(f".data/logs", exist_ok=True)
        print(f"running server on port {port}")

        environment = os.environ.copy()
        process = subprocess.Popen(
            command,
            shell=True,
            preexec_fn=os.setsid,
            env=environment,
            text=True,
        )

        # Wait for the command to complete
        stdout, stderr = process.communicate()

        # Check if there were any errors
        if process.returncode != 0:
            logger.error("Error running command:")
            print(stderr)
        else:
            # Print the output from stdout
            if stdout:
                print(stdout)

        # Health check logic
        max_retries = 20
        retry_delay = 1
        health_url = f"http://localhost:{port}/health"

        for _ in range(max_retries):
            try:
                response = requests.get(health_url)
                if response.status_code == 200:
                    logger.info("Task server is up and running.")
                    break
            except requests.ConnectionError:
                logger.warning("Task server not yet available, retrying...")
            time.sleep(retry_delay)
        else:
            raise RuntimeError("Failed to start server, it did not pass health checks.")

        return Tracker(
            name=name,
            runtime=self,
            status="running",
            port=port,
            labels={"command": command},
            owner_id=owner_id,
        )

    def _signal_handler(self, server_name: str):
        def handle_signal(signum, frame):
            print(f"Signal {signum} received, stopping process '{server_name}'")
            self.delete(server_name)
            instances = Tracker.find(name=server_name)
            if instances:
                instances[0].delete()
            sys.exit(1)

        return handle_signal

    def _follow_logs(self, server_name: str):
        log_path = f"./.data/logs/{server_name.lower()}.log"
        if not os.path.exists(log_path):
            logger.error("No log file found.")
            return

        with open(log_path, "r") as log_file:
            # Go to the end of the file
            log_file.seek(0, 2)
            try:
                while True:
                    line = log_file.readline()
                    if not line:
                        time.sleep(0.5)  # Wait briefly for new log entries
                        continue
                    print(line.strip())
            except KeyboardInterrupt:
                # Handle Ctrl+C gracefully if we are attached to the logs
                print(f"Interrupt received, stopping logs for '{server_name}'")
                self.delete(server_name)
                raise

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
        logger.info("no proxy needed")
        return

    def get(
        self, name: str, owner_id: Optional[str] = None, source: bool = False
    ) -> Tracker:
        if source:
            try:
                # Read the metadata file
                with open(f".data/proc/{name}.json", "r") as f:
                    metadata = json.load(f)

                return Tracker(
                    name=metadata["name"],
                    runtime=self,
                    port=metadata["port"],
                )
            except FileNotFoundError:
                raise ValueError(f"No metadata found for server {name}")

        else:
            instances = Tracker.find(
                name=name, owner_id=owner_id, runtime_name=self.name()
            )
            if len(instances) == 0:
                raise ValueError(f"No running server found with the name {name}")
            return instances[0]

    def list(
        self,
        owner_id: Optional[str] = None,
        source: bool = False,
    ) -> List[Tracker]:
        instances = []
        if source:
            metadata_dir = ".data/proc"
            all_processes = subprocess.check_output(
                "ps ax -o pid,command", shell=True, text=True
            )

            for filename in os.listdir(metadata_dir):
                if filename.endswith(".json"):
                    try:
                        with open(os.path.join(metadata_dir, filename), "r") as file:
                            metadata = json.load(file)

                        # Check if process is still running
                        process_info = f"TASK_SERVER={metadata['name']} "
                        if process_info in all_processes:
                            instance = Tracker(
                                name=metadata["name"],
                                runtime=self,
                                status="running",
                                port=metadata["port"],
                            )
                            instances.append(instance)
                        else:
                            # Process is not running, delete the metadata file
                            os.remove(os.path.join(metadata_dir, filename))
                            logger.info(
                                f"Deleted metadata for non-existing process {metadata['name']}."
                            )

                    except Exception as e:
                        logger.error(f"Error processing {filename}: {str(e)}")
        else:
            return Tracker.find(owner_id=owner_id, runtime_name=self.name())

        return instances

    def call(
        self,
        name: str,
        path: str,
        method: str,
        port: int = 9070,
        data: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Tuple[int, str]:
        # Construct the URL
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
                f"Error making HTTP request to local process: {status_code}: {error_message}"
            )
        finally:
            try:
                if response:  # type: ignore
                    response.close()
            except:
                pass

    def delete(
        self,
        name: str,
        owner_id: Optional[str] = None,
    ) -> None:
        try:
            process_list = subprocess.check_output(
                f"ps ax -o pid,command | grep -v grep | grep TASK_SERVER={name}",
                shell=True,
                text=True,
            )
            logger.debug(f"Found process list: {process_list}")
            if process_list.strip():
                # Process found, extract PID and kill it
                pid = process_list.strip().split()[0]
                os.killpg(os.getpgid(int(pid)), signal.SIGTERM)
                logger.info(f"Process {name} with PID {pid} has been terminated.")
            else:
                raise SystemError(f"No running process found with the name {name}.")

            # Delete the metadata file whether or not the process was found
            metadata_file = f".data/proc/{name}.json"
            if os.path.exists(metadata_file):
                os.remove(metadata_file)
                logger.info(f"Deleted metadata file for {name}.")

        except subprocess.CalledProcessError as e:
            raise SystemError(f"Error while attempting to delete the process: {str(e)}")
        except ValueError as e:
            raise SystemError(f"Error parsing process ID: {str(e)}")
        except Exception as e:
            raise SystemError(f"An unexpected error occurred: {str(e)}")

    def runtime_local_addr(self, name: str, owner_id: Optional[str] = None) -> str:
        """
        Returns the local address of the agent with respect to the runtime
        """
        instances = Tracker.find(name=name, owner_id=owner_id, runtime_name=self.name())
        if not instances:
            raise ValueError(f"Task server '{name}' not found")
        instance = instances[0]

        return f"http://localhost:{instance.port}"

    def clean(
        self,
        owner_id: Optional[str] = None,
    ) -> None:
        try:
            # Fetch the list of all processes that were started with the 'TASK_SERVER' environment variable
            process_list = subprocess.check_output(
                "ps ax -o pid,command | grep -v grep | grep TASK_SERVER",
                shell=True,
                text=True,
            )
            # Iterate through each process found and kill it
            for line in process_list.strip().split("\n"):
                pid = line.split()[0]  # Extract the PID from the output
                try:
                    os.kill(
                        int(pid), signal.SIGTERM
                    )  # Send SIGTERM signal to terminate the process
                    logger.info(f"Terminated process with PID {pid}.")
                except OSError as e:
                    logger.error(
                        f"Failed to terminate process with PID {pid}: {str(e)}"
                    )
            logger.info("All relevant processes have been terminated.")
        except subprocess.CalledProcessError as e:
            logger.error(
                "No relevant processes found or error executing the ps command:", str(e)
            )
        except Exception as e:
            logger.error(f"An unexpected error occurred during cleanup: {str(e)}")

    def logs(
        self,
        name: str,
        follow: bool = False,
        owner_id: Optional[str] = None,
    ) -> Union[str, Iterator[str]]:
        log_path = f"./.data/logs/{name.lower()}.log"
        if not os.path.exists(log_path):
            return "No logs available for this server."

        if follow:
            # If follow is True, implement a simple follow (like 'tail -f')
            def follow_logs():
                with open(log_path, "r") as log_file:
                    # Go to the end of the file
                    log_file.seek(0, 2)
                    while True:
                        line = log_file.readline()
                        if not line:
                            time.sleep(0.5)  # Wait briefly for new log entries
                            continue
                        yield line

            return follow_logs()
        else:
            # If not following, return all logs as a single string
            with open(log_path, "r") as log_file:
                return log_file.read()

    def refresh(self, owner_id: Optional[str] = None) -> None:
        """
        Reconciles the database against the running processes.

        Parameters:
            owner_id (Optional[str]): The owner ID to filter the trackers. If None, refreshes for all owners.
        """
        # List all running processes with the specific environment variable
        all_processes = subprocess.check_output(
            "ps ax -o pid,command", shell=True, text=True
        )
        running_processes = {}
        for line in all_processes.splitlines():
            if "TASK_SERVER=" in line:
                pid, command = line.split(maxsplit=1)
                server_name = next(
                    (
                        part.split("=")[1]
                        for part in command.split()
                        if part.startswith("TASK_SERVER=")
                    ),
                    None,
                )
                if server_name:
                    running_processes[server_name] = pid

        running_process_names = set(running_processes.keys())

        # List all trackers in the database
        if owner_id:
            db_trackers = Tracker.find(owner_id=owner_id, runtime_name=self.name())
        else:
            db_trackers = Tracker.find(runtime_name=self.name())

        db_tracker_names = {tracker.name for tracker in db_trackers}

        # Determine trackers to add or remove from the database
        processes_to_add = running_process_names - db_tracker_names
        processes_to_remove = db_tracker_names - running_process_names

        # Add new processes to the database
        for process_name in processes_to_add:
            try:
                with open(f".data/proc/{process_name}.json", "r") as f:
                    metadata = json.load(f)

                new_tracker = Tracker(
                    name=metadata["name"],
                    runtime=self,
                    port=metadata["port"],
                    status="running",
                    owner_id=owner_id,
                )
                new_tracker.save()
            except FileNotFoundError:
                logger.warning(f"No metadata found for process {process_name}")

        # Remove processes from the database that are no longer running
        for tracker_name in processes_to_remove:
            trackers = Tracker.find(
                name=tracker_name, owner_id=owner_id, runtime_name=self.name()
            )
            if not trackers:
                continue
            tracker = trackers[0]
            tracker.delete()

        logger.debug(
            f"Refresh completed: added {len(processes_to_add)} trackers, removed {len(processes_to_remove)} trackers."
        )

import atexit
import base64
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Iterator, List, Optional, Tuple, Type, Union

from google.auth.transport.requests import Request
from google.cloud import container_v1
from google.oauth2 import service_account
from kubernetes import client, config
from kubernetes.client import Configuration
from kubernetes.client.api import core_v1_api
from kubernetes.client.rest import ApiException
from kubernetes.stream import portforward
from namesgenerator import get_random_name
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_fixed

from taskara.server.models import (
    V1ResourceLimits,
    V1ResourceRequests,
    V1Task,
    V1Tracker,
)
from taskara.util import find_open_port

from .base import Tracker, TrackerRuntime

logger = logging.getLogger(__name__)


class GKEOpts(BaseModel):
    cluster_name: str
    region: str
    service_account_json: str


class LocalOpts(BaseModel):
    path: Optional[str] = os.getenv("KUBECONFIG", os.path.expanduser("~/.kube/config"))


class KubeConnectConfig(BaseModel):
    provider: str = "local"
    namespace: str = "default"
    gke_opts: Optional[GKEOpts] = None
    local_opts: Optional[LocalOpts] = None
    image: str = "us-central1-docker.pkg.dev/agentsea-dev/taskara/api:latest"


class KubeTrackerRuntime(TrackerRuntime["KubeTrackerRuntime", KubeConnectConfig]):
    """A container runtime that uses Kubernetes to manage Pods directly"""

    def __init__(self, cfg: Optional[KubeConnectConfig] = None) -> None:
        # Load the Kubernetes configuration, typically from ~/.kube/config
        if not cfg:
            cfg = KubeConnectConfig()
        self.cfg = cfg
        if cfg.provider == "gke":
            opts = cfg.gke_opts
            if not opts:
                raise ValueError("GKE opts missing")
            self.connect_to_gke(opts)
        elif cfg.provider == "local":
            opts = cfg.local_opts
            if not opts:
                opts = LocalOpts()
            if opts.path:
                config.load_kube_config(opts.path)
        else:
            raise ValueError("Unsupported provider: " + cfg.provider)

        self.img = cfg.image

        self.core_api = core_v1_api.CoreV1Api()
        self.namespace = cfg.namespace
        self.subprocesses = []
        self.setup_signal_handlers()

    @classmethod
    def name(cls) -> str:
        return "kube"

    def create_secret(self, name: str, env_vars: dict) -> client.V1Secret:
        """
        Creates a Kubernetes Secret object to store environment variables.

        Parameters:
            name (str): The base name of the secret, usually related to the pod name.
            env_vars (dict): A dictionary containing the environment variables as key-value pairs.

        Returns:
            client.V1Secret: The created Kubernetes Secret object.
        """
        logger.debug(f"creating secret with envs: {env_vars}")
        secret = client.V1Secret(
            api_version="v1",
            kind="Secret",
            metadata=client.V1ObjectMeta(
                name=name,
                namespace=self.namespace,
                # This ensures that the secret is deleted when the pod is deleted.
                labels={"provisioner": "surfkit"},
            ),
            string_data=env_vars,
            type="Opaque",
        )
        try:
            self.core_api.create_namespaced_secret(
                namespace=self.namespace, body=secret
            )
            logger.debug(f"Secret created: {name}")
            return secret
        except ApiException as e:
            logger.error(f"Failed to create secret: {e}")
            raise

    def create(
        self,
        image: str,
        name: Optional[str] = None,
        resource_requests: V1ResourceRequests = V1ResourceRequests(),
        resource_limits: V1ResourceLimits = V1ResourceLimits(),
        env_vars: Optional[dict] = None,
        owner_id: Optional[str] = None,
        auth_enabled: bool = True,
    ) -> None:
        if not name:
            name = get_random_name("-")
            if not name:
                raise ValueError("Could not generate a random name")

        secret = None
        if env_vars:
            # Create a secret for the environment variables
            logger.debug("creating secret...")
            secret: Optional[client.V1Secret] = self.create_secret(name, env_vars)
            env_from = [
                client.V1EnvFromSource(
                    secret_ref=client.V1SecretEnvSource(name=secret.metadata.name)  # type: ignore
                )
            ]
        else:
            env_from = []

        # Resource configurations as before
        resources = client.V1ResourceRequirements(
            requests={"memory": resource_requests.memory, "cpu": resource_requests.cpu},
            limits={"memory": resource_limits.memory, "cpu": resource_limits.cpu},
        )
        if resource_requests.gpu:
            raise ValueError("GPU resource requests are not supported")

        logger.debug(f"using resources: {resources.__dict__}")

        # Container configuration
        container = client.V1Container(
            name=name,
            image=image,
            ports=[client.V1ContainerPort(container_port=9070)],
            resources=resources,
            env_from=env_from,  # Using envFrom to source env vars from the secret
            image_pull_policy="Always",
        )

        # print("\ncreating container: ", container.__dict__)

        # Pod specification
        pod_spec = client.V1PodSpec(
            containers=[container],
            restart_policy="Never",
        )

        _env_vars = []
        if not auth_enabled:
            _env_vars.append(client.V1EnvVar(name="TASK_SERVER_NO_AUTH", value="true"))

        # Pod creation
        pod = client.V1Pod(
            api_version="v1",
            kind="Pod",
            metadata=client.V1ObjectMeta(
                name=name,
                labels={"provisioner": "surfkit"},
                annotations={
                    "owner": owner_id,
                    "server_name": name,
                },
            ),
            spec=pod_spec,
        )

        try:
            created_pod: client.V1Pod = self.core_api.create_namespaced_pod(  # type: ignore
                namespace=self.namespace, body=pod
            )
            logger.debug(f"Pod created with name='{name}'")
            # print("created pod: ", created_pod.__dict__)
            # Update secret's owner reference UID to newly created pod's UID
            if secret:
                logger.debug("updating secret refs...")
                if not secret.metadata:
                    raise ValueError("expected secret metadata to be set")
                if not created_pod.metadata:
                    raise ValueError("expected pod metadata to be set")
                secret.metadata.owner_references = [
                    client.V1OwnerReference(
                        api_version="v1",
                        kind="Pod",
                        name=name,
                        uid=created_pod.metadata.uid,  # This should be set dynamically after pod creation
                    )
                ]
                self.core_api.patch_namespaced_secret(
                    name=secret.metadata.name, namespace=self.namespace, body=secret  # type: ignore
                )
                logger.debug("secret refs updated")
        except ApiException as e:
            logger.error(f"Exception when creating pod: {e}")
            raise

        self.wait_pod_ready(name)
        self.wait_for_http_200(name)

    @classmethod
    def connect_config_type(cls) -> Type[KubeConnectConfig]:
        return KubeConnectConfig

    def connect_config(self) -> KubeConnectConfig:
        return self.cfg

    @classmethod
    def connect(cls, cfg: KubeConnectConfig) -> "KubeTrackerRuntime":
        return cls(cfg)

    @retry(stop=stop_after_attempt(15))
    def connect_to_gke(self, opts: GKEOpts) -> Tuple[client.CoreV1Api, str, str]:
        """
        Sets up and returns a configured Kubernetes client (CoreV1Api) and cluster details.

        Returns:
            Tuple containing the Kubernetes CoreV1Api client object, the project ID, and the cluster name.
        """
        service_account_info = json.loads(opts.service_account_json)
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )

        # Setup GKE client to get cluster information
        gke_service = container_v1.ClusterManagerClient(credentials=credentials)
        project_id = service_account_info.get("project_id")
        if not project_id or not opts.cluster_name or not opts.region:
            raise ValueError(
                "Missing project_id, cluster_name, or region in credentials or metadata"
            )

        logger.debug("K8s getting cluster...")
        cluster_request = container_v1.GetClusterRequest(
            name=f"projects/{project_id}/locations/{opts.region}/clusters/{opts.cluster_name}"
        )
        cluster = gke_service.get_cluster(request=cluster_request)

        # Configure Kubernetes client
        logger.debug("K8s getting token...")
        ca_cert = base64.b64decode(cluster.master_auth.cluster_ca_certificate)
        try:
            logger.debug("K8s refreshing token...")
            credentials.refresh(Request())
        except Exception as e:
            logger.debug(f"K8s token refresh failed: {e}")
            raise e
        access_token = credentials.token
        logger.debug(f"K8s got token: {access_token}")

        cluster_name = opts.cluster_name

        kubeconfig = {
            "apiVersion": "v1",
            "kind": "Config",
            "clusters": [
                {
                    "name": cluster_name,
                    "cluster": {
                        "server": f"https://{cluster.endpoint}",
                        "certificate-authority-data": base64.b64encode(
                            ca_cert
                        ).decode(),
                    },
                }
            ],
            "contexts": [
                {
                    "name": cluster_name,
                    "context": {
                        "cluster": cluster_name,
                        "user": cluster_name,
                    },
                }
            ],
            "current-context": cluster_name,
            "users": [
                {
                    "name": cluster_name,
                    "user": {
                        "token": access_token,
                    },
                }
            ],
        }

        config.load_kube_config_from_dict(config_dict=kubeconfig)
        v1_client = client.CoreV1Api()
        logger.debug("K8s returning client...")

        return v1_client, project_id, cluster_name

    @retry(stop=stop_after_attempt(200), wait=wait_fixed(2))
    def wait_for_http_200(self, name: str, path: str = "/", port: int = 9070):
        """
        Waits for an HTTP 200 response from the specified path on the given pod.

        Parameters:
            name (str): The name of the pod.
            path (str): The path to query. Defaults to root '/'.
            port (int): The port on which the pod service is exposed. Defaults to 9070.

        Raises:
            RuntimeError: If the response is not 200 after the specified retries.
        """
        logger.debug(
            f"Checking HTTP 200 readiness for pod {name} on path {path} and port: {port}"
        )
        status_code, response_text = self.call(
            name=name, path=path, method="GET", port=port
        )
        if status_code != 200:
            print(f"Received status code {status_code}, retrying...")
            raise Exception(
                f"Pod {name} at path {path} is not ready. Status code: {status_code}"
            )
        logger.debug(f"Pod {name} at path {path} responded with: {response_text}")
        print(f"Pod {name} at path {path} is ready with status 200.")

    @retry(stop=stop_after_attempt(200), wait=wait_fixed(2))
    def wait_pod_ready(self, name: str) -> bool:
        """
        Checks if the specified pod is ready to serve requests.

        Parameters:
            name (str): The name of the pod to check.

        Returns:
            bool: True if the pod is ready, False otherwise.
        """
        try:
            pod = self.core_api.read_namespaced_pod(name=name, namespace=self.namespace)
            conditions = pod.status.conditions  # type: ignore
            if conditions:
                for condition in conditions:
                    if condition.type == "Ready" and condition.status == "True":
                        print("pod is ready!")
                        return True
            print("pod is not ready yet...")
            raise Exception(f"Pod {name} is not ready")
        except ApiException as e:
            logger.error(f"Failed to read pod status for '{name}': {e}")
            raise

    @retry(stop=stop_after_attempt(15))
    def call(
        self,
        name: str,
        path: str,
        method: str,
        port: int = 9070,
        data: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Tuple[int, str]:

        c = Configuration.get_default_copy()
        c.assert_hostname = False  # type: ignore
        Configuration.set_default(c)
        core_v1 = client.CoreV1Api()
        ##############################################################################
        # Kubernetes pod port forwarding works by directly providing a socket which
        # the python application uses to send and receive data on. This is in contrast
        # to the go client, which opens a local port that the go application then has
        # to open to get a socket to transmit data.
        #
        # This simplifies the python application, there is not a local port to worry
        # about if that port number is available. Nor does the python application have
        # to then deal with opening this local port. The socket used to transmit data
        # is immediately provided to the python application.
        #
        # Below also is an example of monkey patching the socket.create_connection
        # function so that DNS names of the following formats will access kubernetes
        # ports:
        #
        #    <pod-name>.<namespace>.kubernetes
        #    <pod-name>.pod.<namespace>.kubernetes
        #    <service-name>.svc.<namespace>.kubernetes
        #    <service-name>.service.<namespace>.kubernetes
        #
        # These DNS name can be used to interact with pod ports using python libraries,
        # such as urllib.request and http.client. For example:
        #
        # response = urllib.request.urlopen(
        #     'https://metrics-server.service.kube-system.kubernetes/'
        # )
        #
        ##############################################################################

        # Monkey patch socket.create_connection which is used by http.client and
        # urllib.request. The same can be done with urllib3.util.connection.create_connection
        # if the "requests" package is used.
        socket_create_connection = socket.create_connection

        def kubernetes_create_connection(address, *args, **kwargs):
            dns_name = address[0]
            if isinstance(dns_name, bytes):
                dns_name = dns_name.decode()
            dns_name = dns_name.split(".")
            if dns_name[-1] != "kubernetes":
                return socket_create_connection(address, *args, **kwargs)
            if len(dns_name) not in (3, 4):
                raise RuntimeError("Unexpected kubernetes DNS name.")
            namespace = dns_name[-2]
            name = dns_name[0]
            port = address[1]
            # print("connecting to: ", namespace, name, port)
            if len(dns_name) == 4:
                if dns_name[1] in ("svc", "service"):
                    service = core_v1.read_namespaced_service(name, namespace)
                    for service_port in service.spec.ports:  # type: ignore
                        if service_port.port == port:
                            port = service_port.target_port
                            break
                    else:
                        raise RuntimeError(f"Unable to find service port: {port}")
                    label_selector = []
                    for key, value in service.spec.selector.items():  # type: ignore
                        label_selector.append(f"{key}={value}")
                    pods = core_v1.list_namespaced_pod(
                        namespace, label_selector=",".join(label_selector)
                    )
                    if not pods.items:
                        raise RuntimeError("Unable to find service pods.")
                    name = pods.items[0].metadata.name
                    if isinstance(port, str):
                        for container in pods.items[0].spec.containers:
                            for container_port in container.ports:
                                if container_port.name == port:
                                    port = container_port.container_port
                                    break
                            else:
                                continue
                            break
                        else:
                            raise RuntimeError(
                                f"Unable to find service port name: {port}"
                            )
                elif dns_name[1] != "pod":
                    raise RuntimeError(f"Unsupported resource type: {dns_name[1]}")
            pf = portforward(
                core_v1.connect_get_namespaced_pod_portforward,
                name,
                namespace,
                ports=str(port),
            )
            return pf.socket(port)

        socket.create_connection = kubernetes_create_connection

        namespace = self.namespace
        if not namespace:
            raise ValueError("NAMESPACE environment variable not set")
        # Access the nginx http server using the
        # "<pod-name>.pod.<namespace>.kubernetes" dns name.
        # Construct the URL with the custom path
        url = f"http://{name.lower()}.pod.{namespace}.kubernetes:{port}{path}"

        # Create a request object based on the HTTP method
        if method.upper() == "GET":
            if data:
                # Convert data to URL-encoded query parameters for GET requests
                query_params = urllib.parse.urlencode(data)
                url += f"?{query_params}"
            request = urllib.request.Request(url)
        else:
            # Set the request method and data for POST, PUT, etc.
            request = urllib.request.Request(url, method=method.upper())
            if data:
                # Convert data to JSON string and set the request body
                request.add_header("Content-Type", "application/json")
                if headers:
                    for k, v in headers.items():
                        request.add_header(k, v)
                request.data = json.dumps(data).encode("utf-8")
            logger.debug(f"Request Data: {request.data}")

        # Send the request and handle the response
        try:
            response = urllib.request.urlopen(request)
            status_code = response.code
            response_text = response.read().decode("utf-8")
            logger.debug(f"Status Code: {status_code}")

            # Parse the JSON response and return a dictionary
            return status_code, response_text
        except urllib.error.HTTPError as e:
            status_code = e.code
            error_message = e.read().decode("utf-8")
            logger.debug(f"Error: {status_code}")
            logger.debug(error_message)

            raise SystemError(
                f"Error making http request kubernetes pod {status_code}: {error_message}"
            )
        finally:
            try:
                if response:  # type: ignore
                    response.close()
            except:
                pass

    def setup_signal_handlers(self):
        signal.signal(signal.SIGINT, self.graceful_exit)
        signal.signal(signal.SIGTERM, self.graceful_exit)
        atexit.register(self.cleanup_subprocesses)

    def _register_cleanup(self, proc: subprocess.Popen):
        self.subprocesses.append(proc)

    def cleanup_subprocesses(self):
        for proc in self.subprocesses:
            if proc.poll() is None:  # Process is still running
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
        self.subprocesses = []  # Clear the list after cleaning up

    def graceful_exit(self, signum, frame):
        self.cleanup_subprocesses()
        sys.exit(signum)  # Exit with the signal number

    def requires_proxy(self) -> bool:
        """Whether this runtime requires a proxy to be used"""
        return True

    def proxy(
        self,
        name: str,
        local_port: Optional[int] = None,
        tracker_port: int = 9070,
        background: bool = True,
        owner_id: Optional[str] = None,
    ) -> Optional[int]:
        if local_port is None:
            local_port = find_open_port(9070, 10090)

        cmd = f"kubectl port-forward pod/{name} {local_port}:{tracker_port} -n {self.namespace}"

        if background:
            proc = subprocess.Popen(
                cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            self._register_cleanup(proc)
            return proc.pid  # Return the PID of the subprocess

        else:
            try:
                subprocess.run(cmd, shell=True, check=True)  # type: ignore
                return None  # No PID to return when not in background mode
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"Port forwarding failed: {e}")

    def logs(
        self,
        name: str,
        follow: bool = False,
        owner_id: Optional[str] = None,
    ) -> Union[str, Iterator[str]]:
        """
        Fetches the logs from the specified pod. Can return all logs as a single string,
        or stream the logs as a generator of strings.

        Parameters:
            name (str): The name of the pod.
            follow (bool): Whether to continuously follow the logs.
            owner_id (Optional[str]): The owner ID of the pod. If provided, it will be included in the log lines.

        Returns:
            Union[str, Iterator[str]]: All logs as a single string, or a generator that yields log lines.
        """
        try:
            return self.core_api.read_namespaced_pod_log(
                name=name,
                namespace=self.namespace,
                follow=follow,
                pretty="true",
                _preload_content=False,  # Important to return a generator when following
            )
        except ApiException as e:
            logger.error(f"Failed to get logs for pod '{name}': {e}")
            raise

    def list(
        self,
        owner_id: Optional[str] = None,
        source: bool = False,
    ) -> List[Tracker]:
        instances = []

        if source:
            try:
                pods = self.core_api.list_namespaced_pod(
                    namespace=self.namespace, label_selector="provisioner=surfkit"
                )
                for pod in pods.items:
                    name = pod.metadata.name

                    instances.append(
                        Tracker(name=name, runtime=self, status="running", port=9070)
                    )
            except ApiException as e:
                logger.error(f"Failed to list pods: {e}")
                raise

        else:
            instances = Tracker.find(owner_id=owner_id, runtime_name=self.name())

        return instances

    def get(
        self,
        name: str,
        owner_id: Optional[str] = None,
        source: bool = False,
    ) -> Tracker:
        if source:
            try:
                pod = self.core_api.read_namespaced_pod(
                    name=name, namespace=self.namespace
                )
                return Tracker(name=name, runtime=self, status="running", port=9070)
            except ApiException as e:
                logger.error(f"Failed to get pod '{name}': {e}")
                raise

        else:
            instances = Tracker.find(
                name=name, owner_id=owner_id, runtime_name=self.name()
            )
            if not instances:
                raise ValueError(f"No server instance found with name '{name}'")
            return instances[0]

    def delete(
        self,
        name: str,
        owner_id: Optional[str] = None,
    ) -> None:
        try:
            # Delete the pod
            self.core_api.delete_namespaced_pod(
                name=name,
                namespace="default",
                body=client.V1DeleteOptions(grace_period_seconds=5),
            )
            self.core_api.delete_namespaced_secret(name=name, namespace=self.namespace)
            logger.debug(f"Successfully deleted pod: {name}")
        except ApiException as e:
            logger.error(f"Failed to delete pod '{name}': {e}")
            raise

    def clean(
        self,
        owner_id: Optional[str] = None,
    ) -> None:
        pods = self.core_api.list_namespaced_pod(
            namespace="default", label_selector="provisioner=surfkit"
        )
        for pod in pods.items:
            try:
                self.core_api.delete_namespaced_pod(
                    name=pod.metadata.name,
                    namespace="default",
                    body=client.V1DeleteOptions(grace_period_seconds=5),
                )
                logger.debug(f"Deleted pod: {pod.metadata.name}")
            except ApiException as e:
                logger.error(f"Failed to delete pod '{pod.metadata.name}': {e}")

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
        logger.debug("creating task server...")
        if not self.img:
            raise ValueError("img not found")

        requests = V1ResourceRequests()
        limits = V1ResourceLimits()
        self.create(
            image=self.img,
            name=name,
            resource_requests=resource_requests,
            resource_limits=resource_limits,
            env_vars=env_vars,
            owner_id=owner_id,
            auth_enabled=auth_enabled,
        )

        return Tracker(
            name=name,
            runtime=self,
            status="running",
            port=9070,
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

        return (
            f"http://{instance.name}.{self.namespace}.svc.cluster.local:{instance.port}"
        )

    def _handle_logs_with_attach(self, server_name: str, attach: bool):
        if attach:
            # Setup the signal handler to catch interrupt signals
            signal.signal(signal.SIGINT, self._signal_handler(server_name))

        try:
            log_lines = self.logs(name=server_name, follow=True)
            for line in log_lines:
                print(line.decode("utf-8"))  # type: ignore
        except KeyboardInterrupt:
            # This block will be executed if SIGINT is caught
            logger.error(
                f"Interrupt received, stopping logs and deleting pod '{server_name}'"
            )
            self.delete(server_name)
        except ApiException as e:
            logger.error(f"Failed to follow logs for pod '{server_name}': {e}")
            raise
        except Exception as e:
            logger.error(f"An error occurred while fetching logs: {e}")
            raise

    def _signal_handler(self, server_name: str):
        def handle_signal(signum, frame):
            print(
                f"Signal {signum} received, stopping and deleting pod '{server_name}'"
            )
            self.delete(server_name)
            sys.exit(1)

        return handle_signal

    def refresh(self, owner_id: Optional[str] = None) -> None:
        """
        Reconciles the database against the Kubernetes pods running.

        Parameters:
            owner_id (Optional[str]): The owner ID to filter the trackers. If None, refreshes for all owners.
        """
        # List all Kubernetes pods with the specific label
        label_selector = "provisioner=surfkit"
        try:
            running_pods = self.core_api.list_namespaced_pod(
                namespace=self.namespace, label_selector=label_selector
            )
        except ApiException as e:
            logger.error(f"Failed to list pods: {e}")
            raise

        running_pod_names = {pod.metadata.name for pod in running_pods.items}

        # List all trackers in the database
        if owner_id:
            db_trackers = Tracker.find(owner_id=owner_id, runtime_name=self.name())
        else:
            db_trackers = Tracker.find(runtime_name=self.name())

        db_tracker_names = {tracker.name for tracker in db_trackers}

        # Determine trackers to add or remove from the database
        pods_to_add = running_pod_names - db_tracker_names
        pods_to_remove = db_tracker_names - running_pod_names

        # Add new pods to the database
        for pod_name in pods_to_add:
            pod = self.core_api.read_namespaced_pod(
                name=pod_name, namespace=self.namespace
            )
            new_tracker = Tracker(
                name=pod_name,
                runtime=self,
                port=9070,
                status="running",
                owner_id=owner_id,
            )
            new_tracker.save()

        # Remove pods from the database that are no longer running
        for tracker_name in pods_to_remove:
            trackers = Tracker.find(
                name=tracker_name, owner_id=owner_id, runtime_name=self.name()
            )
            if not trackers:
                continue
            tracker = trackers[0]
            tracker.delete()

        logger.debug(
            f"Refresh completed: added {len(pods_to_add)} trackers, removed {len(pods_to_remove)} trackers."
        )

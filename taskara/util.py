import random
import socket
import string
import subprocess
from typing import Optional
from openmeter import Client
from azure.core.exceptions import ResourceNotFoundError
import os

openmeter_secret = os.getenv("OPENMETER_SECRET", False)
openmeter_agent_task_feature = os.getenv("OPENMETER_AGENT_TASK_FEATURE")
# TODO really figure out if this initiates a connection, I think not but should make sure somehow
if openmeter_secret: 
    openmeter_client = Client(
        endpoint="https://openmeter.cloud",
        headers={
        "Accept": "application/json",
        "Authorization": f"Bearer {openmeter_secret}",
        },
    )


def generate_random_string(length: int = 8):
    """Generate a random string of fixed length."""
    letters = string.ascii_letters + string.digits
    return "".join(random.choices(letters, k=length))


def get_docker_host() -> str:
    try:
        # Get the current Docker context
        current_context = (
            subprocess.check_output("docker context show", shell=True).decode().strip()
        )

        # Inspect the current Docker context and extract the host
        context_info = subprocess.check_output(
            f"docker context inspect {current_context}", shell=True
        ).decode()
        for line in context_info.split("\n"):
            if '"Host"' in line:
                return line.split('"')[3]
        return ""
    except subprocess.CalledProcessError as e:
        print(f"Error: {e.output.decode()}")
        return ""


def check_port_in_use(port: int) -> bool:
    """
    Check if the specified port is currently in use on the local machine.

    Args:
        port (int): The port number to check.

    Returns:
        bool: True if the port is in use, False otherwise.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def find_open_port(start_port: int = 1024, end_port: int = 65535) -> Optional[int]:
    """Finds an open port on the machine"""
    for port in range(start_port, end_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("", port))
                return port  # Port is open
            except socket.error:
                continue  # Port is in use, try the next one
    return None  # No open port found

def check_openmeter_agent_tasks(owner_id) -> bool:
    if openmeter_secret:
        if not openmeter_agent_task_feature or not openmeter_client:
            raise ValueError('Cannot create desktop no openmeter secret or client or openmeter_agent_task_feature to get entitlements from')

        entitlement_value = {}
        try:
            # Check openmeter for if user has access through an entitlement
            entitlement_value = openmeter_client.get_entitlement_value(
                subject_id_or_key=owner_id,
                entitlement_id_or_feature_key=openmeter_agent_task_feature
            )
        
        except ResourceNotFoundError as e:
            print(
                f"#slack-alert Feature {openmeter_agent_task_feature} not found for subject {owner_id}: {e}"
            )
            return False
        if not entitlement_value or not entitlement_value["hasAccess"]:
            print(f"entitlement access denied in assigning task to agent for feature {openmeter_agent_task_feature}, for subject {owner_id} it is likely that the entitlement is no longer valid or the user/org has reached their cap #slack-alert")
            return False
        print(f"user: {owner_id} agent task entitlement values are {entitlement_value}", flush=True)
    return True
import random
import socket
import string
import subprocess
from typing import Optional


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

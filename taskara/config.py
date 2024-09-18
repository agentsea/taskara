"""
Configuration for taskara
"""

import os
from dataclasses import dataclass
from typing import Optional

import yaml

from .env import AGENTSEA_AUTH_URL_ENV, AGENTSEA_HUB_API_URL_ENV, AGENTSEA_HUB_URL_ENV

AGENTSEA_HOME = os.path.expanduser(os.environ.get("AGENTSEA_HOME", "~/.agentsea"))
AGENTSEA_DB_DIR = os.path.expanduser(
    os.environ.get("AGENTSEA_DB_DIR", os.path.join(AGENTSEA_HOME, "data"))
)
AGENTSEA_LOG_DIR = os.path.expanduser(
    os.environ.get("AGENTSEA_LOG_DIR", os.path.join(AGENTSEA_HOME, "logs"))
)
AGENTSEA_AUTH_URL = os.getenv(AGENTSEA_AUTH_URL_ENV, "https://auth.hub.agentsea.ai")
AGENTSEA_HUB_URL = os.getenv(AGENTSEA_HUB_URL_ENV, "https://hub.agentsea.ai")
AGENTSEA_HUB_API_URL = os.getenv(
    AGENTSEA_HUB_API_URL_ENV, "https://api.hub.agentsea.ai"
)
DB_TEST = os.environ.get("AGENTSEA_DB_TEST", "false") == "true"
DB_NAME = os.environ.get("TASKS_DB_NAME", "tasks.db")
if DB_TEST:
    DB_NAME = "tasks_test.db"


@dataclass
class GlobalConfig:
    api_key: Optional[str] = None
    hub_address: str = AGENTSEA_HUB_URL

    def write(self) -> None:
        home = os.path.expanduser("~")
        dir = os.path.join(home, ".agentsea")
        os.makedirs(dir, exist_ok=True)
        path = os.path.join(dir, "config.yaml")

        with open(path, "w") as yaml_file:
            yaml.dump(self.__dict__, yaml_file)
            yaml_file.flush()
            yaml_file.close()

    @classmethod
    def read(cls) -> "GlobalConfig":
        home = os.path.expanduser("~")
        dir = os.path.join(home, ".agentsea")
        os.makedirs(dir, exist_ok=True)
        path = os.path.join(dir, "config.yaml")

        if not os.path.exists(path):
            return GlobalConfig()

        with open(path, "r") as yaml_file:
            config = yaml.safe_load(yaml_file)
            return GlobalConfig(**config)

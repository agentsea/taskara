from typing import Optional, List, Type

from pydantic import BaseModel

from .docker import DockerTrackerRuntime, DockerConnectConfig
from .kube import KubeTrackerRuntime, KubeConnectConfig
from .process import ProcessTrackerRuntime, ProcessConnectConfig
from .base import Tracker, TrackerRuntime
from taskara.server.models import V1TrackerRuntimeConnect


class AgentRuntimeConfig(BaseModel):
    provider: Optional[str] = None
    docker_config: Optional[DockerConnectConfig] = None
    kube_config: Optional[KubeConnectConfig] = None
    process_config: Optional[ProcessConnectConfig] = None
    preference: List[str] = ["kube", "docker", "process"]


def runtime_from_name(name: str) -> Type[TrackerRuntime]:
    for runt in RUNTIMES:
        if runt.name() == name:
            return runt
    raise ValueError(f"Unknown runtime '{name}'")


def load_tracker_runtime(cfg: AgentRuntimeConfig) -> TrackerRuntime:
    for pref in cfg.preference:
        if pref == KubeTrackerRuntime.name() and cfg.kube_config:
            return KubeTrackerRuntime.connect(cfg.kube_config)
        elif pref == DockerTrackerRuntime.name() and cfg.docker_config:
            return DockerTrackerRuntime.connect(cfg.docker_config)
        elif pref == ProcessTrackerRuntime.name() and cfg.process_config:
            return ProcessTrackerRuntime.connect(cfg.process_config)
    raise ValueError(f"Unknown provider: {cfg.provider}")


RUNTIMES: List[Type[TrackerRuntime]] = [DockerTrackerRuntime, KubeTrackerRuntime, ProcessTrackerRuntime]  # type: ignore


def load_from_connect(connect: V1TrackerRuntimeConnect) -> TrackerRuntime:
    for runt in RUNTIMES:
        if connect.name == runt.name():
            print("connect config: ", connect.connect_config)
            print("type: ", type(connect.connect_config))
            cfg = runt.connect_config_type().model_validate(connect.connect_config)
            return runt.connect(cfg)

    raise ValueError(f"Unknown runtime: {connect.name}")

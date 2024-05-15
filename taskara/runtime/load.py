from typing import Optional, List, Type

from pydantic import BaseModel

from .docker import DockerTaskServerRuntime, DockerConnectConfig
from .kube import KubeTaskServerRuntime, KubeConnectConfig
from .process import ProcessTaskServerRuntime, ProcessConnectConfig
from .base import TaskServer, TaskServerRuntime
from taskara.server.models import V1TaskRuntimeConnect


class AgentRuntimeConfig(BaseModel):
    provider: Optional[str] = None
    docker_config: Optional[DockerConnectConfig] = None
    kube_config: Optional[KubeConnectConfig] = None
    process_config: Optional[ProcessConnectConfig] = None
    preference: List[str] = ["kube", "docker", "process"]


def runtime_from_name(name: str) -> Type[TaskServerRuntime]:
    for runt in RUNTIMES:
        if runt.name() == name:
            return runt
    raise ValueError(f"Unknown runtime '{name}'")


def load_task_server_runtime(cfg: AgentRuntimeConfig) -> TaskServerRuntime:
    for pref in cfg.preference:
        if pref == KubeTaskServerRuntime.name() and cfg.kube_config:
            return KubeTaskServerRuntime.connect(cfg.kube_config)
        elif pref == DockerTaskServerRuntime.name() and cfg.docker_config:
            return DockerTaskServerRuntime.connect(cfg.docker_config)
        elif pref == ProcessTaskServerRuntime.name() and cfg.process_config:
            return ProcessTaskServerRuntime.connect(cfg.process_config)
    raise ValueError(f"Unknown provider: {cfg.provider}")


RUNTIMES: List[Type[TaskServerRuntime]] = [DockerTaskServerRuntime, KubeTaskServerRuntime, ProcessTaskServerRuntime]  # type: ignore


def load_from_connect(connect: V1TaskRuntimeConnect) -> TaskServerRuntime:
    for runt in RUNTIMES:
        if connect.name == runt.name():
            print("connect config: ", connect.connect_config)
            print("type: ", type(connect.connect_config))
            cfg = runt.connect_config_type().model_validate(connect.connect_config)
            return runt.connect(cfg)

    raise ValueError(f"Unknown runtime: {connect.name}")

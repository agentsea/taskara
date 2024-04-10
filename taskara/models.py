from typing import Optional, List, Dict, Any
import uuid
import time

from threadmem.server.models import RoleThreadModel
from pydantic import BaseModel, Field
from devicebay.models import DeviceModel


class TaskCreateModel(BaseModel):
    description: str
    assigned_to: Optional[str] = None


class TaskUpdateModel(BaseModel):
    status: Optional[str] = None
    description: Optional[str] = None
    max_steps: Optional[int] = None
    error: Optional[str] = None
    output: Optional[str] = None
    assigned_to: Optional[str] = None
    completed: Optional[float] = None
    version: Optional[str] = None


class TaskModel(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    max_steps: int = 30
    status: Optional[str] = None
    threads: Optional[List[RoleThreadModel]] = None
    assigned_to: Optional[str] = None
    created: float = Field(default_factory=time.time)
    started: float = 0.0
    completed: float = 0.0
    error: Optional[str] = None
    output: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = {}
    version: Optional[str] = None
    remote: Optional[str] = None
    owner_id: Optional[str] = None


class TasksModel(BaseModel):
    tasks: List[TaskModel]


class V1UserProfile(BaseModel):
    email: Optional[str] = None
    display_name: Optional[str] = None
    handle: Optional[str] = None
    picture: Optional[str] = None
    created: Optional[int] = None
    updated: Optional[int] = None
    token: Optional[str] = None


class AgentModel(BaseModel):
    name: str
    config: BaseModel


class SolveTaskModel(BaseModel):
    task: TaskModel
    device: Optional[DeviceModel] = None
    agent: Optional[AgentModel] = None
    max_steps: int = 30

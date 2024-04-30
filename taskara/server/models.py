from typing import Optional, List, Dict, Any
import uuid
import time

from threadmem.server.models import V1RoleThread, V1RoleMessage
from pydantic import BaseModel, Field
from devicebay.models import DeviceModel
from mllm import V1Prompt


class V1TaskUpdate(BaseModel):
    status: Optional[str] = None
    description: Optional[str] = None
    max_steps: Optional[int] = None
    error: Optional[str] = None
    output: Optional[str] = None
    assigned_to: Optional[str] = None
    completed: Optional[float] = None
    version: Optional[str] = None


class V1Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    max_steps: int = 30
    status: Optional[str] = None
    threads: Optional[List[V1RoleThread]] = None
    prompts: Optional[List[V1Prompt]] = None
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
    tags: List[str] = []
    labels: Dict[str, str] = {}
    episode_id: Optional[str] = None


class V1Tasks(BaseModel):
    tasks: List[V1Task]


class V1UserProfile(BaseModel):
    email: Optional[str] = None
    display_name: Optional[str] = None
    handle: Optional[str] = None
    picture: Optional[str] = None
    created: Optional[int] = None
    updated: Optional[int] = None
    token: Optional[str] = None


class V1Agent(BaseModel):
    name: str
    config: BaseModel


class V1SolveTask(BaseModel):
    task: V1Task
    device: Optional[DeviceModel] = None
    agent: Optional[V1Agent] = None
    max_steps: int = 30


class V1CreateTask(BaseModel):
    task: V1Task
    device: str
    agent: Optional[V1Agent] = None
    max_steps: int = 30


class V1AddThread(BaseModel):
    public: bool
    name: Optional[str] = None
    metadata: Optional[dict] = None
    id: Optional[str] = None


class V1RemoveThread(BaseModel):
    id: str


class V1PostMessage(BaseModel):
    role: str
    msg: str
    images: List[str] = []
    thread: Optional[str] = None

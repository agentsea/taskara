import time
from typing import Any, Dict, List, Optional

import shortuuid
from devicebay import V1Device, V1DeviceType
from devicebay.models import V1Device
from mllm import V1Prompt
from pydantic import BaseModel, Field
from threadmem.server.models import V1RoleThread


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
    id: str = Field(default_factory=lambda: shortuuid.uuid())
    description: str
    max_steps: int = 30
    device: Optional[V1Device] = None
    device_type: Optional[V1DeviceType] = None
    expect_schema: Optional[Dict[str, Any]] = None
    status: Optional[str] = None
    threads: Optional[List[V1RoleThread]] = None
    prompts: Optional[List[str]] = None
    assigned_to: Optional[str] = None
    assigned_type: Optional[str] = None
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
    auth_token: Optional[str] = None


class V1Tasks(BaseModel):
    tasks: List[V1Task]


class V1TaskTemplate(BaseModel):
    id: str = Field(default_factory=lambda: shortuuid.uuid())
    description: str
    max_steps: int = 30
    device: Optional[V1Device] = None
    device_type: Optional[V1DeviceType] = None
    expect_schema: Optional[Dict[str, Any]] = None
    parameters: Optional[Dict[str, Any]] = {}
    owner_id: Optional[str] = None
    tags: List[str] = []
    labels: Dict[str, str] = {}
    created: float = Field(default_factory=lambda: time.time())


class V1TaskTemplates(BaseModel):
    templates: List[V1TaskTemplate]


class V1UserProfile(BaseModel):
    email: Optional[str] = None
    display_name: Optional[str] = None
    handle: Optional[str] = None
    picture: Optional[str] = None
    created: Optional[int] = None
    updated: Optional[int] = None
    token: Optional[str] = None


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


class V1TrackerRuntimeConnect(BaseModel):
    name: str
    connect_config: BaseModel


class V1Tracker(BaseModel):
    name: str
    runtime: V1TrackerRuntimeConnect
    version: Optional[str] = None
    port: int = 9090
    labels: Dict[str, str] = {}
    tags: List[str] = []
    status: str
    owner_id: Optional[str] = None
    created: float
    updated: float


class V1Runtime(BaseModel):
    type: str
    preference: List[str] = []


class V1ResourceLimits(BaseModel):
    cpu: str = "2"
    memory: str = "2Gi"


class V1ResourceRequests(BaseModel):
    cpu: str = "1"
    memory: str = "500m"
    gpu: Optional[str] = None


class V1Prompts(BaseModel):
    prompts: List[V1Prompt]


class V1Benchmark(BaseModel):
    id: str = Field(default_factory=lambda: shortuuid.uuid())
    name: str
    description: str
    tasks: List[V1TaskTemplate]
    owner_id: Optional[str] = None
    tags: List[str] = []
    labels: Dict[str, str] = {}
    created: float = Field(default_factory=lambda: time.time())
    public: bool = False


class V1BenchmarkEval(BaseModel):
    assigned_to: str | None = None
    assigned_type: str | None = None


class V1Benchmarks(BaseModel):
    benchmarks: List[V1Benchmark]


class V1Eval(BaseModel):
    id: Optional[str] = None
    benchmark: V1Benchmark
    tasks: List[V1Task]
    assigned_to: Optional[str] = None
    assigned_type: Optional[str] = None
    owner_id: Optional[str] = None


class V1Evals(BaseModel):
    evals: List[V1Eval]

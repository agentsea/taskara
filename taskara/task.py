import uuid
import time
from typing import List, Optional, TypeVar, Any, Dict
import requests
import os
import json
import hashlib
import logging
import copy

from threadmem import RoleThread, RoleMessage
from mllm import Prompt
from skillpacks import Episode, ActionEvent, V1Action, V1ToolRef
from devicebay import V1Device, V1DeviceType

from .db.models import TaskRecord
from .db.conn import WithDB
from .server.models import V1Prompt, V1Task, V1TaskUpdate, V1Tasks
from .env import HUB_API_KEY_ENV

T = TypeVar("T", bound="Task")
logger = logging.getLogger(__name__)


class Task(WithDB):
    """An agent task"""

    def __init__(
        self,
        description: Optional[str] = None,
        max_steps: int = 30,
        owner_id: Optional[str] = None,
        device: Optional[V1Device] = None,
        device_type: Optional[V1DeviceType] = None,
        id: Optional[str] = None,
        status: str = "defined",
        created: Optional[float] = None,
        started: float = 0.0,
        completed: float = 0.0,
        threads: List[RoleThread] = [],
        prompts: List[Prompt] = [],
        assigned_to: Optional[str] = None,
        assigned_type: Optional[str] = None,
        error: Optional[str] = None,
        output: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = {},
        remote: Optional[str] = None,
        version: Optional[str] = None,
        labels: Dict[str, str] = {},
        tags: List[str] = [],
        episode: Optional[Episode] = None,
    ):
        self._id = id if id is not None else str(uuid.uuid4())
        self._description = description
        self._max_steps = max_steps
        self._owner_id = owner_id
        self._device = device
        self._device_type = device_type
        self._status = status
        self._created = created if created is not None else time.time()
        self._started = started
        self._completed = completed
        self._assigned_to = assigned_to
        self._assigned_type = assigned_type
        self._error = error
        self._output = output
        self._parameters = parameters
        self._remote = remote
        self._prompts = prompts
        self._labels = labels
        self._tags = tags
        self._episode = episode if episode else Episode()

        self._threads = []
        self.ensure_thread("feed")
        if threads:
            self._threads.extend(threads)

        self._version = version if version is not None else self.generate_version_hash()

        if not self._remote and not self._description:
            raise ValueError("Task must have a description or a remote task")
        if self._remote:
            if not self._id:
                raise ValueError("ID must be set for remote tasks")
            logger.debug("calling remote task", self._id)
            existing_task = self._remote_request(
                self._remote, "GET", f"/v1/tasks/{self._id}"
            )
            if not existing_task:
                raise ValueError("Remote task not found")
            logger.debug("\nfound existing task", existing_task)
            self.refresh()
            logger.debug("\nrefreshed tasks")
            logger.debug("\ntask: ", self.__dict__)
        else:
            self._remote = None
            self.save()

    @property
    def id(self) -> str:
        return self._id

    @property
    def description(self) -> Optional[str]:
        return self._description

    @description.setter
    def description(self, value: Optional[str]):
        self._description = value

    @property
    def max_steps(self) -> int:
        return self._max_steps

    @max_steps.setter
    def max_steps(self, value: int):
        self._max_steps = value

    @property
    def device(self) -> Optional[V1Device]:
        return self._device

    @device.setter
    def device(self, value: Optional[V1Device]):
        self._device = value

    @property
    def device_type(self) -> Optional[V1DeviceType]:
        return self._device_type

    @device_type.setter
    def device_type(self, value: Optional[V1DeviceType]):
        self._device_type = value

    @property
    def owner_id(self) -> Optional[str]:
        return self._owner_id

    @owner_id.setter
    def owner_id(self, value: Optional[str]):
        self._owner_id = value

    @property
    def status(self) -> str:
        return self._status

    @status.setter
    def status(self, value: str):
        self._status = value

    @property
    def created(self) -> float:
        return self._created

    @created.setter
    def created(self, value: float):
        self._created = value

    @property
    def started(self) -> float:
        return self._started

    @started.setter
    def started(self, value: float):
        self._started = value

    @property
    def parameters(self) -> Optional[Dict[str, Any]]:
        return self._parameters

    @parameters.setter
    def parameters(self, value: Dict[str, Any]):
        self._parameters = value

    @property
    def completed(self) -> float:
        return self._completed

    @completed.setter
    def completed(self, value: float):
        self._completed = value

    @property
    def threads(self) -> List[RoleThread]:
        return self._threads

    @threads.setter
    def threads(self, value: List[RoleThread]):
        self._threads = value

    @property
    def assigned_to(self) -> Optional[str]:
        return self._assigned_to

    @assigned_to.setter
    def assigned_to(self, value: Optional[str]):
        self._assigned_to = value

    @property
    def assigned_type(self) -> Optional[str]:
        return self._assigned_type

    @assigned_type.setter
    def assigned_type(self, value: Optional[str]):
        self._assigned_type = value

    @property
    def error(self) -> Optional[str]:
        return self._error

    @error.setter
    def error(self, value: str):
        self._error = value

    @property
    def output(self) -> Optional[str]:
        return self._output

    @output.setter
    def output(self, value: str):
        self._output = value

    @property
    def remote(self) -> Optional[str]:
        return self._remote

    @remote.setter
    def remote(self, value: str):
        self._remote = value

    @property
    def labels(self) -> Dict[str, str]:
        return self._labels

    @labels.setter
    def labels(self, value: Dict[str, str]):
        self._labels = value

    @property
    def tags(self) -> List[str]:
        return self._tags

    @tags.setter
    def tags(self, value: List[str]):
        self._tags = value

    def generate_version_hash(self) -> str:
        task_data = json.dumps(self.to_v1().model_dump(), sort_keys=True)
        hash_version = hashlib.sha256(task_data.encode("utf-8")).hexdigest()
        return hash_version

    def to_record(self) -> TaskRecord:
        version = None
        if hasattr(self, "_version"):
            version = self._version

        device = None
        if self._device:
            device = self._device.model_dump_json()

        device_type = None
        if self._device_type:
            device_type = self._device_type.model_dump_json()

        return TaskRecord(
            id=self._id,
            owner_id=self._owner_id,
            description=self._description,
            max_steps=self._max_steps,
            device=device,
            device_type=device_type,
            status=self._status,
            created=self._created,
            started=self._started,
            completed=self._completed,
            assigned_to=self._assigned_to,
            assigned_type=self._assigned_type,
            error=self._error,
            output=self._output,
            threads=json.dumps([t._id for t in self._threads]),
            prompts=json.dumps([p._id for p in self._prompts]),
            parameters=json.dumps(self._parameters),
            version=version,
            tags=json.dumps(self.tags),
            labels=json.dumps(self.labels),
            episode_id=self._episode.id,
        )

    @classmethod
    def from_record(cls, record: TaskRecord) -> "Task":
        thread_ids = json.loads(str(record.threads))
        threads = [RoleThread.find(id=thread_id)[0] for thread_id in thread_ids]

        prompt_ids = json.loads(str(record.prompts))
        prompts = [Prompt.find(id=prompt_id)[0] for prompt_id in prompt_ids]

        parameters = json.loads(str(record.parameters))

        episodes = Episode.find(id=record.episode_id)
        episode = episodes[0]

        device = None
        if record.device:  # type: ignore
            device = V1Device.model_validate_json(str(record.device))

        device_type = None
        if record.device_type:  # type: ignore
            device_type = V1DeviceType.model_validate_json(str(record.device_type))

        obj = cls.__new__(cls)
        obj._id = record.id
        obj._owner_id = record.owner_id
        obj._description = record.description
        obj._max_steps = record.max_steps
        obj._device = device
        obj._device_type = device_type
        obj._status = record.status
        obj._created = record.created
        obj._started = record.started
        obj._completed = record.completed
        obj._assigned_to = record.assigned_to
        obj._assigned_type = record.assigned_type
        obj._error = record.error
        obj._output = record.output
        obj._threads = threads
        obj._prompts = prompts
        obj._version = record.version
        obj._parameters = parameters
        obj._remote = None
        obj.tags = json.loads(str(record.tags))
        obj._labels = json.loads(str(record.labels))
        obj._episode = episode
        return obj

    def post_message(
        self,
        role: str,
        msg: str,
        images: List[str] = [],
        private: bool = False,
        metadata: Optional[dict] = None,
        thread: Optional[str] = None,
    ) -> None:
        logger.debug(f"posting message to thread {thread}: ", msg)
        if hasattr(self, "_remote") and self._remote:
            logger.debug("posting msg to remote task", self._id)
            try:
                data = {"msg": msg, "role": role, "images": images}
                if thread:
                    data["thread"] = thread
                self._remote_request(
                    self._remote,
                    "POST",
                    f"/v1/tasks/{self.id}/msg",
                    data,
                )
                return
            except Exception as e:
                print("failed to post message to remote: ", e)
                raise

        if not thread:
            thread = "feed"

        logger.debug("finding local thread...")
        for thrd in self._threads:
            logger.debug("checking thread: ", thrd.name, thrd.id)
            if thrd.id == thread or thrd.name == thread:
                logger.debug("found local thread")
                thrd.post(role, msg, images, private, metadata)
                return

        raise ValueError(f"Thread by name or id '{thread}' not found")

    def record_action(
        self,
        prompt: Prompt | str,
        action: V1Action,
        tool: V1ToolRef,
        result: Optional[Any] = None,
        namespace: str = "default",
        metadata: dict = {},
        owner_id: Optional[str] = None,
        model: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> ActionEvent:
        if not owner_id:
            owner_id = self.owner_id
        return self._episode.record(
            prompt=prompt,
            action=action,
            tool=tool,
            result=result,
            namespace=namespace,
            metadata=metadata,
            owner_id=owner_id,
            model=model,
            agent_id=agent_id,
        )

    def copy(self) -> "Task":
        """
        Creates a deep copy of the current Task instance with a new unique ID and reset timestamps.

        Returns:
            Task: A new Task instance that is a copy of the current instance with a new unique ID and timestamps.
        """
        # Use the copy.deepcopy function to ensure that all mutable objects are also copied.
        copied_task = copy.deepcopy(self)

        # Resetting the unique ID and timestamps
        copied_task._id = str(uuid.uuid4())
        now = time.time()
        copied_task._created = now
        copied_task._started = 0.0
        copied_task._completed = 0.0

        # Assuming you may want to start with an undefined status or any other initial value
        copied_task._status = "defined"

        # Reset version and potentially other properties that should be unique to each new task
        copied_task._version = copied_task.generate_version_hash()

        return copied_task

    def store_prompt(
        self,
        thread: RoleThread,
        response: RoleMessage,
        namespace: str = "default",
        metadata: Dict[str, Any] = {},
    ) -> None:
        if hasattr(self, "_remote") and self._remote:
            logger.debug("creting remote thread")
            self._remote_request(
                self._remote,
                "POST",
                f"/v1/tasks/{self._id}/prompts",
                V1Prompt(
                    thread=thread.to_v1(),
                    response=response.to_v1(),
                    namespace=namespace,
                    metadata=metadata,
                ).model_dump(),
            )
            logger.debug("stored prompt")
            return

        prompt = Prompt(thread, response, namespace, metadata)
        self._prompts.append(prompt)
        self.save()

    def approve_prompt(self, prompt_id: str) -> None:
        if hasattr(self, "_remote") and self._remote:
            logger.debug("creting remote thread")
            self._remote_request(
                self._remote,
                "POST",
                f"/v1/tasks/{self._id}/prompts/{prompt_id}/approve",
            )
            logger.debug("approved prompt")
            return

        prompts = Prompt.find(id=prompt_id)
        if not prompts:
            raise ValueError(f"Prompt with id '{prompt_id}' not found")
        prompt = prompts[0]
        prompt.approved = True
        prompt.save()

    def create_thread(
        self,
        name: Optional[str] = None,
        public: bool = False,
        metadata: Optional[dict] = None,
        id: Optional[str] = None,
    ) -> None:
        if hasattr(self, "_remote") and self._remote:
            logger.debug("creting remote thread")
            self._remote_request(
                self._remote,
                "POST",
                f"/v1/tasks/{self._id}/threads",
                {"name": name, "public": public, "metadata": metadata, "id": id},
            )
            logger.debug("removed remote thread")
            return

        logger.debug("creating thread")

        existing_threads = [t for t in self._threads if t.id == id or t.name == name]
        if existing_threads:
            raise ValueError(f"Thread with name '{name}' already exists")
        thread = RoleThread(self.owner_id, public, name, metadata)
        self._threads.append(thread)
        self.save()
        logger.debug("created local thread")
        return

    def ensure_thread(
        self,
        name: Optional[str] = None,
        public: bool = False,
        metadata: Optional[dict] = None,
        id: Optional[str] = None,
    ) -> None:
        for thread in self.threads:
            if thread.name == name:
                return None

        self.create_thread(name, public, metadata, id)

    def remove_thread(self, thread_id: str) -> None:
        if hasattr(self, "_remote") and self._remote:
            logger.debug("removing remote thread")
            self._remote_request(
                self._remote,
                "DELETE",
                f"/v1/tasks/{self._id}/threads",
                {"id": thread_id},
            )
            logger.debug("removed remote thread")
            return

        self._threads = [t for t in self._threads if t._id != thread_id]
        self.save()

    def messages(self, thread: Optional[str] = None) -> List[RoleMessage]:
        if not thread:
            thread = "feed"

        for thrd in self._threads:
            if thrd.name == thread:
                return thrd.messages()

        raise ValueError(f"Thread {thread} not found")

    def save(self) -> None:
        logger.debug("saving task", self._id)
        # Generate the new version hash
        self._episode.save()
        new_version = self.generate_version_hash()

        if hasattr(self, "_remote") and self._remote:
            logger.debug("saving remote task", self._id)
            try:
                existing_task = self._remote_request(
                    self._remote, "GET", f"/v1/tasks/{self._id}"
                )
                logger.debug("found existing task", existing_task)

                if existing_task["version"] != self._version:
                    pass
                    # print("WARNING: current task version is different from remote, you could be overriding changes")
            except Exception:
                existing_task = None
            if existing_task:
                logger.debug("updating existing task", existing_task)
                if self._version != new_version:
                    self._version = new_version
                    logger.debug(f"Version updated to {self._version}")

                self._remote_request(
                    self._remote,
                    "PUT",
                    f"/v1/tasks/{self._id}",
                    json_data=self.to_update_v1().model_dump(),
                )
                logger.debug("updated existing task", self._id)
            else:
                logger.debug("creating new task", self._id)
                if self._version != new_version:
                    self._version = new_version
                    logger.debug(f"Version updated to {self._version}")

                self._remote_request(
                    self._remote,
                    "POST",
                    "/v1/tasks",
                    json_data=self.to_v1().model_dump(),
                )
                logger.debug("created new task", self._id)
        else:
            logger.debug("saving local db task", self._id)
            if hasattr(self, "_version"):
                if self._version != new_version:
                    self._version = new_version
                    logger.debug(f"Version updated to {self._version}")

            for db in self.get_db():
                db.merge(self.to_record())
                db.commit()

    @classmethod
    def find(cls, remote: Optional[str] = None, **kwargs) -> List["Task"]:
        if remote:
            logger.debug("finding remote tasks for: ", remote, kwargs["owner_id"])
            remote_response = cls._remote_request(
                remote, "GET", "/v1/tasks", json_data={**kwargs, "sort": "created_desc"}
            )
            tasks = V1Tasks(**remote_response)
            if remote_response is not None:
                out = [
                    cls.from_v1(record, kwargs["owner_id"]) for record in tasks.tasks
                ]
                for task in out:
                    task._remote = remote
                    logger.debug("returning task: ", task.__dict__)
                return out
            else:
                return []
        else:
            for db in cls.get_db():
                records = (
                    db.query(TaskRecord)
                    .filter_by(**kwargs)
                    .order_by(TaskRecord.created.desc())
                    .all()
                )
                return [cls.from_record(record) for record in records]
            raise ValueError("No session")

    def update(self, **kwargs) -> None:
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)

        self.save()

    @classmethod
    def delete(cls, id: str, owner_id: str, remote: Optional[str] = None) -> None:
        if remote:
            cls._remote_request(remote, "DELETE", f"/v1/tasks/{id}")
        else:
            for db in cls.get_db():
                record = (
                    db.query(TaskRecord).filter_by(id=id, owner_id=owner_id).first()
                )
                if record:
                    db.delete(record)
                    db.commit()

    def to_v1(self) -> V1Task:
        version = None
        if hasattr(self, "_version"):
            version = self._version

        remote = None
        if hasattr(self, "_remote"):
            remote = self._remote

        return V1Task(
            id=self._id,
            description=self._description if self._description else "",
            max_steps=self._max_steps,
            device=self._device,
            device_type=self.device_type,
            threads=[t.to_v1() for t in self._threads],
            prompts=[p.to_v1() for p in self._prompts],
            status=self._status,
            created=self._created,
            started=self._started,
            completed=self._completed,
            assigned_to=self._assigned_to,
            assigned_type=self._assigned_type,
            error=self._error,
            output=self._output,
            parameters=self._parameters,
            version=version,
            remote=remote,
            owner_id=self._owner_id,
            tags=self._tags,
            labels=self._labels,
            episode_id=self._episode.id,
        )

    def to_update_v1(self) -> V1TaskUpdate:
        return V1TaskUpdate(
            description=self._description,
            max_steps=self._max_steps,
            status=self._status,
            assigned_to=self._assigned_to,
            error=self._error,
            output=self._output,
            completed=self._completed,
            version=self._version,
        )

    @classmethod
    def from_v1(cls, v1: V1Task, owner_id: Optional[str] = None) -> "Task":
        obj = cls.__new__(cls)  # Create a new instance without calling __init__

        owner_id = owner_id if owner_id else v1.owner_id
        if not owner_id:
            raise ValueError("Owner id is required in v1 or as parameter")

        # Manually set attributes on the object
        obj._id = v1.id if v1.id else str(uuid.uuid4())
        obj._owner_id = owner_id
        obj._description = v1.description
        obj._max_steps = v1.max_steps
        obj._device = v1.device
        obj._device_type = v1.device_type
        obj._status = v1.status if v1.status else "defined"
        obj._created = v1.created
        obj._started = v1.started
        obj._completed = v1.completed
        obj._assigned_to = v1.assigned_to
        obj._assigned_type = v1.assigned_type
        obj._error = v1.error
        obj._output = v1.output
        obj._version = v1.version
        obj._remote = v1.remote
        obj._parameters = v1.parameters
        obj._remote = v1.remote
        obj._owner_id = owner_id
        obj._tags = v1.tags
        obj._labels = v1.labels

        episodes = Episode.find(id=v1.episode_id)
        if not episodes:
            raise ValueError(f"Episode {v1.episode_id} not found")
        obj._episode = episodes[0]

        if v1.threads:
            obj._threads = [RoleThread.from_v1(s) for s in v1.threads]
        else:
            obj._threads = [RoleThread(owner_id=owner_id, name="feed")]

        if v1.prompts:
            obj._prompts = [Prompt.from_v1(p) for p in v1.prompts]
        else:
            obj._prompts = []

        return obj

    def refresh(self, auth_token: Optional[str] = None) -> None:
        logger.debug("refreshing task", self._id)
        if hasattr(self, "_remote") and self._remote:
            logger.debug("refreshing remote task", self._id)
            try:

                remote_task = self._remote_request(
                    self._remote, "GET", f"/v1/tasks/{self._id}", auth_token=auth_token
                )
                logger.debug("found remote task", remote_task)
                if remote_task:
                    v1 = V1Task(**remote_task)
                    self._description = v1.description
                    self._max_steps = v1.max_steps
                    self._device = v1.device
                    self._device_type = v1.device_type
                    self._status = v1.status if v1.status else "defined"
                    self._created = v1.created
                    self._started = v1.started
                    self._completed = v1.completed
                    self._assigned_to = v1.assigned_to
                    self._assigned_type = v1.assigned_type
                    self._error = v1.error
                    self._output = v1.output
                    self._version = v1.version
                    self._parameters = v1.parameters
                    if v1.threads:
                        self._threads = [RoleThread.from_v1(wt) for wt in v1.threads]
                    if v1.prompts:
                        self._prompts = [Prompt.from_v1(p) for p in v1.prompts]
                    else:
                        self._prompts = []
                    logger.debug("\nrefreshed remote task", self._id)
            except requests.RequestException as e:
                raise e
        else:
            raise ValueError("Refresh is only supported for remote tasks")

    @classmethod
    def _remote_request(
        cls,
        addr: str,
        method: str,
        endpoint: str,
        json_data: Optional[dict] = None,
        auth_token: Optional[str] = None,
    ) -> Any:
        url = f"{addr}{endpoint}"
        headers = {}
        if not auth_token:
            auth_token = os.getenv(HUB_API_KEY_ENV)
            if not auth_token:
                raise Exception(f"Hub API key not found, set ${HUB_API_KEY_ENV}")
        logger.debug(f"auth_token: {auth_token}")
        headers["Authorization"] = f"Bearer {auth_token}"
        try:
            if method.upper() == "GET":
                logger.debug("\ncalling remote task GET with url: ", url)
                logger.debug("\ncalling remote task GET with headers: ", headers)
                response = requests.get(url, headers=headers)
            elif method.upper() == "POST":
                logger.debug("\ncalling remote task POST with: ", url)
                logger.debug("\ncalling remote task POST with headers: ", headers)
                response = requests.post(url, json=json_data, headers=headers)
            elif method.upper() == "PUT":
                logger.debug("\ncalling remote task PUT with: ", url)
                logger.debug("\ncalling remote task PUT with headers: ", headers)
                response = requests.put(url, json=json_data, headers=headers)
            elif method.upper() == "DELETE":
                logger.debug("\ncalling remote task DELETE with: ", url)
                logger.debug("\ncalling remote task DELETE with headers: ", headers)
                response = requests.delete(url, headers=headers)
            else:
                return None

            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError as e:
                print("HTTP Error:", e)
                print("Status Code:", response.status_code)
                try:
                    print("Response Body:", response.json())
                except ValueError:
                    print("Raw Response:", response.text)
                raise
            logger.debug("\nresponse: ", response.__dict__)
            logger.debug("\response.status_code: ", response.status_code)

            try:
                response_json = response.json()
                logger.debug("\nresponse_json: ", response_json)
                return response_json
            except ValueError:
                print("Raw Response:", response.text)
                return None

        except requests.RequestException as e:
            raise e

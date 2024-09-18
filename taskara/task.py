import base64
import copy
import hashlib
import json
import logging
import os
import time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, TypeVar

import requests
import shortuuid
from cryptography.fernet import Fernet
from devicebay import V1Device, V1DeviceType
from mllm import Prompt, V1Prompt
from PIL import Image
from pydantic import BaseModel
from skillpacks import (
    ActionEvent,
    Episode,
    V1Action,
    V1Episode,
    V1ToolRef,
    V1EnvState,
    Review,
)
from threadmem import RoleMessage, RoleThread, V1RoleThreads
from threadmem.server.models import V1RoleMessage

from .config import GlobalConfig
from .db.conn import WithDB
from .db.models import TaskRecord, LabelRecord, TagRecord
from .env import HUB_API_KEY_ENV
from .img import image_to_b64
from .server.models import (
    V1Prompts,
    V1Task,
    V1Tasks,
    V1TaskUpdate,
)
from .flag import Flag
from .review import ReviewRequirement, PendingReviewers

T = TypeVar("T", bound="Task")
logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Task status"""

    DEFINED = "defined"
    CREATED = "created"
    IN_PROGRESS = "in progress"
    FINISHED = "finished"
    FAILED = "failed"
    ERROR = "error"
    WAITING = "waiting"
    CANCELING = "canceling"
    CANCELED = "canceled"
    TIMED_OUT = "timed out"


FINAL_STATUSES = [
    TaskStatus.FAILED,
    TaskStatus.ERROR,
    TaskStatus.CANCELED,
    TaskStatus.CANCELING,
    TaskStatus.TIMED_OUT,
]


class Task(WithDB):
    """An agent task"""

    def __init__(
        self,
        description: Optional[str] = None,
        max_steps: int = 30,
        owner_id: Optional[str] = None,
        project: Optional[str] = None,
        device: Optional[V1Device] = None,
        device_type: Optional[V1DeviceType] = None,
        expect: Optional[Type[BaseModel]] = None,
        id: Optional[str] = None,
        status: TaskStatus = TaskStatus.DEFINED,
        created: Optional[float] = None,
        started: float = 0.0,
        completed: float = 0.0,
        threads: List[RoleThread] = [],
        prompts: List[Prompt] = [],
        assigned_to: Optional[str] = None,
        assigned_type: Optional[str] = None,
        reviews: List[Review] = [],
        review_requirements: List[ReviewRequirement] = [],
        error: Optional[str] = None,
        output: Optional[str] = None,
        parameters: Dict[str, Any] = {},
        remote: Optional[str] = None,
        version: Optional[str] = None,
        parent_id: Optional[str] = None,
        labels: Dict[str, str] = {},
        tags: List[str] = [],
        episode: Optional[Episode] = None,
        auth_token: Optional[str] = None,
    ):
        self._id = id if id is not None else shortuuid.uuid()
        self._description = description
        self._max_steps = max_steps
        self._owner_id = owner_id
        self._project = project
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
        self._reviews = reviews
        self._review_requirements = review_requirements
        self._remote = remote
        self._prompts = prompts
        self._parent_id = parent_id
        self._labels = labels
        self._tags = tags
        self._episode = episode
        self._expect_schema = expect.model_json_schema() if expect else None
        self._auth_token = auth_token
        self._flags: List[Flag] = []

        self._threads = []
        if threads:
            self._threads.extend(threads)

        self._version = version if version is not None else self.generate_version_hash()

        if not self._remote and not self._description:
            raise ValueError("Task must have a description or a remote task")

        self.save()
        self.ensure_thread("feed")
        self.update_pending_reviews()

    @classmethod
    def get_encryption_key(cls) -> bytes:
        # Step 1: Try to get the key from an environment variable
        key = os.getenv("ENCRYPTION_KEY")
        if key:
            return key.encode()

        # Define the path for the local encryption key file
        key_path = Path.home() / ".agentsea/keys/taskara_encryption_key"

        # Step 2: Try to get the key from a local file
        try:
            if key_path.exists():
                with key_path.open("rb") as file:
                    return file.read()
        except IOError as e:
            print(f"Failed to read the encryption key from {key_path}: {e}")

        print(
            "No encryption key found. Generating a new one. "
            "This key will be stored in ~/.agentsea/keys/taskara_encryption_key"
        )
        # Step 3: Generate a new key and store it if neither of the above worked
        key = Fernet.generate_key()
        try:
            key_path.parent.mkdir(
                parents=True, exist_ok=True
            )  # Ensure the directory exists
            with key_path.open("wb") as file:
                file.write(key)
        except IOError as e:
            print(f"Failed to write the new encryption key to {key_path}: {e}")
            raise Exception("Failed to secure an encryption key.")

        return key

    def encrypt_device(self, device: Optional[V1Device]) -> Optional[str]:
        if not device:
            return None
        key = self.get_encryption_key()
        fernet = Fernet(key)
        encrypted_private_key = fernet.encrypt(device.model_dump_json().encode())
        return base64.b64encode(encrypted_private_key).decode()

    @classmethod
    def decrypt_device(
        cls, encrypted_device: Optional[str] = None
    ) -> Optional[V1Device]:
        if not encrypted_device:
            return None
        key = cls.get_encryption_key()
        fernet = Fernet(key)
        decrypted_private_key = fernet.decrypt(base64.b64decode(encrypted_device))
        return V1Device.model_validate_json(decrypted_private_key.decode())

    @classmethod
    def get(
        cls, id: str, remote: Optional[str] = None, auth_token: Optional[str] = None
    ) -> "Task":
        """Get a task by id"""
        if remote:
            resp = cls._remote_request(
                remote, "GET", f"/v1/tasks/{id}", auth_token=auth_token
            )
            resp["remote"] = remote
            task = cls.from_v1(V1Task.model_validate(resp))
            return task

        tasks = cls.find(id=id)
        if not tasks:
            raise ValueError(f"No task with id {id} found")
        task = tasks[0]
        return task

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
    def expect(self) -> Optional[Dict[str, Any]]:
        return self._expect_schema

    @expect.setter
    def expect(self, value: Optional[Type[BaseModel]]):
        self._expect_schema = value.model_json_schema() if value else None

    @property
    def owner_id(self) -> Optional[str]:
        return self._owner_id

    @owner_id.setter
    def owner_id(self, value: Optional[str]):
        self._owner_id = value

    @property
    def reviews(self) -> List[Review]:
        return self._reviews

    @reviews.setter
    def reviews(self, value: List[Review]):
        self._reviews = value

    @property
    def review_requirements(self) -> List[ReviewRequirement]:
        return self._review_requirements

    @review_requirements.setter
    def review_requirements(self, value: List[ReviewRequirement]):
        self._review_requirements = value

    @property
    def project(self) -> Optional[str]:
        return self._project

    @project.setter
    def project(self, value: Optional[str]):
        self._project = value

    @property
    def episode(self) -> Optional[Episode]:
        return self._episode

    @property
    def status(self) -> TaskStatus:
        return self._status

    @status.setter
    def status(self, value: TaskStatus):
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
    def parent_id(self) -> Optional[str]:
        return self._parent_id

    @parent_id.setter
    def parent_id(self, value: Optional[str]):
        self._parent_id = value

    @property
    def tags(self) -> List[str]:
        return self._tags

    @tags.setter
    def tags(self, value: List[str]):
        self._tags = value

    @property
    def flags(self) -> List[Flag]:
        return self._flags

    def flag(self, flag: Flag) -> None:
        self._flags.append(flag)

    def is_done(self) -> bool:
        return self._status in FINAL_STATUSES

    def generate_version_hash(self) -> str:
        task_data = json.dumps(self.to_v1().model_dump(), sort_keys=True)
        hash_version = hashlib.sha256(task_data.encode("utf-8")).hexdigest()
        return hash_version

    def to_record(self) -> TaskRecord:
        version = None
        if hasattr(self, "_version"):
            version = self._version

        device_type = None
        if self._device_type:
            device_type = self._device_type.model_dump_json()

        expect = None
        if self._expect_schema:
            expect = json.dumps(self._expect_schema)

        if not hasattr(self, "_episode") or not self._episode:
            raise ValueError("episode not set")

        review_ids = []
        for review in self.reviews:
            review_ids.append(review.id)
            review.save()

        requirement_ids = []
        for req in self._review_requirements:
            requirement_ids.append(req.id)
            req.save()

        # Create the TaskRecord object without tags/labels initially
        task_record = TaskRecord(
            id=self._id,
            owner_id=self._owner_id,
            description=self._description,
            max_steps=self._max_steps,
            device=self.encrypt_device(self._device),
            device_type=device_type,
            project=self._project,
            expect=expect,
            reviews=json.dumps(review_ids),
            review_requirements=json.dumps(requirement_ids),
            status=self._status.value,
            created=self._created,
            started=self._started,
            completed=self._completed,
            assigned_to=self._assigned_to,
            assigned_type=self._assigned_type,
            error=self._error,
            output=self._output,
            parent_id=self._parent_id,
            threads=json.dumps([t._id for t in self._threads]),
            prompts=json.dumps([p._id for p in self._prompts]),
            parameters=json.dumps(self._parameters),
            version=version,
            episode_id=self._episode.id,
        )

        # Attach tags
        if hasattr(self, "_tags"):
            task_record.tags = [TagRecord(tag=tag) for tag in self._tags]

        # Attach labels
        if hasattr(self, "_labels"):
            task_record.labels = [
                LabelRecord(key=key, value=value) for key, value in self._labels.items()
            ]

        return task_record

    @classmethod
    def from_record(cls, record: TaskRecord) -> "Task":
        thread_ids = json.loads(str(record.threads))
        threads = [RoleThread.find(id=thread_id)[0] for thread_id in thread_ids]

        prompt_ids = json.loads(str(record.prompts))
        prompts = [Prompt.find(id=prompt_id)[0] for prompt_id in prompt_ids]

        review_ids = json.loads(str(record.reviews))
        reviews = [Review.find(id=id)[0] for id in review_ids]

        review_req_ids = json.loads(str(record.review_requirements))
        review_reqs = [ReviewRequirement.find(id=id)[0] for id in review_req_ids]

        parameters = json.loads(str(record.parameters))

        episodes = Episode.find(id=record.episode_id)
        if not episodes:
            raise ValueError("episode not found")
        episode = episodes[0]

        device_type = None
        if record.device_type:  # type: ignore
            device_type = V1DeviceType.model_validate_json(str(record.device_type))

        expect = None
        if record.expect:  # type: ignore
            expect = json.loads(str(record.expect))

        obj = cls.__new__(cls)
        obj._id = record.id
        obj._owner_id = record.owner_id
        obj._description = record.description
        obj._max_steps = record.max_steps
        obj._project = record.project
        obj._device = cls.decrypt_device(record.device)  # type: ignore
        obj._device_type = device_type
        obj._expect_schema = expect
        obj._reviews = reviews
        obj._review_requirements = review_reqs
        obj._status = TaskStatus(record.status)
        obj._created = record.created
        obj._started = record.started
        obj._completed = record.completed
        obj._assigned_to = record.assigned_to
        obj._assigned_type = record.assigned_type
        obj._error = record.error
        obj._output = record.output
        obj._threads = threads
        obj._prompts = prompts
        obj._parent_id = record.parent_id
        obj._version = record.version
        obj._parameters = parameters
        obj._remote = None

        # Load tags
        obj._tags = [tag.tag for tag in record.tags]

        # Load labels
        obj._labels = {label.key: label.value for label in record.labels}

        obj._episode = episode

        return obj

    def post_message(
        self,
        role: str,
        msg: str,
        images: List[str | Image.Image] = [],
        private: bool = False,
        metadata: Optional[dict] = None,
        thread: Optional[str] = None,
    ) -> None:
        logger.debug(f"posting message to thread {thread}: {msg}")
        new_imgs: List[str] = []
        for img in images:
            if isinstance(img, Image.Image):
                new_imgs.append(image_to_b64(img))
            elif isinstance(img, str):
                if img.startswith("data:") or img.startswith("http"):
                    new_imgs.append(img)
                else:
                    loaded_img = Image.open(img)
                    new_imgs.append(image_to_b64(loaded_img))
            else:
                raise ValueError("unnknown image type")

        if hasattr(self, "_remote") and self._remote:
            logger.debug(f"posting msg to remote task: {self._id}")
            try:
                data = {"msg": msg, "role": role, "images": new_imgs}
                if thread:
                    data["thread"] = thread
                self._remote_request(
                    self._remote,
                    "POST",
                    f"/v1/tasks/{self.id}/msg",
                    data,
                    auth_token=self.auth_token,
                )
                return
            except Exception as e:
                logger.error(f"failed to post message to remote: {e}")
                raise

        if not thread:
            thread = "feed"

        logger.debug("finding local thread...")
        for thrd in self._threads:
            logger.debug(f"checking thread: {thrd.name} {thrd.id}")
            if thrd.id == thread or thrd.name == thread:
                logger.debug("found local thread")
                thrd.post(role, msg, images, private, metadata)
                return

        raise ValueError(f"Thread by name or id '{thread}' not found")

    @classmethod
    def _get_prompts(
        cls,
        task_id: Optional[str] = None,
        remote: Optional[str] = None,
        ids: Optional[List[str]] = None,
        auth_token: Optional[str] = None,
    ) -> List[Prompt]:
        if remote:
            try:
                prompt_data = cls._remote_request(
                    remote,
                    "GET",
                    f"/v1/tasks/{task_id}/prompts",
                    auth_token=auth_token,
                )
                v1prompts = V1Prompts.model_validate(prompt_data)
                out = []
                for prompt in v1prompts.prompts:
                    out.append(Prompt.from_v1(prompt))

                return out

            except Exception as e:
                logger.error(f"failed to get prompts from remote: {e}")
                raise

        if not ids:
            raise ValueError("expected ids or remote")
        out = []
        for id in ids:
            prompts = Prompt.find(id=id)
            if not prompts:
                raise ValueError(f"Prompt by id '{id}' not found")
            out.append(prompts[0])

        return out

    @classmethod
    def _get_episode(
        cls,
        task_id: Optional[str] = None,
        remote: Optional[str] = None,
        id: Optional[str] = None,
        auth_token: Optional[str] = None,
    ) -> Episode:
        if remote:
            try:
                episode_data = cls._remote_request(
                    remote,
                    "GET",
                    f"/v1/tasks/{task_id}/episode",
                    auth_token=auth_token,
                )
                v1episode = V1Episode.model_validate(episode_data)
                return Episode.from_v1(v1episode)

            except Exception as e:
                logger.error(f"failed to get prompts from remote: {e}")
                raise

        if not id:
            ep = Episode()
            ep.save()
            return ep

        episodes = Episode.find(id=id)
        if not episodes:
            raise ValueError(f"Episode by id '{id}' not found")
        return episodes[0]

    def record_action(
        self,
        state: V1EnvState,
        action: V1Action,
        tool: V1ToolRef,
        result: Optional[Any] = None,
        end_state: Optional[V1EnvState] = None,
        prompt: Optional[Prompt | str] = None,
        namespace: str = "default",
        metadata: dict = {},
        owner_id: Optional[str] = None,
        model: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> ActionEvent:
        if not owner_id:
            owner_id = self.owner_id

        if hasattr(self, "_remote") and self._remote:
            logger.debug(f"posting msg to remote task: {self._id}")
            try:
                if isinstance(prompt, str):
                    prompt = Prompt.find(id=prompt)[0]

                event = ActionEvent(
                    state=state,
                    prompt=prompt,
                    action=action,
                    tool=tool,
                    result=result,
                    end_state=end_state,
                    namespace=namespace,
                    metadata=metadata,
                    owner_id=owner_id,
                    model=model,
                    agent_id=agent_id,
                )
                data = event.to_v1().model_dump()
                self._remote_request(
                    self._remote,
                    "POST",
                    f"/v1/tasks/{self.id}/actions",
                    data,
                    auth_token=self.auth_token,
                )
                return event

            except Exception as e:
                logger.error(f"failed to post message to remote: {e}")
                raise

        if not hasattr(self, "_episode") or not self._episode:
            raise ValueError("episode not set")

        return self._episode.record(
            state=state,
            prompt=prompt,
            action=action,
            tool=tool,
            result=result,
            end_state=end_state,
            namespace=namespace,
            metadata=metadata,
            owner_id=owner_id,
            model=model,
            agent_id=agent_id,
        )

    @property
    def auth_token(self) -> Optional[str]:
        if hasattr(self, "_auth_token"):
            return self._auth_token
        return None

    @auth_token.setter
    def auth_token(self, token: str) -> None:
        self._auth_token = token

    def record_action_event(
        self,
        event: ActionEvent,
    ) -> None:
        if hasattr(self, "_remote") and self._remote:
            logger.debug(f"posting msg to remote task {self._id}")
            try:
                data = event.to_v1().model_dump()
                self._remote_request(
                    self._remote,
                    "POST",
                    f"/v1/tasks/{self.id}/actions",
                    data,
                    auth_token=self.auth_token,
                )
                return

            except Exception as e:
                logger.error(f"failed to post message to remote: {e}")
                raise

        if not hasattr(self, "_episode") or not self._episode:
            raise ValueError("episode not set")

        self._episode.record_event(event)
        return

    def copy(self) -> "Task":
        """
        Creates a deep copy of the current Task instance with a new unique ID and reset timestamps.

        Returns:
            Task: A new Task instance that is a copy of the current instance with a new unique ID and timestamps.
        """
        # Use the copy.deepcopy function to ensure that all mutable objects are also copied.
        copied_task = copy.deepcopy(self)

        # Resetting the unique ID and timestamps
        copied_task._id = shortuuid.uuid()
        now = time.time()
        copied_task._created = now
        copied_task._started = 0.0
        copied_task._completed = 0.0

        # Assuming you may want to start with an undefined status or any other initial value
        copied_task._status = TaskStatus.DEFINED

        # Reset version and potentially other properties that should be unique to each new task
        copied_task._version = copied_task.generate_version_hash()

        return copied_task

    def wait_for_done(
        self, timeout: int = 1200, print_status: bool = True, sleep: int = 1
    ) -> None:
        """
        Waits for the task to complete.
        """
        start = time.time()

        while not self.is_done():
            if print_status:
                print("task status: ", self.status)
            time.sleep(sleep)
            self.refresh()
            if time.time() > start + timeout:
                raise TimeoutError(
                    f"Task {self._id} did not complete within {timeout} seconds."
                )

    def _episode_satified(self, user: str) -> bool:
        episode = self.episode
        if not episode:
            raise ValueError("episode not set")
        episode_satisfied = True
        for action in episode.actions:
            action_satisfied = False
            for review in action.reviews:
                if review.reviewer == user:
                    action_satisfied = True
                    break
            if not action_satisfied:
                episode_satisfied = False

        return episode_satisfied

    def _review_satisfied(self, user: str) -> bool:
        review_satisfied = False
        for review in self.reviews:
            if review.reviewer == user:
                review_satisfied = True
                break
        return review_satisfied

    def update_pending_reviews(self) -> None:
        """Updates the pending reviewers table for the task"""
        revs = PendingReviewers()

        for req in self._review_requirements:
            req_satisfied = False
            total_approvals = 0

            all_potential_reviewers = [*req.agents, *req.users]
            for user in all_potential_reviewers:
                episode = self.episode
                if not episode:
                    raise ValueError("episode not set")

                episode_satisfied = self._episode_satified(user)
                if not episode_satisfied:
                    continue

                review_satisfied = self._review_satisfied(user)
                if not review_satisfied:
                    continue

                total_approvals += 1

            if total_approvals >= req.number_required:
                req_satisfied = True

            if req_satisfied:
                for user in req.users:
                    logger.debug(f"removing pending reviewer: {user}")
                    revs.remove_pending_reviewer(
                        task_id=self.id, user=user, requirement_id=req.id
                    )
                for agent in req.agents:
                    logger.debug(f"removing pending reviewer: {agent}")
                    revs.remove_pending_reviewer(
                        task_id=self.id, user=agent, requirement_id=req.id
                    )
            else:
                for user in req.users:
                    logger.debug(f"adding pending reviewer: {user}")
                    revs.ensure_pending_reviewer(
                        task_id=self.id, user=user, requirement_id=req.id
                    )
                for agent in req.agents:
                    logger.debug(f"adding pending reviewer: {agent}")
                    revs.ensure_pending_reviewer(
                        task_id=self.id, user=agent, requirement_id=req.id
                    )

    def store_prompt(
        self,
        thread: RoleThread,
        response: RoleMessage,
        response_schema: Optional[type[BaseModel]] = None,
        namespace: str = "default",
        metadata: Dict[str, Any] = {},
        owner_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        model: Optional[str] = None,
    ) -> str:
        if hasattr(self, "_remote") and self._remote:
            logger.debug("creting remote thread")
            resp = self._remote_request(
                self._remote,
                "POST",
                f"/v1/tasks/{self._id}/prompts",
                V1Prompt(
                    thread=thread.to_v1(),
                    response=response.to_v1(),
                    response_schema=(
                        response_schema.model_json_schema() if response_schema else None
                    ),
                    namespace=namespace,
                    metadata=metadata,
                    agent_id=agent_id,
                    model=model,
                ).model_dump(),
                auth_token=self.auth_token,
            )
            logger.debug("stored prompt")
            return resp["id"]

        prompt = Prompt(
            thread=thread,
            response=response,
            response_schema=response_schema,
            namespace=namespace,
            metadata=metadata,
            owner_id=owner_id,
            agent_id=agent_id,
            model=model,
        )
        prompt.save()

        logger.debug(f"stored prompt: {prompt.id}")
        self._prompts.append(prompt)
        self.save()
        return prompt.id

    def add_prompt(
        self,
        prompt: Prompt,
    ) -> None:
        if hasattr(self, "_remote") and self._remote:
            logger.debug("creting remote thread")
            self._remote_request(
                self._remote,
                "POST",
                f"/v1/tasks/{self._id}/prompts",
                V1Prompt(
                    thread=prompt.thread.to_v1(),
                    response=prompt.response.to_v1(),
                    response_schema=prompt.response_schema,
                    namespace=prompt.namespace,
                    metadata=prompt.metadata,
                    agent_id=prompt.agent_id,
                    model=prompt.model,
                ).model_dump(),
                auth_token=self.auth_token,
            )
            logger.debug("stored prompt")
            return

        self._prompts.append(prompt)
        self.save()

    def approve_prompt(self, prompt_id: str) -> None:
        if hasattr(self, "_remote") and self._remote:
            logger.debug("creting remote thread")
            self._remote_request(
                self._remote,
                "POST",
                f"/v1/tasks/{self._id}/prompts/{prompt_id}/approve",
                auth_token=self.auth_token,
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
                auth_token=self.auth_token,
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
        if hasattr(self, "_remote") and self._remote:
            threads_dict = self._remote_request(
                self._remote,
                "GET",
                f"/v1/tasks/{self._id}/threads",
                auth_token=self.auth_token,
            )
            v1threads = V1RoleThreads.model_validate(threads_dict)
            for thread in v1threads.threads:
                if thread.name == name:
                    return None
        else:
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
                auth_token=self.auth_token,
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
        logger.debug(f"saving task {self._id}")
        # Generate the new version hash
        new_version = self.generate_version_hash()

        if hasattr(self, "_remote") and self._remote:
            logger.debug(f"saving remote task {self._id}")
            try:
                existing_task = self._remote_request(
                    self._remote,
                    "GET",
                    f"/v1/tasks/{self._id}",
                    auth_token=self.auth_token,
                    suppress_not_found=True,
                )
                logger.debug(f"found existing task: {existing_task}")

                if existing_task["version"] != self._version:
                    pass
                    # print("WARNING: current task version is different from remote, you could be overriding changes")
            except Exception:
                existing_task = None

            if existing_task:
                logger.debug(f"updating existing task {existing_task}")
                if self._version != new_version:
                    self._version = new_version
                    logger.debug(f"Version updated to {self._version}")

                self._remote_request(
                    self._remote,
                    "PUT",
                    f"/v1/tasks/{self._id}",
                    json_data=self.to_update_v1().model_dump(),
                    auth_token=self.auth_token,
                )
                logger.debug(f"updated existing task: {self._id}")
            else:
                logger.debug(f"creating new task {self._id}")
                if self._version != new_version:
                    self._version = new_version
                    logger.debug(f"Version updated to {self._version}")

                resp = self._remote_request(
                    self._remote,
                    "POST",
                    "/v1/tasks",
                    json_data=self.to_v1().model_dump(),
                    auth_token=self.auth_token,
                )
                logger.debug(f"created new task {self._id}")
        else:
            logger.debug(f"saving local db task: {self._id}")
            if hasattr(self, "_version"):
                if self._version != new_version:
                    self._version = new_version
                    logger.debug(f"Version updated to {self._version}")

            if not hasattr(self, "_episode") or not self._episode:
                self._episode = Episode()
            self._episode.save()

            for db in self.get_db():
                db.merge(self.to_record())
                db.commit()

    @classmethod
    def find(
        cls,
        remote: Optional[str] = None,
        auth_token: Optional[str] = None,
        tags: Optional[List[str]] = None,
        labels: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> List["Task"]:
        if remote:
            logger.debug(f"finding remote tasks for: {remote}")
            remote_response = cls._remote_request(
                remote,
                "GET",
                "/v1/tasks",
                json_data={
                    **kwargs,
                    "sort": "created_desc",
                    "tags": tags,
                    "labels": labels,
                },
                auth_token=auth_token,
            )
            tasks = V1Tasks(**remote_response)
            if remote_response is not None:
                out = [
                    cls.from_v1(record, kwargs["owner_id"]) for record in tasks.tasks
                ]
                for task in out:
                    task._remote = remote
                    logger.debug(f"returning task: {task.__dict__}")
                return out
            else:
                return []
        else:
            for db in cls.get_db():
                query = db.query(TaskRecord)

                # Apply task-specific filters from kwargs (e.g., owner_id)
                query = query.filter_by(**kwargs)

                # Handle tag filtering if tags are provided
                if tags:
                    query = query.join(TaskRecord.tags).filter(TagRecord.tag.in_(tags))

                # Handle label filtering if labels are provided
                if labels:
                    for key, value in labels.items():
                        query = query.join(TaskRecord.labels).filter(
                            LabelRecord.key == key, LabelRecord.value == value
                        )

                # Apply sorting by creation date and retrieve the records
                records = query.order_by(TaskRecord.created.desc()).all()

                return [cls.from_record(record) for record in records]

            raise ValueError("No session")

    def update(self, **kwargs) -> None:
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)

        self.save()

    @classmethod
    def delete(
        cls,
        id: str,
        owner_id: str,
        remote: Optional[str] = None,
        auth_token: Optional[str] = None,
    ) -> None:
        if remote:
            cls._remote_request(
                remote, "DELETE", f"/v1/tasks/{id}", auth_token=auth_token
            )
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

        if not hasattr(self, "_episode"):
            self._episode = None

        episode_id = None
        if self._episode:
            episode_id = self._episode.id

        return V1Task(
            id=self._id,
            description=self._description if self._description else "",
            max_steps=self._max_steps,
            device=self._device,
            device_type=self.device_type,
            expect_schema=self._expect_schema,
            threads=[t.to_v1() for t in self._threads],
            prompts=[p.id for p in self._prompts],
            status=self._status.value,
            created=self._created,
            started=self._started,
            completed=self._completed,
            assigned_to=self._assigned_to,
            assigned_type=self._assigned_type,
            reviews=[r.to_v1() for r in self._reviews],
            review_requirements=[
                review.to_v1() for review in self._review_requirements
            ],
            error=self._error,
            output=self._output,
            parameters=self._parameters,
            version=version,
            remote=remote,
            owner_id=self._owner_id,
            parent_id=self._parent_id,
            project=self._project,
            tags=self._tags,
            labels=self._labels,
            episode_id=episode_id,
            auth_token=self.auth_token,
        )

    def to_update_v1(self) -> V1TaskUpdate:
        return V1TaskUpdate(
            description=self._description,
            max_steps=self._max_steps,
            status=self._status.value,
            assigned_to=self._assigned_to,
            error=self._error,
            output=self._output,
            completed=self._completed,
            version=self._version,
        )

    @classmethod
    def from_v1(
        cls,
        v1: V1Task,
        owner_id: Optional[str] = None,
        auth_token: Optional[str] = None,
    ) -> "Task":
        obj = cls.__new__(cls)  # Create a new instance without calling __init__

        owner_id = owner_id if owner_id else v1.owner_id
        if not owner_id:
            raise ValueError("Owner id is required in v1 or as parameter")

        status = v1.status if v1.status else "defined"
        task_status = TaskStatus(status)

        # Manually set attributes on the object
        obj._id = v1.id if v1.id else shortuuid.uuid()
        obj._owner_id = owner_id
        obj._description = v1.description
        obj._max_steps = v1.max_steps
        obj._device = v1.device
        obj._device_type = v1.device_type
        obj._expect_schema = v1.expect_schema
        obj._status = task_status
        obj._created = v1.created
        obj._started = v1.started
        obj._completed = v1.completed
        obj._assigned_to = v1.assigned_to
        obj._assigned_type = v1.assigned_type
        obj._reviews = [Review.from_v1(r) for r in v1.reviews]
        obj._review_requirements = [
            ReviewRequirement.from_v1(r) for r in v1.review_requirements
        ]
        obj._error = v1.error
        obj._output = v1.output
        obj._version = v1.version
        obj._remote = v1.remote
        obj._parameters = v1.parameters
        obj._parent_id = v1.parent_id
        obj._remote = v1.remote
        obj._owner_id = owner_id
        obj._project = v1.project
        obj._tags = v1.tags
        obj._labels = v1.labels
        obj._auth_token = auth_token if auth_token else v1.auth_token

        obj._episode = cls._get_episode(
            task_id=v1.id,
            remote=v1.remote,
            id=v1.episode_id,
            auth_token=obj._auth_token,
        )

        if v1.threads:
            obj._threads = [RoleThread.from_v1(s) for s in v1.threads]
        else:
            obj._threads = [RoleThread(owner_id=owner_id, name="feed")]

        if v1.prompts:
            obj._prompts = cls._get_prompts(
                task_id=v1.id,
                remote=v1.remote,
                ids=v1.prompts,
                auth_token=obj._auth_token,
            )
        else:
            obj._prompts = []

        return obj

    def refresh(self) -> None:
        logger.debug(f"refreshing task {self._id}")
        if hasattr(self, "_remote") and self._remote:
            logger.debug(f"refreshing remote task {self._id}")
            try:
                remote_task = self._remote_request(
                    self._remote,
                    "GET",
                    f"/v1/tasks/{self._id}",
                    auth_token=self.auth_token,
                )
                logger.debug(f"found remote task {remote_task}")
                if remote_task:
                    v1 = V1Task(**remote_task)
                    status = v1.status if v1.status else "defined"
                    task_status = TaskStatus(status)
                    self._description = v1.description
                    self._max_steps = v1.max_steps
                    self._device = v1.device
                    self._device_type = v1.device_type
                    self._expect_schema = v1.expect_schema
                    self._status = task_status
                    self._created = v1.created
                    self._started = v1.started
                    self._completed = v1.completed
                    self._assigned_to = v1.assigned_to
                    self._assigned_type = v1.assigned_type
                    self._error = v1.error
                    self._output = v1.output
                    self._version = v1.version
                    self._parameters = v1.parameters
                    self._project = v1.project
                    self._parent_id = v1.parent_id
                    self._review_requirements = [
                        ReviewRequirement.from_v1(requirement)
                        for requirement in v1.review_requirements
                    ]
                    self._reviews = [Review.from_v1(r) for r in v1.reviews]
                    self._episode = self._get_episode(
                        task_id=v1.id,
                        remote=self._remote,
                        id=v1.episode_id,
                        auth_token=self.auth_token,
                    )
                    if v1.threads:
                        self._threads = [RoleThread.from_v1(wt) for wt in v1.threads]
                    if v1.prompts:
                        self._prompts = self._get_prompts(
                            task_id=v1.id,
                            remote=self._remote,
                            ids=v1.prompts,
                            auth_token=self.auth_token,
                        )
                    else:
                        self._prompts = []
                    logger.debug(f"refreshed remote task {self._id}")
            except requests.RequestException as e:
                raise e
        else:
            tasks = self.find(id=self._id)
            task = tasks[0]
            self._description = task._description
            self._max_steps = task._max_steps
            self._device = task._device
            self._device_type = task._device_type
            self._project = task._project
            self._expect_schema = task._expect_schema
            self._status = task._status
            self._created = task._created
            self._started = task._started
            self._completed = task._completed
            self._assigned_to = task._assigned_to
            self._assigned_type = task._assigned_type
            self._reviews = task._reviews
            self._review_requirements = task._review_requirements
            self._error = task._error
            self._output = task._output
            self._version = task._version
            self._parameters = task._parameters
            self._parent_id = task._parent_id
            self._threads = task._threads
            self._prompts = task._prompts
            logger.debug(f"refreshed local task {self._id}")

    @classmethod
    def _remote_request(
        cls,
        addr: str,
        method: str,
        endpoint: str,
        json_data: Optional[dict] = None,
        auth_token: Optional[str] = None,
        suppress_not_found: bool = False,
    ) -> Any:
        url = f"{addr}{endpoint}"
        logger.debug(f"calling remote task {method} {url}")
        headers = {}
        if not auth_token:
            auth_token = os.getenv(HUB_API_KEY_ENV)
            logger.debug(f"using hub auth token found in env var {HUB_API_KEY_ENV}")

            config = GlobalConfig.read()
            if config.api_key:
                auth_token = config.api_key
                logger.debug("using hub auth token found in global config")

        if auth_token:
            logger.debug(f"auth_token: {auth_token}")
            headers["Authorization"] = f"Bearer {auth_token}"
        try:
            if method.upper() == "GET":
                logger.debug(f"calling remote task GET with url: {url}")
                logger.debug(f"calling remote task GET with headers: {headers}")
                response = requests.get(url, headers=headers)
            elif method.upper() == "POST":
                logger.debug(f"calling remote task POST with: {url}")
                logger.debug(f"calling remote task POST with headers: {headers}")
                response = requests.post(url, json=json_data, headers=headers)
            elif method.upper() == "PUT":
                logger.debug(f"calling remote task PUT with: {url}")
                logger.debug(f"calling remote task PUT with headers: {headers}")
                response = requests.put(url, json=json_data, headers=headers)
            elif method.upper() == "DELETE":
                logger.debug(f"calling remote task DELETE with: {url}")
                logger.debug(f"calling remote task DELETE with headers: {headers}")
                response = requests.delete(url, headers=headers)
            else:
                return None

            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError as e:
                if response.status_code == 404 and suppress_not_found:
                    logger.debug("suppressing 404 not found error")
                    raise

                logger.error(f"HTTP Error: {e}")
                logger.error(f"Status Code: {response.status_code}")
                try:
                    logger.error(f"Response Body: {response.json()}")
                except ValueError:
                    logger.error(f"Raw Response: {response.text}")
                raise
            logger.debug(f"response: {response.__dict__}")
            logger.debug(f"response.status_code: {response.status_code}")

            try:
                response_json = response.json()
                logger.debug(f"response_json: {response_json}")
                return response_json
            except ValueError:
                logger.debug(f"Raw Response: {response.text}")
                return None

        except requests.RequestException as e:
            raise e


class TaskClient:
    """A remote client for tasks"""

    def __init__(self, base_url: str, auth_token: Optional[str] = None):
        self.base_url = base_url
        self.auth_token = auth_token

    def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        url = f"{self.base_url}{endpoint}"
        headers = (
            {"Authorization": f"Bearer {self.auth_token}"} if self.auth_token else {}
        )
        response = requests.request(
            method, url, json=data, params=params, headers=headers
        )

        try:
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as e:
            print(f"HTTP Error: {response.status_code} {e}")
            print(response.text)
            raise
        except ValueError:
            return response.text  # If the response isn't JSON

    def create_task(self, task: V1Task) -> V1Task:
        data = task.model_dump()
        response = self._request("POST", "/v1/tasks", data=data)
        return V1Task.model_validate(response)

    def get_task(self, task_id: str) -> V1Task:
        response = self._request("GET", f"/v1/tasks/{task_id}")
        return V1Task.model_validate(response)

    def update_task(self, task_id: str, task: V1TaskUpdate) -> V1Task:
        data = task.model_dump()
        response = self._request("PUT", f"/v1/tasks/{task_id}", data=data)
        return V1Task.model_validate(response)

    def delete_task(self, task_id: str) -> None:
        self._request("DELETE", f"/v1/tasks/{task_id}")

    def post_message(self, task_id: str, message: V1RoleMessage) -> None:
        response = self._request(
            "POST", f"/v1/tasks/{task_id}/msg", data=message.model_dump()
        )
        return

    def record_action(self, task_id: str, action: V1Action) -> None:
        data = action.model_dump()
        response = self._request("POST", f"/v1/tasks/{task_id}/actions", data=data)
        return None

    def approve_prompt(self, task_id: str, prompt_id: str) -> None:
        endpoint = f"/v1/tasks/{task_id}/prompts/{prompt_id}/approve"
        self._request("POST", endpoint)

    def add_prompt(self, task_id: str, prompt: V1Prompt) -> None:
        data = prompt.model_dump()
        response = self._request("POST", f"/v1/tasks/{task_id}/prompts", data=data)
        return

    def get_prompts(self, task_id: str) -> List[V1Prompt]:
        response = self._request("GET", f"/v1/tasks/{task_id}/prompts")
        return [V1Prompt.model_validate(prompt) for prompt in response]

    def list_tasks(self, filters: Optional[Dict[str, Any]] = None) -> List[V1Task]:
        response = self._request("GET", "/v1/tasks", params=filters)
        return [V1Task.model_validate(task) for task in response]

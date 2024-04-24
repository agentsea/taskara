import uuid
import time
import logging
import json
from typing import Optional, Dict, Any, List

from pydantic import BaseModel
from threadmem import RoleThread, RoleMessage, RoleThreadModel
from threadmem.server.models import RoleMessageModel

from .db.models import PromptRecord
from .db.conn import WithDB

logger = logging.getLogger(__name__)


class PromptModel(BaseModel):
    id: str
    namespace: str = "default"
    thread: RoleThreadModel
    response: RoleMessageModel
    created: float
    metadata: Dict[str, Any] = {}


class Prompt(WithDB):
    """A communication prompt"""

    def __init__(
        self,
        thread: RoleThread,
        response: RoleMessage,
        namespace: str = "default",
        metadata: Dict[str, Any] = {},
        id: Optional[str] = None,
        created: float = time.time(),
    ):
        self._id = id if id else str(uuid.uuid4())
        self._namespace = namespace
        self._thread = thread
        self._response = response
        self._metadata = metadata
        self._created = created

    @property
    def id(self) -> str:
        return self._id

    @property
    def namespace(self) -> str:
        return self._namespace

    @namespace.setter
    def namespace(self, value: str):
        self._namespace = value

    @property
    def thread(self) -> RoleThread:
        return self._thread

    @thread.setter
    def thread(self, value: RoleThread):
        self._thread = value

    @property
    def response(self) -> RoleMessage:
        return self._response

    @response.setter
    def response(self, value: RoleMessage):
        self._response = value

    @property
    def metadata(self) -> Dict[str, Any]:
        return self._metadata

    @metadata.setter
    def metadata(self, value: Dict[str, Any]):
        self._metadata = value

    @property
    def created(self) -> float:
        return self._created

    @created.setter
    def created(self, value: float):
        self._created = value

    def to_record(self) -> PromptRecord:
        # Serialize the response using RoleMessageModel's json() method
        if not self.metadata:
            self.metadata = {}

        return PromptRecord(
            id=self._id,
            namespace=self._namespace,
            thread_id=self._thread.id,
            response=self._response.to_schema().model_dump_json(),
            metadata=json.dumps(self._metadata),
            created=self._created,
        )

    @classmethod
    def from_record(cls, record: PromptRecord) -> "Prompt":
        # Deserialize thread_id into a RoleThreadModel using a suitable method or lookup
        threads = RoleThread.find(id=record.thread_id)
        if not threads:
            raise Exception("Thread not found")
        thread = threads[0]

        response = RoleMessageModel.model_validate_json(str(record.response))
        metadata = json.loads(record.metadata) if record.metadata else {}  # type: ignore
        return cls(
            id=record.id,  # type: ignore
            namespace=record.namespace,  # type: ignore
            thread=thread,
            response=response,  # type: ignore
            metadata=metadata,
            created=record.created,  # type: ignore
        )

    def to_schema(self) -> PromptModel:
        return PromptModel(
            id=self._id,
            namespace=self._namespace,
            thread=self._thread.to_schema(),
            response=self._response.to_schema(),
            metadata=self._metadata,
            created=self._created,
        )

    @classmethod
    def from_schema(cls, schema: PromptModel) -> "Prompt":
        obj = cls.__new__(cls)

        obj._id = schema.id
        obj._namespace = schema.namespace
        obj._thread = RoleThread.from_schema(schema.thread)
        obj._response = RoleMessage.from_schema(schema.response)
        obj._metadata = schema.metadata
        obj._created = schema.created

        return obj

    def save(self) -> None:
        logger.debug("saving prompt", self._id)
        for db in self.get_db():
            db.merge(self.to_record())
            db.commit()

    @classmethod
    def delete(cls, id: str) -> None:
        for db in cls.get_db():
            record = db.query(PromptRecord).filter_by(id=id).first()
            if record:
                db.delete(record)
                db.commit()

    def update(self, **kwargs) -> None:
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.save()

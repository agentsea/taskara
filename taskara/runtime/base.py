import json
import time
from abc import ABC, abstractmethod
from typing import Dict, Generic, Iterator, List, Optional, Tuple, Type, TypeVar, Union

import shortuuid
from pydantic import BaseModel

from taskara.db.conn import WithDB
from taskara.db.models import TrackerRecord
from taskara.server.models import (
    V1ResourceLimits,
    V1ResourceRequests,
    V1Tracker,
    V1TrackerRuntimeConnect,
)

R = TypeVar("R", bound="TrackerRuntime")
C = TypeVar("C", bound="BaseModel")


class Tracker(WithDB):
    """A task server"""

    def __init__(
        self,
        name: str,
        port: int,
        runtime: "TrackerRuntime",
        status: str = "running",
        owner_id: Optional[str] = None,
        labels: Optional[Dict[str, str]] = None,
    ) -> None:
        self._id = shortuuid.uuid()
        self._name = name
        self._port = port
        self._status = status
        self._runtime = runtime
        self._owner_id = owner_id
        self._created = time.time()
        self._updated = time.time()
        self._labels = labels

        self.save()

    @property
    def id(self) -> str:
        return self._id

    @property
    def status(self) -> str:
        return self._status

    @property
    def name(self) -> str:
        return self._name

    @property
    def runtime(self) -> "TrackerRuntime":
        return self._runtime

    @property
    def port(self) -> int:
        return self._port

    @property
    def owner_id(self) -> Optional[str]:
        return self._owner_id

    @property
    def created(self) -> float:
        return self._created

    @property
    def updated(self) -> float:
        return self._updated

    @property
    def labels(self) -> Optional[Dict[str, str]]:
        return self._labels

    def proxy(
        self,
        local_port: Optional[int] = None,
        background: bool = True,
    ) -> Optional[int]:
        return self._runtime.proxy(self._name, local_port, self.port, background)

    def delete(self, force: bool = False) -> None:
        """
        Deletes the server instance from the runtime and the database.
        """
        # First, delete the server instance from the runtime.
        try:
            self._runtime.delete(self._name)
        except Exception as e:
            if not force:
                raise e

        # After the runtime deletion, proceed to delete the record from the database.
        for db in self.get_db():
            record = db.query(TrackerRecord).filter_by(id=self._id).one()
            db.delete(record)
            db.commit()

    def logs(self, follow: bool = False) -> Union[str, Iterator[str]]:
        """
        Fetches the logs from the specified pod.

        Parameters:
            follow (bool): If True, stream logs until the connection

        Returns:
            str: The logs from the pod.
        """
        return self._runtime.logs(self._name, follow)

    def save(self) -> None:
        for db in self.get_db():
            record = self.to_record()
            db.merge(record)
            db.commit()

    @classmethod
    def find(cls, **kwargs) -> List["Tracker"]:
        for db in cls.get_db():
            records = (
                db.query(TrackerRecord)
                .filter_by(**kwargs)
                .order_by(TrackerRecord.created.desc())
                .all()
            )
            return [cls.from_record(record) for record in records]
        raise ValueError("No session")

    @classmethod
    def active_runtimes(cls) -> List["TrackerRuntime"]:
        """Get all runtimes currently being used by a tracker

        Returns:
            List[TrackerRuntime]: a list of tracker runtimes
        """
        trackers = cls.find()
        return [tracker.runtime for tracker in trackers]

    def to_v1(self) -> V1Tracker:
        """Convert to V1 API model"""
        return V1Tracker(
            name=self._name,
            runtime=V1TrackerRuntimeConnect(
                name=self._runtime.name(), connect_config=self.runtime.connect_config()
            ),
            port=self._port,
            status=self._status,
            owner_id=self._owner_id,
            created=self._created,
            updated=self._updated,
            labels=self._labels or {},
        )

    def to_record(self) -> TrackerRecord:
        """Convert to DB model"""
        runtime_cfg = self._runtime.connect_config().model_dump_json()

        return TrackerRecord(
            id=self._id,
            name=self._name,
            runtime_name=self._runtime.name(),
            runtime_config=runtime_cfg,
            port=self._port,
            status=self._status,
            owner_id=self._owner_id,
            created=self._created,
            updated=self._updated,
            labels=json.dumps(self._labels or {}),
        )

    @classmethod
    def from_record(cls, record: TrackerRecord) -> "Tracker":
        from taskara.runtime.load import runtime_from_name

        runtype = runtime_from_name(str(record.runtime_name))
        runcfg = runtype.connect_config_type().model_validate_json(
            str(record.runtime_config)
        )
        runtime = runtype.connect(runcfg)

        obj = cls.__new__(cls)
        obj._id = str(record.id)
        obj._name = str(record.name)
        obj._runtime = runtime
        obj._status = record.status
        obj._port = record.port
        obj._owner_id = record.owner_id
        obj._created = record.created
        obj._updated = record.updated
        obj._labels = json.loads(record.labels) if record.labels else None  # type: ignore

        return obj

    def call(
        self,
        path: str,
        method: str,
        data: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Tuple[int, str]:
        """Call the task server

        Args:
            path (str): Path to call
            method (str): Method to use
            data (Optional[dict], optional): Body data. Defaults to None.
            headers (Optional[dict], optional): Headers. Defaults to None.

        Returns:
            Tuple[int, str]: Status code and response text
        """
        return self.runtime.call(
            name=self.name,
            path=path,
            method=method,
            port=self.port,
            data=data,
            headers=headers,
        )


class TrackerRuntime(Generic[R, C], ABC):

    @classmethod
    def name(cls) -> str:
        return cls.__name__

    @classmethod
    @abstractmethod
    def connect_config_type(cls) -> Type[C]:
        """The pydantic model which defines the schema for connecting to this runtime

        Returns:
            Type[C]: The type
        """
        pass

    @abstractmethod
    def connect_config(cls) -> C:
        """The connect config for this runtime instance

        Returns:
            C: Connect config
        """
        pass

    @classmethod
    @abstractmethod
    def connect(cls, cfg: C) -> R:
        """Connect to the runtime using this configuration

        Args:
            cfg (C): Connect config

        Returns:
            R: A runtime
        """
        pass

    @abstractmethod
    def run(
        self,
        name: str,
        env_vars: Optional[dict] = None,
        owner_id: Optional[str] = None,
        labels: Optional[Dict[str, str]] = None,
        resource_requests: V1ResourceRequests = V1ResourceRequests(),
        resource_limits: V1ResourceLimits = V1ResourceLimits(),
        auth_enabled: bool = True,
    ) -> Tracker:
        """Run the task server

        Args:
            name (str): Name of the task server
            env_vars (Optional[dict], optional): Env vars to supply. Defaults to None.
            owner_id (Optional[str], optional): Owner ID. Defaults to None.
            labels (Optional[Dict[str, str]], optional): Labels for the task server. Defaults to None.
            resource_requests (V1ResourceRequests, optional): Resource requests. Defaults to V1ResourceRequests().
            resource_limits (V1ResourceLimits, optional): Resource limits. Defaults to V1ResourceLimits().
            auth_enabled (bool, optional): Whether to enable auth. Defaults to True.

        Returns:
            Tracker: An task server instance
        """
        pass

    @abstractmethod
    def list(
        self, owner_id: Optional[str] = None, source: bool = False
    ) -> List[Tracker]:
        """List task server instances

        Args:
            owner_id (Optional[str], optional): An optional owner id. Defaults to None.
            source (bool, optional): Whether to list directly from the source. Defaults to False.

        Returns:
            List[Tracker]: A list of task server instances
        """
        pass

    @abstractmethod
    def get(
        self, name: str, owner_id: Optional[str] = None, source: bool = False
    ) -> Tracker:
        """Get an task server instance

        Args:
            name (str): Name of the task server
            owner_id (Optional[str], optional): Optional owner ID. Defaults to None.
            source (bool, optional): Whether to fetch directly from the source. Defaults to False.

        Returns:
            Tracker: An task server instance
        """
        pass

    @abstractmethod
    def requires_proxy(self) -> bool:
        """Whether this runtime requires a proxy to be used"""
        pass

    @abstractmethod
    def proxy(
        self,
        name: str,
        local_port: Optional[int] = None,
        tracker_port: int = 9070,
        background: bool = True,
        owner_id: Optional[str] = None,
    ) -> Optional[int]:
        """Proxy a port to the task server

        Args:
            name (str): Name of the task server
            local_port (Optional[int], optional): Local port to proxy to. Defaults to None.
            tracker_port (int, optional): The task servers port. Defaults to 9070.
            background (bool, optional): Whether to run the proxy in the background. Defaults to True.
            owner_id (Optional[str], optional): An optional owner ID. Defaults to None.

        Returns:
                Optional[int]: The pid of the proxy
        """
        pass

    @abstractmethod
    def delete(self, name: str, owner_id: Optional[str] = None) -> None:
        """Delete an task server instance

        Args:
            name (str): Name of the task server
            owner_id (Optional[str], optional): An optional owner id. Defaults to None.
        """
        pass

    @abstractmethod
    def clean(self, owner_id: Optional[str] = None) -> None:
        """Delete all task server instances

        Args:
            owner_id (Optional[str], optional): An optional owner ID to scope it to. Defaults to None.
        """
        pass

    @abstractmethod
    def logs(
        self, name: str, follow: bool = False, owner_id: Optional[str] = None
    ) -> Union[str, Iterator[str]]:
        """
        Fetches the logs from the specified task server.

        Parameters:
            name (str): The name of the task server.

        Returns:
            str: The logs from the task server.
        """
        pass

    @abstractmethod
    def call(
        self,
        name: str,
        path: str,
        method: str,
        port: int = 9070,
        data: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Tuple[int, str]:
        """Call the task server

        Args:
            name (str): Name of the server
            path (str): Path to call
            method (str): Method to use
            port (int, optional): Port to use. Defaults to 9070.
            data (Optional[dict], optional): Body data. Defaults to None.
            headers (Optional[dict], optional): Headers. Defaults to None.

        Returns:
            Tuple[int, str]: Status code and response text
        """
        pass

    @abstractmethod
    def refresh(self, owner_id: Optional[str] = None) -> None:
        """Refresh the runtime

        Args:
            owner_id (Optional[str], optional): Owner id to scope it to. Defaults to None.
        """
        pass

    @abstractmethod
    def runtime_local_addr(self, name: str, owner_id: Optional[str] = None) -> str:
        """
        Returns the local address of the agent with respect to the runtime
        """
        pass

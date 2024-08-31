from typing import TypeVar, Optional, Generic, Type, Dict, List
from abc import ABC, abstractmethod
import time
import json

import shortuuid
from pydantic import BaseModel

from taskara.server.models import V1BoundingBox, V1BoundingBoxFlag, V1Flag
from taskara.db.models import FlagRecord
from taskara.db.conn import WithDB

FlagResult = TypeVar("FlagResult", bound="BaseModel")
FlagModel = TypeVar("FlagModel", bound="BaseModel")
FlagType = TypeVar("FlagType", bound="Flag")


class Flag(Generic[FlagResult, FlagModel, FlagType], ABC, WithDB):
    """A flag for human review"""

    def __init__(self) -> None:
        self.id = shortuuid.uuid()
        self.result: Optional[FlagResult] = None
        self.created = time.time()
        self.result = None

    def set_result(self, result: FlagResult):
        self.result = result

    @classmethod
    @abstractmethod
    def result_type(cls) -> Type[FlagResult]:
        pass

    @classmethod
    @abstractmethod
    def v1_type(cls) -> Type[FlagModel]:
        pass

    @abstractmethod
    def to_v1(cls) -> FlagModel:
        pass

    @classmethod
    @abstractmethod
    def from_v1(cls, v1: FlagModel) -> FlagType:
        pass

    def to_v1flag(self) -> V1Flag:
        return V1Flag(
            type=self.__class__.__name__,
            id=self.id,
            flag=self.to_v1().model_dump(),
            result=self.result.model_dump() if self.result else None,
            created=self.created,
        )

    def to_record(self) -> FlagRecord:
        return FlagRecord(
            id=self.id,
            type=self.__class__.__name__,
            flag=self.to_v1().model_dump_json(),
            result=self.result.model_dump_json() if self.result else None,
            created=self.created,
        )

    @classmethod
    def from_record(cls, record: FlagRecord) -> FlagType:
        # Deserialize the flag JSON to a FlagModel (like V1BoundingBoxFlag)
        flag_model = cls.v1_type().model_validate_json(str(record.flag))

        # Use the from_v1 method to create the specific FlagType (like BoundingBoxFlag)
        instance = cls.from_v1(flag_model)

        # Set additional fields from the record
        instance.id = record.id
        instance.result = (  # type: ignore
            cls.result_type().model_validate_json(str(record.result))
            if record.result  # type: ignore
            else None
        )
        instance.created = record.created

        return instance

    def save(self) -> None:
        for db in self.get_db():
            db.add(self.to_record())
            db.commit()

    @classmethod
    def find(cls, **kwargs) -> List[FlagType]:
        for db in cls.get_db():
            records = (
                db.query(FlagRecord)
                .filter_by(type=cls.__name__, **kwargs)
                .order_by(FlagRecord.created.desc())
                .all()
            )
            return [cls.from_record(record) for record in records]
        return []

    @classmethod
    def find_v1(cls, **kwargs) -> List[V1Flag]:
        for db in cls.get_db():
            records = (
                db.query(FlagRecord)
                .filter_by(**kwargs)
                .order_by(FlagRecord.created.desc())
                .all()
            )
            return [
                V1Flag(
                    type=str(record.type),
                    id=str(record.id),
                    flag=json.loads(str(record.flag)),
                    result=json.loads(str(record.result)) if record.result else None,  # type: ignore
                    created=record.created,  # type: ignore
                )
                for record in records
            ]
        return []


class BoundingBoxFlag(Flag[V1BoundingBox, V1BoundingBoxFlag, "BoundingBoxFlag"]):
    """Bounding box flag"""

    def __init__(
        self,
        img: str,
        target: str,
        bbox: V1BoundingBox,
        metadata: Optional[Dict[str, str]] = None,
    ):
        super().__init__()
        self.img = img
        self.target = target
        self.bbox = bbox
        self.metadata = metadata

    @classmethod
    def result_type(cls) -> Type[V1BoundingBox]:
        return V1BoundingBox

    @classmethod
    def v1_type(cls) -> Type[V1BoundingBoxFlag]:
        return V1BoundingBoxFlag

    def to_v1(self) -> V1BoundingBoxFlag:
        return V1BoundingBoxFlag(
            img=self.img,
            target=self.target,
            bbox=self.bbox,
        )

    @classmethod
    def from_v1(cls, v1: V1BoundingBoxFlag) -> "BoundingBoxFlag":
        out = cls.__new__(cls)
        out.img = v1.img
        out.target = v1.target
        out.bbox = v1.bbox
        return out

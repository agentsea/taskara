import json
import time
from typing import Any, Dict, List, Optional, Type

import shortuuid
from devicebay import V1Device, V1DeviceType
from pydantic import BaseModel

from taskara.db.conn import WithDB
from taskara.db.models import (
    BenchmarkRecord,
    EvalRecord,
    TaskRecord,
    TaskTemplateRecord,
    benchmark_task_association,
    eval_task_association,
)
from taskara.server.models import V1Benchmark, V1Eval, V1TaskTemplate
from taskara.task import Task


class TaskTemplate(WithDB):
    """A task template"""

    def __init__(
        self,
        description: Optional[str] = None,
        max_steps: int = 30,
        owner_id: Optional[str] = None,
        device: Optional[V1Device] = None,
        device_type: Optional[V1DeviceType] = None,
        expect: Optional[Type[BaseModel]] = None,
        parameters: Dict[str, Any] = {},
        labels: Dict[str, str] = {},
        tags: List[str] = [],
    ) -> None:
        self._id = shortuuid.uuid()
        self._description = description
        self._max_steps = max_steps
        self._owner_id = owner_id
        self._device = device
        self._device_type = device_type
        self._expect_schema = expect.model_json_schema() if expect else None
        self._parameters = parameters
        self._labels = labels
        self._tags = tags
        self._created = time.time()

    @property
    def id(self) -> str:
        return self._id

    @property
    def description(self) -> Optional[str]:
        return self._description

    @property
    def max_steps(self) -> int:
        return self._max_steps

    @property
    def owner_id(self) -> Optional[str]:
        return self._owner_id

    @property
    def device(self) -> Optional[V1Device]:
        return self._device

    @property
    def device_type(self) -> Optional[V1DeviceType]:
        return self._device_type

    @property
    def expect_schema(self) -> Optional[Dict[str, Any]]:
        return self._expect_schema

    @property
    def parameters(self) -> Optional[Dict[str, Any]]:
        return self._parameters

    @property
    def labels(self) -> Dict[str, str]:
        return self._labels

    @property
    def tags(self) -> List[str]:
        return self._tags

    @property
    def created(self) -> float:
        return self._created

    def to_task(
        self,
        assigned_to: Optional[str] = None,
        assigned_type: Optional[str] = None,
        remote: Optional[str] = None,
        owner_id: Optional[str] = None,
    ) -> Task:
        task = Task(
            description=self.description,
            max_steps=self.max_steps,
            device=self.device,
            device_type=self.device_type,
            assigned_to=assigned_to,
            assigned_type=assigned_type,
            remote=remote,
            labels=self.labels,
            tags=self.tags,
            owner_id=owner_id if owner_id else self.owner_id,
        )
        task._expect_schema = self.expect_schema
        return task

    @classmethod
    def from_task(cls, task: Task) -> "TaskTemplate":
        tpl = cls(
            description=task.description,
            max_steps=task.max_steps,
            device=task.device,
            device_type=task.device_type,
            parameters=task.parameters if task.parameters else {},
            labels=task.labels,
            tags=task.tags,
            owner_id=task.owner_id,
        )
        tpl._expect_schema = task._expect_schema
        return tpl

    def to_record(self) -> TaskTemplateRecord:

        device = None
        if self._device:
            device = self._device.model_dump_json()

        device_type = None
        if self._device_type:
            device_type = self._device_type.model_dump_json()

        expect = None
        if self._expect_schema:
            expect = json.dumps(self._expect_schema)

        return TaskTemplateRecord(
            id=self._id,
            owner_id=self._owner_id,
            description=self._description,
            max_steps=self._max_steps,
            device=device,
            device_type=device_type,
            expect=expect,
            parameters=json.dumps(self._parameters),
            tags=json.dumps(self.tags),
            labels=json.dumps(self.labels),
            created=self._created,
        )

    @classmethod
    def from_record(cls, record: TaskTemplateRecord) -> "TaskTemplate":

        parameters = json.loads(str(record.parameters))

        device = None
        if record.device:  # type: ignore
            device = V1Device.model_validate_json(str(record.device))

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
        obj._device = device
        obj._device_type = device_type
        obj._expect_schema = expect
        obj._parameters = parameters
        obj._tags = json.loads(str(record.tags))
        obj._labels = json.loads(str(record.labels))
        obj._created = record.created
        return obj

    def to_v1(self) -> V1TaskTemplate:
        return V1TaskTemplate(
            id=self._id,
            description=self._description if self._description else "",
            max_steps=self._max_steps,
            device=self._device,
            device_type=self.device_type,
            expect_schema=self._expect_schema,
            parameters=self._parameters,
            owner_id=self._owner_id,
            tags=self._tags,
            labels=self._labels,
            created=self._created,
        )

    @classmethod
    def from_v1(
        cls, v1: V1TaskTemplate, owner_id: Optional[str] = None
    ) -> "TaskTemplate":
        obj = cls.__new__(cls)

        owner_id = owner_id if owner_id else v1.owner_id
        if not owner_id:
            raise ValueError("Owner id is required in v1 or as parameter")

        obj._id = v1.id if v1.id else shortuuid.uuid()
        obj._owner_id = owner_id
        obj._description = v1.description
        obj._max_steps = v1.max_steps
        obj._device = v1.device
        obj._device_type = v1.device_type
        obj._expect_schema = v1.expect_schema
        obj._parameters = v1.parameters
        obj._owner_id = owner_id
        obj._tags = v1.tags
        obj._labels = v1.labels
        obj._created = v1.created

        return obj

    def save(self) -> None:
        for db in self.get_db():
            db.merge(self.to_record())
            db.commit()


class Benchmark(WithDB):
    """An agent benchmark"""

    def __init__(
        self,
        name: str,
        description: str,
        tasks: List[TaskTemplate],
        owner_id: Optional[str] = None,
        labels: Dict[str, str] = {},
        tags: List[str] = [],
        public: bool = False,
    ):
        self._tasks = tasks
        self._id = shortuuid.uuid()
        self._name = name
        self._description = description
        self._owner_id = owner_id
        self._labels = labels
        self._tags = tags
        self._public = public
        self._created = time.time()

        for task in tasks:
            task.labels["benchmark"] = self.name

    @property
    def name(self) -> str:
        return self._name

    @property
    def tasks(self) -> List[TaskTemplate]:
        return self._tasks

    @property
    def description(self) -> str:
        return self._description

    @property
    def id(self) -> str:
        return self._id

    @property
    def owner_id(self) -> Optional[str]:
        return self._owner_id

    @property
    def labels(self) -> Dict[str, str]:
        return self._labels

    @property
    def tags(self) -> List[str]:
        return self._tags

    @property
    def public(self) -> bool:
        return self._public

    def eval(
        self,
        assigned_to: str | None = None,
        assigned_type: str | None = None,
        remote: str | None = None,
        owner_id: str | None = None,
    ) -> "Eval":
        return Eval(
            benchmark=self,
            assigned_to=assigned_to,
            assigned_type=assigned_type,
            remote=remote,
            owner_id=owner_id,
        )

    def to_record(self) -> BenchmarkRecord:
        record = BenchmarkRecord(
            id=self._id,
            owner_id=self._owner_id,
            name=self._name,
            description=self._description,
            public=self._public,
            tags=json.dumps(self._tags),
            labels=json.dumps(self._labels),
            created=self._created,
        )
        return record

    @classmethod
    def from_record(cls, record: BenchmarkRecord, db_session) -> "Benchmark":
        # Retrieve task templates associated with the benchmark
        task_records = (
            db_session.query(TaskTemplateRecord)
            .join(
                benchmark_task_association,
                TaskTemplateRecord.id == benchmark_task_association.c.task_template_id,
            )
            .filter(benchmark_task_association.c.benchmark_id == record.id)
            .all()
        )
        tasks = [TaskTemplate.from_record(task_record) for task_record in task_records]

        obj = cls.__new__(cls)
        obj._id = record.id
        obj._owner_id = record.owner_id
        obj._name = record.name
        obj._description = record.description
        obj._labels = json.loads(str(record.labels))
        obj._tags = json.loads(str(record.tags))
        obj._created = record.created
        obj._tasks = tasks
        obj._public = record.public
        return obj

    def to_v1(self) -> V1Benchmark:
        return V1Benchmark(
            id=self._id,
            name=self._name,
            description=self._description,
            tasks=[task.to_v1() for task in self._tasks],
            owner_id=self._owner_id,
            tags=self._tags,
            labels=self._labels,
            created=self._created,
            public=self._public,
        )

    @classmethod
    def from_v1(cls, v1: V1Benchmark, owner_id: Optional[str] = None) -> "Benchmark":
        tasks = [
            TaskTemplate.from_v1(task, owner_id=owner_id if owner_id else v1.owner_id)
            for task in v1.tasks
        ]
        for task in tasks:
            task.save()

        obj = cls.__new__(cls)
        owner_id = owner_id if owner_id else v1.owner_id
        if not owner_id:
            raise ValueError("Owner id is required in v1 or as parameter")

        obj._id = v1.id if v1.id else shortuuid.uuid()
        obj._owner_id = owner_id
        obj._name = v1.name
        obj._description = v1.description
        obj._tasks = tasks
        obj._labels = v1.labels
        obj._tags = v1.tags
        obj._created = v1.created
        obj._public = v1.public

        return obj

    @classmethod
    def find(cls, remote: Optional[str] = None, **kwargs) -> List["Benchmark"]:
        for db in cls.get_db():
            records = (
                db.query(BenchmarkRecord)
                .filter_by(**kwargs)
                .order_by(BenchmarkRecord.created.desc())
                .all()
            )
            return [cls.from_record(record, db) for record in records]
        raise ValueError("No session")

    def save(self) -> None:
        for db in self.get_db():
            # Save the benchmark record
            benchmark_record = self.to_record()
            db.merge(benchmark_record)
            db.commit()

            # Save the task records and associations
            for task in self._tasks:
                task_record = task.to_record()
                db.merge(task_record)
                db.commit()

                association = benchmark_task_association.insert().values(
                    benchmark_id=self._id, task_template_id=task.id
                )
                db.execute(association)
                db.commit()

    def delete(self) -> None:
        for db in self.get_db():
            # Delete the benchmark record
            benchmark_record = db.query(BenchmarkRecord).filter_by(id=self._id).first()
            if benchmark_record:
                db.delete(benchmark_record)
                db.commit()

            # Delete the task records and associations
            db.execute(
                benchmark_task_association.delete().where(
                    benchmark_task_association.c.benchmark_id == self._id
                )
            )
            db.commit()

            for task in self._tasks:
                task_record = db.query(TaskTemplateRecord).filter_by(id=task.id).first()
                if task_record:
                    db.delete(task_record)
                    db.commit()


class Eval(WithDB):
    """An agent evaluation on a benchmark"""

    def __init__(
        self,
        benchmark: Benchmark,
        assigned_to: Optional[str] = None,
        assigned_type: Optional[str] = None,
        remote: Optional[str] = None,
        owner_id: Optional[str] = None,
    ) -> None:
        self._id = shortuuid.uuid()
        self._benchmark = benchmark
        self._tasks: List[Task] = []
        self._owner_id = owner_id
        self._assigned_to = assigned_to
        self._assigned_type = assigned_type

        for tpl in self._benchmark.tasks:
            task = tpl.to_task(
                assigned_to=assigned_to,
                assigned_type=assigned_type,
                remote=remote,
                owner_id=owner_id,
            )
            task.labels["benchmark"] = self._benchmark.name
            self._tasks.append(task)

    @property
    def tasks(self) -> List[Task]:
        return self._tasks

    @property
    def benchmark(self) -> Benchmark:
        return self._benchmark

    @property
    def id(self) -> str:
        return self._id

    @property
    def owner_id(self) -> Optional[str]:
        return self._owner_id

    def to_record(self) -> EvalRecord:
        return EvalRecord(
            id=self._id,
            benchmark_id=self._benchmark.id,
            assigned_to=self._assigned_to,
            assigned_type=self._assigned_type,
            owner_id=self._owner_id,
            created=time.time(),
        )

    @classmethod
    def from_record(cls, record: EvalRecord, db_session) -> "Eval":
        benchmark = Benchmark.from_record(
            db_session.query(BenchmarkRecord).filter_by(id=record.benchmark_id).first(),
            db_session,
        )
        # Correctly extract task_ids from the association table
        task_associations = (
            db_session.query(eval_task_association.c.task_id)
            .filter_by(eval_id=record.id)
            .all()
        )
        task_ids = [task_id for (task_id,) in task_associations]
        tasks = [
            Task.from_record(db_session.query(TaskRecord).filter_by(id=task_id).first())
            for task_id in task_ids
        ]

        obj = cls.__new__(cls)
        obj._id = record.id
        obj._benchmark = benchmark
        obj._tasks = tasks
        obj._owner_id = record.owner_id
        obj._assigned_to = record.assigned_to
        obj._assigned_type = record.assigned_type

        return obj

    def to_v1(self) -> V1Eval:
        return V1Eval(
            id=self._id,
            benchmark=self._benchmark.to_v1(),
            tasks=[task.to_v1() for task in self._tasks],
            assigned_to=self._assigned_to,
            assigned_type=self._assigned_type,
            owner_id=self._owner_id,
        )

    @classmethod
    def from_v1(cls, v1: V1Eval, owner_id: Optional[str] = None) -> "Eval":
        benchmark = Benchmark.from_v1(v1.benchmark, owner_id=owner_id)
        tasks = [
            Task.from_v1(task, owner_id=owner_id if owner_id else v1.owner_id)
            for task in v1.tasks
        ]

        obj = cls.__new__(cls)
        obj._id = v1.id if v1.id else shortuuid.uuid()
        obj._benchmark = benchmark
        obj._tasks = tasks
        obj._owner_id = owner_id if owner_id else v1.owner_id
        obj._assigned_to = v1.assigned_to
        obj._assigned_type = v1.assigned_type

        return obj

    @classmethod
    def find(cls, remote: Optional[str] = None, **kwargs) -> List["Eval"]:
        for db in cls.get_db():
            records = (
                db.query(EvalRecord)
                .filter_by(**kwargs)
                .order_by(EvalRecord.created.desc())
                .all()
            )
            return [cls.from_record(record, db) for record in records]
        raise ValueError("No session")

    def save(self) -> None:
        for db in self.get_db():
            # Save the evaluation record
            eval_record = self.to_record()
            db.merge(eval_record)
            db.commit()

            # Save the task records and associations
            for task in self._tasks:
                task_record = task.to_record()
                db.merge(task_record)
                db.commit()

                association = eval_task_association.insert().values(
                    eval_id=self._id, task_id=task.id
                )
                db.execute(association)
                db.commit()

    def delete(self) -> None:
        for db in self.get_db():
            # Delete the evaluation record
            eval_record = db.query(EvalRecord).filter_by(id=self._id).first()
            if eval_record:
                db.delete(eval_record)
                db.commit()

            # Delete the task records and associations
            db.execute(
                eval_task_association.delete().where(
                    eval_task_association.c.eval_id == self._id
                )
            )
            db.commit()

import time

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Table
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

benchmark_task_association = Table(
    "benchmark_task_association",
    Base.metadata,
    Column("benchmark_id", String, ForeignKey("benchmarks.id"), primary_key=True),
    Column(
        "task_template_id", String, ForeignKey("task_templates.id"), primary_key=True
    ),
)

eval_task_association = Table(
    "eval_task_association",
    Base.metadata,
    Column("eval_id", String, ForeignKey("evals.id"), primary_key=True),
    Column("task_id", String, ForeignKey("tasks.id"), primary_key=True),
)


class TaskRecord(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True)
    owner_id = Column(String, nullable=True)
    description = Column(String, nullable=False)
    max_steps = Column(Integer, nullable=False, default=30)
    device = Column(String, nullable=True)
    device_type = Column(String, nullable=True)
    project = Column(String, nullable=True)
    expect = Column(String, nullable=True)
    assigned_to = Column(String, nullable=True)
    assigned_type = Column(String, nullable=True)
    status = Column(String, nullable=False)
    created = Column(Float, nullable=False)
    started = Column(Float, nullable=False, default=0.0)
    completed = Column(Float, nullable=False, default=0.0)
    error = Column(String, nullable=True)
    output = Column(String, nullable=True)
    threads = Column(String, nullable=False)
    prompts = Column(String, nullable=True)
    parameters = Column(String, nullable=True)
    version = Column(String, nullable=True)
    tags = Column(String, nullable=True)
    labels = Column(String, nullable=True)
    episode_id = Column(String, nullable=True)


class TaskTemplateRecord(Base):
    __tablename__ = "task_templates"

    id = Column(String, primary_key=True)
    owner_id = Column(String, nullable=True)
    description = Column(String, nullable=False)
    max_steps = Column(Integer, nullable=False, default=30)
    device = Column(String, nullable=True)
    device_type = Column(String, nullable=True)
    expect = Column(String, nullable=True)
    parameters = Column(String, nullable=True)
    tags = Column(String, nullable=True)
    labels = Column(String, nullable=True)
    created = Column(Float, default=time.time)

    benchmarks = relationship(
        "BenchmarkRecord",
        secondary=benchmark_task_association,
        back_populates="task_templates",
    )


class BenchmarkRecord(Base):
    __tablename__ = "benchmarks"

    id = Column(String, primary_key=True)
    owner_id = Column(String, nullable=True)
    name = Column(String, unique=True, index=True)
    description = Column(String, nullable=False)
    public = Column(Boolean, default=False)
    tags = Column(String, nullable=True)
    labels = Column(String, nullable=True)
    created = Column(Float, default=time.time)

    task_templates = relationship(
        "TaskTemplateRecord",
        secondary=benchmark_task_association,
        back_populates="benchmarks",
    )


class EvalRecord(Base):
    __tablename__ = "evals"

    id = Column(String, primary_key=True)
    owner_id = Column(String, nullable=True)
    benchmark_id = Column(String, ForeignKey("benchmarks.id"))
    assigned_to = Column(String, nullable=True)
    assigned_type = Column(String, nullable=True)
    created = Column(Float, default=time.time)

    benchmark = relationship("BenchmarkRecord")
    tasks = relationship(
        "TaskRecord",
        secondary=eval_task_association,
    )


class TrackerRecord(Base):
    __tablename__ = "trackers"

    id = Column(String, primary_key=True)
    name = Column(String, unique=True, index=True)
    runtime_name = Column(String)
    runtime_config = Column(String)
    status = Column(String)
    port = Column(Integer)
    owner_id = Column(String, nullable=True)
    labels = Column(String, nullable=True)
    created = Column(Float, default=time.time)
    updated = Column(Float, default=time.time)

import time
import shortuuid

from sqlalchemy import Table, Column, ForeignKey, String, Integer, Float, Text, Boolean
from sqlalchemy.orm import relationship, declarative_base

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


# Association table for many-to-many between tasks and tags
task_tag_association = Table(
    "task_tag_association",
    Base.metadata,
    Column("task_id", String, ForeignKey("tasks.id"), primary_key=True),
    Column("tag_id", String, ForeignKey("tags.id"), primary_key=True),
)

# Association table for many-to-many between tasks and labels
task_label_association = Table(
    "task_label_association",
    Base.metadata,
    Column("task_id", String, ForeignKey("tasks.id"), primary_key=True),
    Column("label_id", String, ForeignKey("labels.id"), primary_key=True),
)


class TagRecord(Base):
    __tablename__ = "tags"

    id = Column(String, primary_key=True, default=lambda: shortuuid.uuid())
    tag = Column(String, unique=True, nullable=False)


class LabelRecord(Base):
    __tablename__ = "labels"

    id = Column(String, primary_key=True, default=lambda: shortuuid.uuid())
    key = Column(String, nullable=False)
    value = Column(String, nullable=False)


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
    reviews = Column(Text, nullable=True)
    review_requirements = Column(Text, nullable=True)
    status = Column(String, nullable=False)
    created = Column(Float, nullable=False)
    started = Column(Float, nullable=False, default=0.0)
    completed = Column(Float, nullable=False, default=0.0)
    error = Column(String, nullable=True)
    output = Column(String, nullable=True)
    threads = Column(String, nullable=False)
    prompts = Column(String, nullable=True)
    parent_id = Column(String, nullable=True)
    parameters = Column(String, nullable=True)
    version = Column(String, nullable=True)
    episode_id = Column(String, nullable=True)

    tags = relationship("TagRecord", secondary=task_tag_association, backref="tasks")
    labels = relationship(
        "LabelRecord", secondary=task_label_association, backref="tasks"
    )


class ReviewRequirementRecord(Base):
    __tablename__ = "review_requirements"

    id = Column(String, primary_key=True)
    task_id = Column(String, ForeignKey("tasks.id"), nullable=False)
    number_required = Column(Integer, nullable=False)
    users = Column(Text, nullable=True)
    agents = Column(Text, nullable=True)
    groups = Column(Text, nullable=True)
    types = Column(Text, nullable=True)
    created = Column(Float, default=time.time)
    updated = Column(Float, nullable=True)


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


class FlagRecord(Base):
    __tablename__ = "flags"

    id = Column(String, primary_key=True)
    type = Column(String)
    flag = Column(Text)
    result = Column(Text, nullable=True)
    created = Column(Float, default=time.time)


class PendingReviewersRecord(Base):
    __tablename__ = "pending_reviewers"

    id = Column(String, primary_key=True)
    task_id = Column(String, ForeignKey("tasks.id"))
    user_id = Column(String, nullable=True)
    agent_id = Column(String, nullable=True)
    requirement_id = Column(String, nullable=True)

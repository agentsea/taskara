import time

from sqlalchemy import Column, String, Float, Integer
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class TaskRecord(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True)
    owner_id = Column(String, nullable=True)
    description = Column(String, nullable=False)
    max_steps = Column(Integer, nullable=False, default=30)
    device = Column(String, nullable=True)
    device_type = Column(String, nullable=True)
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


class TaskServerRecord(Base):
    __tablename__ = "task_servers"

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

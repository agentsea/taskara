import time

from sqlalchemy import Boolean, Column, String, Float, Integer, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class TaskRecord(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True)
    owner_id = Column(String, nullable=False)
    description = Column(String, nullable=False)
    max_steps = Column(Integer, nullable=False, default=30)
    assigned_to = Column(String, nullable=True)
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


class PromptRecord(Base):
    __tablename__ = "prompts"

    id = Column(String, primary_key=True)
    namespace = Column(String, default="default")
    thread = Column(String)
    response = Column(Text)
    metadata_ = Column(Text, default=dict)
    approved = Column(Boolean, default=False)
    flagged = Column(Boolean, default=False)
    created = Column(Float, default=time.time)

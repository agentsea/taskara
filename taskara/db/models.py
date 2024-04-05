from sqlalchemy import Column, String, Float, Integer
from sqlalchemy.orm import declarative_base

from ..models import V1UserProfile

Base = declarative_base()


class TaskRecord(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True)
    owner_id = Column(String, nullable=False)
    description = Column(String, nullable=False)
    assigned_to = Column(String, nullable=True)
    status = Column(String, nullable=False)
    created = Column(Float, nullable=False)
    started = Column(Float, nullable=False, default=0.0)
    completed = Column(Float, nullable=False, default=0.0)
    error = Column(String, default="")
    output = Column(String, default="")
    threads = Column(String, nullable=False)
    version = Column(String, nullable=True)


class UserRecord(Base):
    __tablename__ = "users"

    email = Column(String, unique=True, index=True, primary_key=True)
    display_name = Column(String)
    handle = Column(String)
    picture = Column(String)
    created = Column(Integer)
    updated = Column(Integer)

    def to_v1_schema(self) -> V1UserProfile:
        return V1UserProfile(
            email=self.email,
            display_name=self.display_name,
            picture=self.picture,
            created=self.created,
            updated=self.updated,
        )

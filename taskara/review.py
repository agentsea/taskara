from typing import Optional, List
import shortuuid
import time
import json

from taskara.db.conn import WithDB
from taskara.db.models import ReviewRequirementRecord
from taskara.server.models import V1ReviewRequirement


class ReviewRequirement(WithDB):
    """A review requirement for a task"""

    def __init__(
        self,
        task_id: str,
        number_required: int = 2,
        users: Optional[List[str]] = None,
        agents: Optional[List[str]] = None,
        groups: Optional[List[str]] = None,
        types: Optional[List[str]] = None,
        created: Optional[float] = None,
        updated: Optional[float] = None,
    ) -> None:
        self.id = str(shortuuid.uuid())
        self.task_id = task_id
        self.number_required = number_required
        self.users = users or []
        self.agents = agents or []
        self.groups = groups or []
        self.types = types or []
        self.created = created or time.time()
        self.updated = updated

    def to_v1(self) -> V1ReviewRequirement:
        return V1ReviewRequirement(
            id=self.id,
            task_id=self.task_id,
            users=self.users,
            agents=self.agents,
            groups=self.groups,
            types=self.types,
            number_required=self.number_required,
        )

    @classmethod
    def from_v1(cls, v1: V1ReviewRequirement) -> "ReviewRequirement":
        out = cls.__new__(cls)
        out.task_id = v1.task_id
        out.number_required = v1.number_required
        out.users = v1.users
        out.agents = v1.agents
        out.groups = v1.groups
        out.types = v1.types

        return out

    def save(self) -> None:
        """Saves the review requirement to the database."""
        for db in self.get_db():
            record = self.to_record()
            db.merge(record)
            db.commit()

    def delete(self) -> None:
        """Deletes the review requirement from the database."""
        for db in self.get_db():
            record = (
                db.query(ReviewRequirementRecord)
                .filter(ReviewRequirementRecord.id == self.id)
                .first()
            )
            if record:
                db.delete(record)
                db.commit()
            else:
                raise ValueError("Review requirement not found")

    def to_record(self) -> ReviewRequirementRecord:
        """Converts the review requirement to a database record."""
        return ReviewRequirementRecord(
            id=self.id,
            number_required=self.number_required,
            users=json.dumps(self.users),
            agents=json.dumps(self.agents),
            groups=json.dumps(self.groups),
            types=json.dumps(self.types),
            created=self.created,
            updated=self.updated,
        )

    @classmethod
    def from_record(cls, record: ReviewRequirementRecord) -> "ReviewRequirement":
        """Creates a review requirement instance from a database record."""
        review_requirement = cls.__new__(cls)
        review_requirement.id = record.id
        review_requirement.number_required = record.number_required
        review_requirement.users = json.loads(record.users)  # type: ignore
        review_requirement.agents = json.loads(record.agents)  # type: ignore
        review_requirement.groups = json.loads(record.groups)  # type: ignore
        review_requirement.types = json.loads(record.types)  # type: ignore
        review_requirement.created = record.created
        review_requirement.updated = record.updated
        return review_requirement

    @classmethod
    def find(cls, **kwargs) -> List["ReviewRequirement"]:
        """Finds review requirements in the database based on provided filters."""
        for db in cls.get_db():
            records = db.query(ReviewRequirementRecord).filter_by(**kwargs).all()
            return [cls.from_record(record) for record in records]
        raise ValueError("No database session available")

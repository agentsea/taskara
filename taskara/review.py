from typing import Optional, List
import shortuuid
import time
import json

from skillpacks import Review

from taskara.db.conn import WithDB
from taskara.db.models import ReviewRequirementRecord, PendingReviewersRecord
from taskara.server.models import (
    V1ReviewRequirement,
    V1PendingReviewers,
    V1PendingReviews,
)


class PendingReviewers(WithDB):
    """A pending review requirement for a task"""

    def pending_reviewers(
        self, task_id: str, requirement_id: Optional[str] = None
    ) -> V1PendingReviewers:
        """Get the pending reviewers for a task, optionally filtered by requirement_id"""

        for db in self.get_db():
            # Start by filtering by task_id
            query = db.query(PendingReviewersRecord).filter_by(task_id=task_id)

            # If requirement_id is provided, filter by it as well
            if requirement_id:
                query = query.filter_by(requirement_id=requirement_id)

            # Get all matching records
            records = query.all()

            # Extract users and agents
            users = set([str(record.user_id) for record in records if record.user_id])  # type: ignore
            agents = set(
                [str(record.agent_id) for record in records if record.agent_id]  # type: ignore
            )

            # Return the V1PendingReviewers with the filtered data
            return V1PendingReviewers(
                task_id=task_id,
                users=list(users) if users else [],
                agents=list(agents) if agents else [],
            )

        raise SystemError("no session")

    def pending_reviews(
        self, user: Optional[str] = None, agent: Optional[str] = None
    ) -> V1PendingReviews:
        """Get the pending reviews for a user or agent"""

        for db in self.get_db():
            query = db.query(PendingReviewersRecord)

            if user:
                query = query.filter(PendingReviewersRecord.user_id == user)
            if agent:
                query = query.filter(PendingReviewersRecord.agent_id == agent)

            records = query.all()

            tasks = list(set([str(record.task_id) for record in records]))

            return V1PendingReviews(tasks=tasks)

        raise SystemError("no session")

    def ensure_pending_reviewer(
        self,
        task_id: str,
        user: Optional[str] = None,
        agent: Optional[str] = None,
        requirement_id: Optional[str] = None,
    ) -> None:
        """Add a pending reviewer for a task, avoiding duplicates"""

        if not user and not agent:
            raise ValueError("Either user or agent must be provided")

        for db in self.get_db():
            # Check if the record already exists
            query = db.query(PendingReviewersRecord).filter_by(task_id=task_id)
            if user:
                query = query.filter_by(user_id=user)
            if agent:
                query = query.filter_by(agent_id=agent)
            if requirement_id:
                query = query.filter_by(requirement_id=requirement_id)

            existing_record = query.first()

            if existing_record:
                # If the record exists, return early to avoid duplicates
                return

            # Add the new record if it doesn't already exist
            new_record = PendingReviewersRecord(
                id=shortuuid.uuid(),
                task_id=task_id,
                user_id=user,
                agent_id=agent,
                requirement_id=requirement_id,
            )
            db.add(new_record)
            db.commit()

    def remove_pending_reviewer(
        self,
        task_id: str,
        user: Optional[str] = None,
        agent: Optional[str] = None,
        requirement_id: Optional[str] = None,
    ) -> None:
        """Remove a pending reviewer for a task"""

        if not user and not agent:
            raise ValueError("Either user or agent must be provided")

        for db in self.get_db():
            query = db.query(PendingReviewersRecord).filter_by(task_id=task_id)
            if user:
                query = query.filter_by(user_id=user)
            if agent:
                query = query.filter_by(agent_id=agent)
            if requirement_id:
                query = query.filter_by(requirement_id=requirement_id)

            record = query.first()
            if record:
                db.delete(record)
                db.commit()

    def task_is_pending(self, task_id: str) -> bool:
        """Check if a task has pending reviewers"""

        for db in self.get_db():
            record = db.query(PendingReviewersRecord).filter_by(task_id=task_id).first()
            return bool(record)
        raise SystemError("no session")

    def pending_tasks(self, user: Optional[str] = None) -> List[str]:
        """Get the pending tasks for a user or agent"""

        for db in self.get_db():
            query = db.query(PendingReviewersRecord)
            if user:
                query = query.filter_by(user_id=user)
            tasks = [str(record.task_id) for record in query.all()]
            return tasks

        raise SystemError("no session")


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
            task_id=self.task_id,
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
        review_requirement.task_id = record.task_id
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

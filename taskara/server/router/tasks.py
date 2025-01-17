import asyncio
import json
import logging
import re
import time
from typing import Annotated, List, Optional

from skillpacks.review import Resource
import shortuuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from mllm import Prompt, V1Prompt
from skillpacks import ActionEvent, Episode, Review
from skillpacks.reviewable import AnnotationReviewable, V1AnnotationReviewable
from skillpacks.server.models import (
    ReviewerType,
    V1ActionEvent,
    V1ActionEvents,
    V1Episode,
    V1Review,
)
from threadmem import RoleMessage, RoleThread, V1RoleThread, V1RoleThreads

from taskara import Task, TaskStatus
from taskara.auth.transport import get_user_dependency
from taskara.db.redis_connection import get_redis_client, stream_action_recorded
from taskara.img import convert_images_async
from taskara.review import PendingReviewers, ReviewRequirement
from taskara.server.models import (
    V1ActionRecordedMessage,
    V1AddThread,
    V1CreateAnnotationResponse,
    V1CreateAnnotationReview,
    V1CreateReview,
    V1CreateReviewAction,
    V1PendingReviewers,
    V1PendingReviews,
    V1PostMessage,
    V1Prompts,
    V1RemoveThread,
    V1ReviewMany,
    V1SearchTask,
    V1Task,
    V1Tasks,
    V1TaskUpdate,
    V1UserProfile,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/v1/tasks", response_model=V1Task)
async def create_task(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    data: V1Task,
):
    logger.debug(f"creating task with model: {data.model_dump()}")

    episode = None
    if data.episode_id:
        episodes = Episode.find(id=data.episode_id, owner_id=current_user.email)
        if not episodes:
            raise HTTPException(status_code=404, detail="Episode not found")
        episode = episodes[0]

    if not episode:
        print("WARNING: no episode found, creating new episode -- create task")
        episode = Episode()

    if not data.id:
        data.id = shortuuid.uuid()

    review_reqs = []
    for req in data.review_requirements:
        review_reqs.append(
            ReviewRequirement(
                task_id=data.id,
                number_required=req.number_required,
                users=req.users,
                agents=req.agents,
                groups=req.groups,
            )
        )

    status = data.status or "created"
    task_status = TaskStatus(status)
    task = Task(
        id=data.id,
        max_steps=data.max_steps,
        device=data.device,
        device_type=data.device_type,
        owner_id=current_user.email,
        description=data.description,
        status=task_status,
        parameters=data.parameters if data.parameters else {},
        assigned_to=data.assigned_to,
        assigned_type=data.assigned_type,
        review_requirements=review_reqs,
        labels=data.labels if data.labels else {},
        tags=data.tags if data.tags else [],
        episode=episode,
    )
    logger.debug(f"saved task: {task.id}")

    return task.to_v1()


@router.post("/v1/tasks/search", response_model=V1Tasks)
async def search_tasks(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    data: V1SearchTask,  # Accept the task_id in the body now
):
    # print(vars(data))
    data_dict = data.model_dump(exclude_unset=True)
    data_dict.setdefault("owner_id", current_user.email)
    print(data_dict)
    tasks = Task.find(**data_dict, tags=None, labels=None)
    return V1Tasks(tasks=[task.to_v1() for task in tasks])


@router.get("/v1/tasks", response_model=V1Tasks)
async def get_tasks(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    tags: Optional[List[str]] = Query(None),
    labels: Optional[str] = Query(None),
    assigned_to: Optional[str] = Query(None),
    assigned_type: Optional[str] = Query(None),
    device: Optional[str] = Query(None),
    device_type: Optional[str] = Query(None),
    parent_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    task_id: Optional[str] = Query(None),
):
    filter_kwargs = {"owner_id": current_user.email}

    if assigned_to:
        filter_kwargs["assigned_to"] = assigned_to
    if task_id:
        filter_kwargs["id"] = task_id
    if assigned_type:
        filter_kwargs["assigned_type"] = assigned_type
    if parent_id:
        filter_kwargs["parent_id"] = parent_id
    if status:
        filter_kwargs["status"] = status
    if device:
        filter_kwargs["device"] = device
    if device_type:
        filter_kwargs["device_type"] = device_type

    labels_dict = json.loads(labels) if labels else None
    if not any(
        [task_id, assigned_to, assigned_type, device, device_type, parent_id, status]
    ):
        tasks = Task.find_many_lite(
            owner_id=current_user.email, tags=tags, labels=labels_dict
        )
        return V1Tasks(tasks=[task.to_v1() for task in tasks])
    tasks = Task.find(**filter_kwargs, tags=tags, labels=labels_dict)
    return V1Tasks(tasks=[task.to_v1() for task in tasks])


@router.get("/v1/tasks/{task_id}", response_model=V1Task)
async def get_task(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())], task_id: str
):
    logger.debug(f"finding task by id: {task_id}")
    tasks = Task.find(id=task_id, owner_id=current_user.email)
    logger.debug(f"found tasks: {tasks}")
    if not tasks:
        logger.debug(f"did not find task by id: {task_id}")
        raise HTTPException(status_code=404, detail="Task not found")
    logger.debug(f"found task by id: {tasks[0]}")
    return tasks[0].to_v1()


@router.delete("/v1/tasks/{task_id}")
async def delete_task(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())], task_id: str
):
    Task.delete(id=task_id, owner_id=current_user.email)  # type: ignore
    return {"message": "Task deleted successfully"}


@router.put("/v1/tasks/{task_id}", response_model=V1Task)
async def update_task(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    task_id: str,
    data: V1TaskUpdate,
):
    logger.debug(f"updating task with model: {data}")
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = task[0]

    logger.debug(f"found task: {task.__dict__}")
    if data.description:
        task.description = data.description
    if data.status:
        task.status = TaskStatus(data.status)
    if data.assigned_to is not None:
        task.assigned_to = data.assigned_to
    if data.assigned_type is not None:
        task.assigned_type = data.assigned_type
    if data.error:
        task.error = data.error
    if data.output:
        task.output = data.output
    if data.completed:
        task.completed = data.completed
    if data.set_labels:
        for key, value in data.set_labels.items():
            task.labels[key] = value

    logger.debug(f"saving task: {task.__dict__}")
    task.save()

    return task.to_v1()


@router.put("/v1/tasks/{task_id}/review", response_model=V1Task)
async def review_task(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    task_id: str,
    data: V1CreateReview,
):
    logger.debug(f"adding review: {data}")
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = task[0]

    logger.debug(f"found task: {task.__dict__}")
    reviewer_type = data.reviewer_type or ReviewerType.HUMAN.value
    if reviewer_type not in [ReviewerType.HUMAN.value, ReviewerType.AGENT.value]:
        raise HTTPException(
            status_code=400, detail="Invalid reviewer type, can be 'human' or 'agent'"
        )

    if not data.reviewer:
        data.reviewer = current_user.email

    reviewerReview = False
    updatedReviewID = None
    for review in task._reviews:
        if review.reviewer == data.reviewer and review.reviewer_type == reviewer_type:
            updatedReviewID = review.id
            reviewerReview = True
            review.approved = data.approved
            review.reason = data.reason
            review.updated = time.time()

    if not reviewerReview:
        # Create review
        review = V1Review(
            id=shortuuid.uuid(),
            reviewer=data.reviewer,  # type: ignore
            approved=data.approved,
            reviewer_type=reviewer_type,
            resource_type=Resource.TASK.value,
            resource_id=task_id,
            created=time.time(),
            reason=data.reason,
        )
        task._reviews.append(Review.from_v1(review))
        updatedReviewID = review.id

    logger.debug(f"saving review {updatedReviewID} to task")
    task.save()
    task.update_pending_reviews()

    return task.to_v1()


@router.post("/v1/tasks/{task_id}/msg")
async def post_task_msg(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    task_id: str,
    data: V1PostMessage,
):
    logger.debug(f"posting message to task: {data.model_dump()}")
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = task[0]

    task.post_message(data.role, data.msg, data.images, thread=data.thread)  # type: ignore
    logger.debug(f"posted message to task: {task.__dict__}")
    return


@router.get("/v1/pending_reviews", response_model=V1PendingReviews)
async def get_pending_reviews(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    agent_id: Optional[str] = None,
):
    pending = PendingReviewers()

    if agent_id:
        return pending.pending_reviews(agent=agent_id)

    return pending.pending_reviews(user=current_user.email)


@router.get("/v1/tasks/{task_id}/pending_reviewers", response_model=V1PendingReviewers)
async def get_pending_approvals(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())], task_id: str
):
    pending = PendingReviewers()

    # TODO: SECURITY: we need authz here
    return pending.pending_reviewers(task_id=task_id)


@router.post("/v1/tasks/{task_id}/prompts")
async def store_prompt(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    task_id: str,
    data: V1Prompt,
):
    logger.debug(f"posting prompt to task: {data.model_dump()}")
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = task[0]

    id = task.store_prompt(
        thread=RoleThread.from_v1(data.thread),
        response=RoleMessage.from_v1(data.response),
        namespace=data.namespace,
        metadata=data.metadata,
        owner_id=current_user.email,
    )

    logger.debug(f"stored prompt in task: {task.__dict__}")
    return {"id": id}


@router.post("/v1/tasks/{task_id}/prompts/{prompt_id}/approve")
async def approve_prompt(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    task_id: str,
    prompt_id: str,
):
    tasks = Task.find(id=task_id, owner_id=current_user.email)
    if not tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    task = tasks[0]

    if prompt_id == "all":
        prompts = Prompt.find(task_id=task_id, owner_id=current_user.email)
        if not prompts:
            raise HTTPException(status_code=404, detail="Prompt not found")
        for prompt in prompts:
            prompt.approved = True
            prompt.save()
            logger.debug(f"approved all prompts in task: {task.__dict__}")
        return

    prompts = Prompt.find(id=prompt_id, owner_id=current_user.email)
    if not prompts:
        raise HTTPException(status_code=404, detail="Prompt not found")
    prompt = prompts[0]

    prompt.approved = True
    prompt.save()

    logger.debug(f"approved prompt in task: {task.__dict__}")
    return


@router.post("/v1/tasks/{task_id}/prompts/{prompt_id}/fail")
async def fail_prompt(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    task_id: str,
    prompt_id: str,
):
    tasks = Task.find(id=task_id, owner_id=current_user.email)
    if not tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    task = tasks[0]

    prompts = Prompt.find(id=prompt_id, owner_id=current_user.email)
    if not prompts:
        raise HTTPException(status_code=404, detail="Prompt not found")
    prompt = prompts[0]

    prompt.approved = False
    prompt.save()

    logger.debug(f"failed prompt in task: {task.__dict__}")
    return


@router.post("/v1/tasks/{task_id}/actions")
async def record_action(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    task_id: str,
    data: V1ActionEvent,
):
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    redis_client = get_redis_client()
    task = task[0]
    if task.episode:
        actions = task.episode.actions
        if not actions or task.episode.actions[-1].action.name != "end": #TODO add enum for action names
            action = data
            state = action.state
            endState = action.end_state
            # Collect async tasks without using asyncio.to_thread, since convert_images is async
            imageTasks = []
            if state.images:
                imageTasks.append(convert_images_async(state.images))
            if endState and endState.images:
                imageTasks.append(convert_images_async(endState.images))

            if imageTasks:
                results = await asyncio.gather(*imageTasks)
                endStateIdx = 0
                if state.images:
                    state.images = results[0]
                    endStateIdx += 1
                if endState and endState.images:
                    endState.images = results[endStateIdx]

            if data.action.name == "end" and actions and task.episode.actions[-1].action.name == "mouse_move":
                task.episode.delete_action(task.episode.actions[-1].id)

            task.record_action_event(ActionEvent.from_v1(data))
            if redis_client:
                if task.episode:
                    actions_length = len(task.episode.actions)
                    prevAction = (
                        task.episode.actions[actions_length - 2].to_v1()
                        if actions_length > 1
                        else None
                    )
                    event_message = V1ActionRecordedMessage(
                        prevAction=prevAction,
                        action=action,
                        event_number=actions_length,
                        task=task.to_v1(),
                    ).model_dump_json()
                    await redis_client.xadd(
                        stream_action_recorded, {"message": event_message}, "*"
                    )
                else:
                    raise ValueError("No Episode on task!")
            else:
                print("no redis client", flush=True)
    return


@router.get("/v1/tasks/{task_id}/actions", response_model=V1ActionEvents)
async def get_actions(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    task_id: str,
):
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = task[0]

    if not task.episode:
        raise HTTPException(status_code=404, detail="Task episode not found")

    return V1ActionEvents(events=[action.to_v1() for action in task.episode.actions])


@router.post("/v1/tasks/{task_id}/actions/{action_id}/approve")
async def approve_action(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    task_id: str,
    action_id: str,
    review: V1CreateReviewAction,
):
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = task[0]

    if not task.episode:
        raise HTTPException(status_code=404, detail="Task episode not found")

    if not review.reviewer:
        review.reviewer = current_user.email

    reviewer_type = review.reviewer_type or ReviewerType.HUMAN.value
    if reviewer_type not in [ReviewerType.HUMAN.value, ReviewerType.AGENT.value]:
        raise HTTPException(
            status_code=400, detail="Invalid reviewer type, can be 'human' or 'agent'"
        )

    task.episode.approve_one(
        action_id,
        reviewer=review.reviewer,  # type: ignore
        reviewer_type=reviewer_type,
        reason=review.reason,
    )
    task.save()
    task.update_pending_reviews()

    return


@router.post("/v1/tasks/{task_id}/actions/{action_id}/approve_prior")
async def approve_prior_actions(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    task_id: str,
    action_id: str,
    review: V1ReviewMany,
):
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = task[0]

    if not task.episode:
        raise HTTPException(status_code=404, detail="Task episode not found")

    if not review.reviewer:
        review.reviewer = current_user.email

    reviewer_type = review.reviewer_type or ReviewerType.HUMAN.value
    if reviewer_type not in [ReviewerType.HUMAN.value, ReviewerType.AGENT.value]:
        raise HTTPException(
            status_code=400, detail="Invalid reviewer type, can be 'human' or 'agent'"
        )

    if not review.reviewer:
        review.reviewer = current_user.email
        if not review.reviewer:
            raise ValueError("no review user")

    task.episode.approve_prior(
        action_id,
        reviewer=review.reviewer,
        reviewer_type=reviewer_type,  # type: ignore
        approve_hidden=review.approve_hidden,
    )
    task.save()
    task.update_pending_reviews()

    return


@router.post("/v1/tasks/{task_id}/approve_actions")
async def approve_all_actions(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    task_id: str,
    review: V1ReviewMany,
):
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = task[0]

    if not task.episode:
        raise HTTPException(status_code=404, detail="Task episode not found")

    reviewer_type = review.reviewer_type or ReviewerType.HUMAN.value
    if reviewer_type not in [ReviewerType.HUMAN.value, ReviewerType.AGENT.value]:
        raise HTTPException(
            status_code=400, detail="Invalid reviewer type, can be 'human' or 'agent'"
        )

    if not review.reviewer:
        review.reviewer = current_user.email
        if not review.reviewer:
            raise ValueError("no review user")

    task.episode.approve_all(
        reviewer=review.reviewer,
        reviewer_type=reviewer_type,
        approve_hidden=review.approve_hidden,
    )  # type: ignore
    task.save()
    task.update_pending_reviews()

    return


@router.post("/v1/tasks/{task_id}/actions/{action_id}/fail")
async def fail_action(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    task_id: str,
    action_id: str,
    review: V1CreateReviewAction,
):
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = task[0]

    if not task.episode:
        raise HTTPException(status_code=404, detail="Task episode not found")

    if not review.reviewer:
        review.reviewer = current_user.email

    reviewer_type = review.reviewer_type or ReviewerType.HUMAN.value
    if reviewer_type not in [ReviewerType.HUMAN.value, ReviewerType.AGENT.value]:
        raise HTTPException(
            status_code=400, detail="Invalid reviewer type, can be 'human' or 'agent'"
        )

    task.episode.fail_one(
        action_id,
        reviewer=review.reviewer,  # type: ignore
        reviewer_type=reviewer_type,
        reason=review.reason,
        correction=review.correction,
    )
    task.save()
    task.update_pending_reviews()

    return


@router.post(
    "/v1/tasks/{task_id}/actions/{action_id}/annotations",
    response_model=V1CreateAnnotationResponse,
)
async def create_annotation(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    task_id: str,
    action_id: str,
    annotation: V1AnnotationReviewable,
):
    tasks = Task.find(id=task_id, owner_id=current_user.email)
    if not tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    events = ActionEvent.find(id=action_id)
    if not events:
        raise HTTPException(status_code=404, detail="Event not found")
    event = events[0]

    annotation = AnnotationReviewable(
        key=annotation.key,
        value=annotation.value,
        annotator=annotation.annotator,
        annotator_type=annotation.annotator_type,
    )

    event.reviewables.append(annotation)

    event.save()
    return V1CreateAnnotationResponse(id=annotation.id)


@router.post("/v1/annotations/{annotation_id}/review")
async def review_annotation(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    annotation_id: str,
    review: V1CreateAnnotationReview,
):
    found = AnnotationReviewable.find(id=annotation_id)
    if not found:
        raise HTTPException(status_code=404, detail="Reviewable not found")
    reviewable = found[0]

    # Check if the user has already placed a review
    existing_review = None
    for r in reviewable.reviews:
        if r.reviewer == current_user.email:
            existing_review = r
            break

    if existing_review:
        # User has already reviewed; override the existing review
        existing_review.approved = review.approved
        existing_review.reviewer_type = review.reviewer_type
        existing_review.reason = review.reason
        existing_review.correction = review.correction
    else:
        # Add a new review
        reviewable.post_review(
            approved=review.approved,
            reviewer=review.reviewer if review.reviewer else current_user.email,  # type: ignore
            reviewer_type=review.reviewer_type,
            reason=review.reason,
            correction=review.correction,
        )

    reviewable.save()
    return


@router.post("/v1/tasks/{task_id}/fail_actions")
async def fail_all_actions(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    task_id: str,
    review: V1ReviewMany,
):
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = task[0]

    if not task.episode:
        raise HTTPException(status_code=404, detail="Task episode not found")

    if not review.reviewer:
        review.reviewer = current_user.email

    reviewer_type = review.reviewer_type or ReviewerType.HUMAN.value
    if reviewer_type not in [ReviewerType.HUMAN.value, ReviewerType.AGENT.value]:
        raise HTTPException(
            status_code=400, detail="Invalid reviewer type, can be 'human' or 'agent'"
        )

    task.episode.fail_all(
        reviewer=review.reviewer, # type: ignore
        reviewer_type=reviewer_type,
        fail_hidden=review.fail_hidden,
    )
    task.save()
    task.update_pending_reviews()

    return


@router.delete("/v1/tasks/{task_id}/actions")
async def delete_all_actions(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    task_id: str,
):
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = task[0]

    if not task.episode:
        raise HTTPException(status_code=404, detail="Task episode not found")

    task.episode.delete_all_actions()
    task.save()
    task.update_pending_reviews()

    return


@router.put("/v1/tasks/{task_id}/actions/{action_id}/unhide")
@router.put("/v1/tasks/{task_id}/actions/{action_id}/hide")
async def toggle_hide_action(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    task_id: str,
    action_id: str,
    request: Request,
):
    hide_action = bool(re.match(r".*/hide$", request.url.path))
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = task[0]

    if not task.episode:
        raise HTTPException(status_code=404, detail="Task episode not found")

    for action in task.episode.actions:
        if action.id == action_id:
            action.hidden = hide_action
            action.save()

    task.save()

    return


@router.get("/v1/tasks/{task_id}/threads", response_model=V1RoleThreads)
async def get_threads(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    task_id: str,
):
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = task[0]

    out: List[V1RoleThread] = []
    for thread in task.threads:
        out.append(thread.to_v1())
    return V1RoleThreads(threads=out)


@router.get("/v1/tasks/{task_id}/threads/{thread_id}", response_model=V1RoleThread)
async def get_thread(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    task_id: str,
    thread_id: str,
):
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = task[0]

    for thread in task.threads:
        if thread.id == thread_id:
            return thread.to_v1()
    raise HTTPException(status_code=404, detail="Thread not found")


@router.post("/v1/tasks/{task_id}/threads")
async def create_thread(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    task_id: str,
    data: V1AddThread,
):
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = task[0]
    task.create_thread(data.name, data.public, data.metadata)
    return


@router.delete("/v1/tasks/{task_id}/threads")
async def remove_thread(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    task_id: str,
    data: V1RemoveThread,
):
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = task[0]
    task.remove_thread(data.id)
    return


@router.get("/v1/tasks/{task_id}/prompts", response_model=V1Prompts)
async def get_prompts(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    task_id: str,
):
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = task[0]

    out: List[V1Prompt] = []
    for prompt in task._prompts:
        out.append(prompt.to_v1())
    return V1Prompts(prompts=out)


@router.get("/v1/tasks/{task_id}/episode", response_model=V1Episode)
async def get_episode(
    current_user: Annotated[V1UserProfile, Depends(get_user_dependency())],
    task_id: str,
):
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = task[0]

    if not task._episode:
        print("WARNING: task has no episode, creating one -- get_episode")
        task._episode = Episode()

    return task._episode.to_v1()

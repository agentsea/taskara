from typing import Annotated
import time

from fastapi import APIRouter, Depends, HTTPException
from threadmem import RoleMessage, RoleThread
from taskara import Task
from taskara.server.models import (
    PromptModel,
    TaskUpdateModel,
    TaskModel,
    SolveTaskModel,
    TasksModel,
    CreateTaskModel,
    V1UserProfile,
    PostMessageModel,
)

from taskara.server.models import AddThreadModel, RemoveThreadModel
from taskara.auth.transport import get_current_user

router = APIRouter()


@router.post("/v1/tasks", response_model=TaskModel)
async def create_task(
    current_user: Annotated[V1UserProfile, Depends(get_current_user)],
    data: CreateTaskModel,
):
    print("creating task with model: ", data.model_dump())
    task = Task(
        owner_id=current_user.email,
        description=data.task.description,
        status="created",
        created=time.time(),
        started=0.0,
        completed=0.0,
        parameters=data.task.parameters if data.task.parameters else {},
        error="",
        output="",
        assigned_to=data.task.assigned_to,
    )

    return task.to_schema()


@router.get("/v1/tasks", response_model=TasksModel)
async def get_tasks(current_user: Annotated[V1UserProfile, Depends(get_current_user)]):
    tasks = Task.find(owner_id=current_user.email)
    return TasksModel(tasks=[task.to_schema() for task in tasks])


@router.get("/v1/tasks/{task_id}", response_model=TaskModel)
async def get_task(
    current_user: Annotated[V1UserProfile, Depends(get_current_user)], task_id: str
):
    print("\nfinding task by id: ", task_id)
    tasks = Task.find(id=task_id, owner_id=current_user.email)
    print("\nfound tasks: ", tasks)
    if not tasks:
        print("\ndid not find task by id: ", task_id)
        raise HTTPException(status_code=404, detail="Task not found")
    print("\nfound task by id: ", tasks[0])
    return tasks[0].to_schema()


@router.delete("/v1/tasks/{task_id}")
async def delete_task(
    current_user: Annotated[V1UserProfile, Depends(get_current_user)], task_id: str
):
    Task.delete(id=task_id, owner_id=current_user.email)  # type: ignore
    return {"message": "Task deleted successfully"}


@router.put("/v1/tasks/{task_id}", response_model=TaskModel)
async def update_task(
    current_user: Annotated[V1UserProfile, Depends(get_current_user)],
    task_id: str,
    data: TaskUpdateModel,
):
    print("\n updating task with model: ", data)
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = task[0]

    print("\nfound task: ", task.__dict__)
    if data.description:
        task.description = data.description
    if data.status:
        task.status = data.status
    if data.assigned_to:
        task.assigned_to = data.assigned_to
    if data.error:
        task.error = data.error
    if data.output:
        task.output = data.output
    if data.completed:
        task.completed = data.completed
    print("\nsaving task: ", task.__dict__)
    task.save()
    return task.to_schema()


@router.post("/v1/tasks/{task_id}/msg")
async def post_task_msg(
    current_user: Annotated[V1UserProfile, Depends(get_current_user)],
    task_id: str,
    data: PostMessageModel,
):
    print("\nposting message to task: ", data.model_dump())
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = task[0]

    task.post_message(data.role, data.msg, data.images, thread=data.thread)
    print("\nposted message to task: ", task.__dict__)
    return


@router.post("/v1/tasks/{task_id}/prompts")
async def store_prompt_msg(
    current_user: Annotated[V1UserProfile, Depends(get_current_user)],
    task_id: str,
    data: PromptModel,
):
    print("\nposting prompt to task: ", data.model_dump())
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = task[0]

    task.store_prompt(
        thread=RoleThread.from_schema(data.thread),
        response=RoleMessage.from_schema(data.response),
        namespace=data.namespace,
        metadata=data.metadata,
    )

    print("\nstored prompt in task: ", task.__dict__)
    return


@router.post("/v1/tasks/{task_id}/threads")
async def create_thread(
    current_user: Annotated[V1UserProfile, Depends(get_current_user)],
    task_id: str,
    data: AddThreadModel,
):
    # print("\n posting message to task: ", data)
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = task[0]
    task.create_thread(data.name, data.public, data.metadata)
    print("\nadded thread: ", task.__dict__)
    return


@router.delete("/v1/tasks/{task_id}/threads")
async def remove_thread(
    current_user: Annotated[V1UserProfile, Depends(get_current_user)],
    task_id: str,
    data: RemoveThreadModel,
):
    # print("\n posting message to task: ", data)
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = task[0]
    task.remove_thread(data.id)
    return

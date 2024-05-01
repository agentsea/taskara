from typing import Annotated
import time

from fastapi import APIRouter, Depends, HTTPException
from threadmem import RoleMessage, RoleThread
from mllm import Prompt

from taskara import Task
from taskara.server.models import (
    V1Prompt,
    V1TaskUpdate,
    V1Task,
    V1Tasks,
    V1UserProfile,
    V1PostMessage,
    V1AddThread,
    V1RemoveThread,
)
from taskara.auth.transport import get_current_user

router = APIRouter()


@router.post("/v1/tasks", response_model=V1Task)
async def create_task(
    current_user: Annotated[V1UserProfile, Depends(get_current_user)],
    data: V1Task,
):
    print("creating task with model: ", data.model_dump())
    task = Task(
        owner_id=current_user.email,
        description=data.description,
        status="created",
        created=time.time(),
        started=0.0,
        completed=0.0,
        parameters=data.parameters if data.parameters else {},
        error="",
        output="",
        assigned_to=data.assigned_to,
    )

    return task.to_v1()


@router.get("/v1/tasks", response_model=V1Tasks)
async def get_tasks(current_user: Annotated[V1UserProfile, Depends(get_current_user)]):
    tasks = Task.find(owner_id=current_user.email)
    return V1Tasks(tasks=[task.to_v1() for task in tasks])


@router.get("/v1/tasks/{task_id}", response_model=V1Task)
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
    return tasks[0].to_v1()


@router.delete("/v1/tasks/{task_id}")
async def delete_task(
    current_user: Annotated[V1UserProfile, Depends(get_current_user)], task_id: str
):
    Task.delete(id=task_id, owner_id=current_user.email)  # type: ignore
    return {"message": "Task deleted successfully"}


@router.put("/v1/tasks/{task_id}", response_model=V1Task)
async def update_task(
    current_user: Annotated[V1UserProfile, Depends(get_current_user)],
    task_id: str,
    data: V1TaskUpdate,
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
    return task.to_v1()


@router.post("/v1/tasks/{task_id}/msg")
async def post_task_msg(
    current_user: Annotated[V1UserProfile, Depends(get_current_user)],
    task_id: str,
    data: V1PostMessage,
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
async def store_prompt(
    current_user: Annotated[V1UserProfile, Depends(get_current_user)],
    task_id: str,
    data: V1Prompt,
):
    print("\nposting prompt to task: ", data.model_dump())
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = task[0]

    task.store_prompt(
        thread=RoleThread.from_v1(data.thread),
        response=RoleMessage.from_v1(data.response),
        namespace=data.namespace,
        metadata=data.metadata,
    )

    print("\nstored prompt in task: ", task.__dict__)
    return


@router.post("/v1/tasks/{task_id}/prompts/{prompt_id}/approve")
async def approve_prompt(
    current_user: Annotated[V1UserProfile, Depends(get_current_user)],
    task_id: str,
    promt_id: str,
):
    tasks = Task.find(id=task_id, owner_id=current_user.email)
    if not tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    task = tasks[0]

    prompts = Prompt.find(id=promt_id, owner_id=current_user.email)
    if not prompts:
        raise HTTPException(status_code=404, detail="Prompt not found")
    prompt = prompts[0]

    prompt.approved = True
    prompt.save()

    print("\napproved prompt in task: ", task.__dict__)
    return


@router.post("/v1/tasks/{task_id}/threads")
async def create_thread(
    current_user: Annotated[V1UserProfile, Depends(get_current_user)],
    task_id: str,
    data: V1AddThread,
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
    data: V1RemoveThread,
):
    # print("\n posting message to task: ", data)
    task = Task.find(id=task_id, owner_id=current_user.email)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = task[0]
    task.remove_thread(data.id)
    return

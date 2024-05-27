import pytest
from devicebay import V1Device, V1DeviceType
from pydantic import BaseModel

from taskara.benchmark import TaskTemplate
from taskara.server.models import V1TaskTemplate
from taskara.task import Task


def test_task_template_creation():
    task_template = TaskTemplate(
        description="Test Task",
        max_steps=10,
        owner_id="owner@example.com",
        device=V1Device(type="device1"),
        device_type=V1DeviceType(name="device_type1"),
        parameters={"param1": "value1"},
        labels={"label1": "value1"},
        tags=["tag1", "tag2"],
    )

    assert task_template.description == "Test Task"
    assert task_template.max_steps == 10
    assert task_template.owner_id == "owner@example.com"
    assert task_template.device.type == "device1"  # type: ignore
    assert task_template.device_type.name == "device_type1"  # type: ignore
    assert task_template.parameters == {"param1": "value1"}
    assert task_template.labels == {"label1": "value1"}
    assert task_template.tags == ["tag1", "tag2"]


def test_task_template_to_task():
    task_template = TaskTemplate(
        description="Test Task",
        max_steps=10,
        owner_id="owner@example.com",
    )

    task = task_template.to_task()

    assert task.description == "Test Task"
    assert task.max_steps == 10
    assert task.owner_id == "owner@example.com"


def test_task_template_from_task():
    task = Task(
        description="Test Task",
        max_steps=10,
        owner_id="owner@example.com",
    )

    task_template = TaskTemplate.from_task(task)

    assert task_template.description == "Test Task"
    assert task_template.max_steps == 10
    assert task_template.owner_id == "owner@example.com"


def test_task_template_to_v1():
    task_template = TaskTemplate(
        description="Test Task",
        max_steps=10,
        owner_id="owner@example.com",
    )

    v1_task_template = task_template.to_v1()

    assert v1_task_template.description == "Test Task"
    assert v1_task_template.max_steps == 10
    assert v1_task_template.owner_id == "owner@example.com"


def test_task_template_from_v1():
    v1_task_template = V1TaskTemplate(
        id="task1",
        description="Test Task",
        max_steps=10,
        owner_id="owner@example.com",
        created=0.0,
    )

    task_template = TaskTemplate.from_v1(v1_task_template)

    assert task_template.description == "Test Task"
    assert task_template.max_steps == 10
    assert task_template.owner_id == "owner@example.com"

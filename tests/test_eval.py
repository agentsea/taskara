import pytest

from taskara.benchmark import Benchmark, Eval, TaskTemplate
from taskara.server.models import V1Benchmark, V1Eval, V1Task, V1TaskTemplate


def test_eval_creation():
    task_template = TaskTemplate(description="Test Task")
    benchmark = Benchmark(
        name="Test Benchmark",
        description="Test Benchmark Description",
        tasks=[task_template],
        owner_id="owner@example.com",
    )
    eval_instance = Eval(benchmark)

    assert eval_instance.benchmark.name == "Test Benchmark"
    assert len(eval_instance.tasks) == 1
    assert eval_instance.tasks[0].description == "Test Task"
    assert eval_instance.benchmark.owner_id == "owner@example.com"


def test_eval_to_v1():
    task_template = TaskTemplate(description="Test Task")
    benchmark = Benchmark(
        name="Test Benchmark",
        description="Test Benchmark Description",
        tasks=[task_template],
        owner_id="owner@example.com",
    )
    eval_instance = Eval(benchmark)

    v1_eval = eval_instance.to_v1()

    assert v1_eval.benchmark.name == "Test Benchmark"
    assert len(v1_eval.tasks) == 1
    assert v1_eval.tasks[0].description == "Test Task"
    assert v1_eval.owner_id == "owner@example.com"


def test_eval_from_v1():
    v1_task_template = V1TaskTemplate(id="task1", description="Test Task", created=0.0)
    v1_benchmark = V1Benchmark(
        id="benchmark1",
        name="Test Benchmark",
        description="Test Benchmark Description",
        tasks=[v1_task_template],
        owner_id="owner@example.com",
        created=0.0,
    )

    v1_task = V1Task(id="123", description="Search for french ducks")
    v1_eval = V1Eval(
        id="eval1",
        benchmark=v1_benchmark,
        tasks=[v1_task],
        owner_id="owner@example.com",
    )

    eval_instance = Eval.from_v1(v1_eval)

    assert eval_instance.benchmark.name == "Test Benchmark"
    assert len(eval_instance.tasks) == 1
    assert eval_instance.tasks[0].description == "Test Task"
    assert eval_instance.benchmark.owner_id == "owner@example.com"

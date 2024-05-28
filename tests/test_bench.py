import pytest

from taskara.benchmark import Benchmark, TaskTemplate
from taskara.server.models import V1Benchmark, V1TaskTemplate


def test_benchmark_creation():
    task_template = TaskTemplate(description="Test Task")
    benchmark = Benchmark(
        name="Test Benchmark",
        description="Test Benchmark Description",
        tasks=[task_template],
        owner_id="owner@example.com",
    )

    assert benchmark.name == "Test Benchmark"
    assert benchmark.description == "Test Benchmark Description"
    assert len(benchmark.tasks) == 1
    assert benchmark.tasks[0].description == "Test Task"
    assert benchmark.owner_id == "owner@example.com"


def test_benchmark_to_v1():
    task_template = TaskTemplate(description="Test Task")
    benchmark = Benchmark(
        name="Test Benchmark",
        description="Test Benchmark Description",
        tasks=[task_template],
        owner_id="owner@example.com",
    )

    v1_benchmark = benchmark.to_v1()

    assert v1_benchmark.name == "Test Benchmark"
    assert v1_benchmark.description == "Test Benchmark Description"
    assert len(v1_benchmark.tasks) == 1
    assert v1_benchmark.tasks[0].description == "Test Task"
    assert v1_benchmark.owner_id == "owner@example.com"


def test_benchmark_from_v1():
    v1_task_template = V1TaskTemplate(
        id="task1",
        description="Test Task",
        created=0.0,
        owner_id="owner@example.com",
    )
    v1_benchmark = V1Benchmark(
        id="benchmark1",
        name="Test Benchmark",
        description="Test Benchmark Description",
        tasks=[v1_task_template],
        owner_id="owner@example.com",
        created=0.0,
    )

    benchmark = Benchmark.from_v1(v1_benchmark)

    assert benchmark.name == "Test Benchmark"
    assert benchmark.description == "Test Benchmark Description"
    assert len(benchmark.tasks) == 1
    assert benchmark.tasks[0].description == "Test Task"
    assert benchmark.owner_id == "owner@example.com"

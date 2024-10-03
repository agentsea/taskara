import json
import time
import urllib.parse

from mllm import Prompt, RoleMessage, RoleThread
from namesgenerator import get_random_name
from openai import BaseModel
from skillpacks import ActionEvent, V1Action, V1EnvState, EnvState
from skillpacks.server.models import V1Episode, V1ActionEvents
from toolfuse.models import V1ToolRef

from taskara import (
    Benchmark,
    Task,
    TaskTemplate,
    V1Benchmark,
    V1Task,
    V1TaskTemplate,
    ReviewRequirement,
    TaskStatus,
)
from taskara.runtime.process import ProcessConnectConfig, ProcessTrackerRuntime
from taskara.server.models import (
    V1Benchmark,
    V1BenchmarkEval,
    V1Benchmarks,
    V1DeviceType,
    V1Eval,
    V1Evals,
    V1Tasks,
    V1TaskTemplate,
    V1CreateReview,
    V1Prompt,
    V1RoleThread,
    V1PendingReviewers,
    V1PendingReviews,
    V1CreateReview,
)


def test_process_tracker_runtime():
    runtime = ProcessTrackerRuntime()
    assert runtime.name() == "process"
    assert runtime.connect_config_type() == ProcessConnectConfig
    assert runtime.connect_config().model_dump() == {}

    runtime.refresh()

    name = get_random_name("-")
    assert name

    print("running task server ", name)
    server = runtime.run(name, auth_enabled=False)
    print("task server ", server.__dict__)

    try:
        # Create a task
        task_data = {
            "description": "Search for french ducks",
            "assigned_to": "tom@myspace.com",
            "labels": {"test": "true"},
            "review_requirements": [
                {
                    "number_required": 2,
                    "users": ["anonymous@agentsea.ai"],
                    "agents": ["agent1", "agent2"],
                },
                {
                    "number_required": 1,
                    "users": ["tom@myspace.com", "anonymous@agentsea.ai"],
                    "agents": ["agent3"],
                },
            ],
        }
        status, text = server.call(path="/v1/tasks", method="POST", data=task_data)
        print("status: ", status)
        print("task created: ", text)
        assert status == 200

        task = V1Task.model_validate(json.loads(text))
        assert task.description == "Search for french ducks"
        assert task.owner_id == "tom@myspace.com"
        task_id = task.id
        time.sleep(1)

        # Fetch the task with query parameters and labels passed as a JSON string
        labels_query = json.dumps({"test": "true"})  # Encode labels as JSON string
        encoded_labels = urllib.parse.quote(labels_query)

        status, text = server.call(
            path=f"/v1/tasks?labels={encoded_labels}", method="GET"
        )
        print("status: ", status)
        print("tasks fetched: ", text)
        assert status == 200

        tasks = V1Tasks.model_validate(json.loads(text))
        assert any(t.id == task_id for t in tasks.tasks)

        # Get a specific task
        status, text = server.call(path=f"/v1/tasks/{task_id}", method="GET")
        print("status: ", status)
        print("task fetched: ", text)
        assert status == 200
        task = V1Task.model_validate(json.loads(text))
        assert task.id == task_id

        # Check the review requirements
        status, text = server.call(
            path=f"/v1/tasks/{task_id}/pending_reviewers", method="GET"
        )
        assert status == 200
        pending_reviewers = V1PendingReviewers.model_validate_json(text)
        assert pending_reviewers.users is not None
        assert len(pending_reviewers.users) == 5

        status, text = server.call(path="/v1/pending_reviews", method="GET")
        assert status == 200
        pending_reviews = V1PendingReviews.model_validate_json(text)
        assert len(pending_reviews.tasks) == 1

        # Approve the task
        data = V1CreateReview(approved=True, reason="Approved")
        status, text = server.call(
            path=f"/v1/tasks/{task_id}/review", method="PUT", data=data.model_dump()
        )

        data = V1CreateReview(approved=True, reason="Approved", reviewer="agent1")
        status, text = server.call(
            path=f"/v1/tasks/{task_id}/review", method="PUT", data=data.model_dump()
        )

        status, text = server.call(
            path=f"/v1/tasks/{task_id}/pending_reviewers", method="GET"
        )
        assert status == 200
        pending_reviewers = V1PendingReviewers.model_validate_json(text)
        assert pending_reviewers.users is not None
        assert len(pending_reviewers.users) == 3

        status, text = server.call(path="/v1/pending_reviews", method="GET")
        assert status == 200
        pending_reviews = V1PendingReviews.model_validate_json(text)
        assert len(pending_reviews.tasks) == 0

        # Update the task
        update_data = {
            "description": "Search for german ducks",
            "status": "in progress",
            "set_labels": {"test_set": "true"},
        }
        status, text = server.call(
            path=f"/v1/tasks/{task_id}", method="PUT", data=update_data
        )
        print("status: ", status)
        print("task updated: ", text)
        assert status == 200
        task = V1Task.model_validate(json.loads(text))
        assert task.description == "Search for german ducks"
        assert task.status == "in progress"

        # Post a message to the task
        message_data = {
            "role": "user",
            "msg": "This is a test message.",
            "images": [],
            "thread": None,
        }
        status, _ = server.call(
            path=f"/v1/tasks/{task_id}/msg", method="POST", data=message_data
        )
        print("status: ", status)
        assert status == 200

        # Create a thread
        thread_data = {"name": "test-thread", "public": True, "metadata": {}}
        status, _ = server.call(
            path=f"/v1/tasks/{task_id}/threads", method="POST", data=thread_data
        )
        print("create thread status: ", status)
        assert status == 200

        # Remove a thread
        remove_thread_data = {"id": "test-thread"}
        status, _ = server.call(
            path=f"/v1/tasks/{task_id}/threads",
            method="DELETE",
            data=remove_thread_data,
        )
        print("remove thread status: ", status)
        assert status == 200

        # Store a prompt in the task
        prompt = Prompt(
            thread=RoleThread(
                name="test-thread",
                public=True,
            ),
            response=RoleMessage(
                id="123",
                role="assistant",
                text="This is a test response",
                images=[],
            ),
        )
        print("sending prompt id: ", prompt.id)
        status, resp = server.call(
            path=f"/v1/tasks/{task_id}/prompts",
            method="POST",
            data=prompt.to_v1().model_dump(),
        )
        print("store prompt status: ", status)
        assert status == 200

        status, resp_text = server.call(
            path=f"/v1/tasks/{task_id}",
            method="GET",
        )
        print("get task status: ", status)
        assert status == 200
        task = V1Task.model_validate(json.loads(resp_text))
        print("task: ", task)

        print("store prompt response: ", resp)

        # Approve a prompt
        prompt_id = json.loads(resp)["id"]

        print("prompt id: ", prompt_id)
        status, _ = server.call(
            path=f"/v1/tasks/{task_id}/prompts/{prompt_id}/approve", method="POST"
        )
        print("approve prompt status: ", status)
        assert status == 200

        # Write a review
        review = V1CreateReview(approved=True, reason="test")
        status, _ = server.call(
            path=f"/v1/tasks/{task_id}/review",
            method="PUT",
            data=review.model_dump(),
        )
        print("store action status: ", status)
        assert status == 200

        # Store an action event
        action_event = ActionEvent(
            state=EnvState(images=["https://test.img"]),
            action=V1Action(name="test", parameters={}),
            tool=V1ToolRef(module="test", type="test"),
            prompt=prompt,
        )

        status, _ = server.call(
            path=f"/v1/tasks/{task_id}/actions",
            method="POST",
            data=action_event.to_v1().model_dump(),
        )
        print("store action status: ", status)
        assert status == 200

        status, resp_text = server.call(
            path=f"/v1/tasks/{task_id}/actions",
            method="GET",
        )
        print("get task status: ", status)
        assert status == 200
        events = V1ActionEvents.model_validate(json.loads(resp_text))
        print("events: ", events)
        assert len(events.events) > 0

        print("getting remote task")
        found_task = Task.get(id=task_id, remote=f"http://localhost:{server.port}")

        # Delete the task
        status, _ = server.call(path=f"/v1/tasks/{task_id}", method="DELETE")
        print("delete task status: ", status)
        assert status == 200

        print("creating a new task")

        class Expected(BaseModel):
            foo: str
            bar: int

        new_task = Task(
            description="a good test",
            remote=f"http://localhost:{server.port}",
            expect=Expected,
            review_requirements=[
                ReviewRequirement(number_required=1, users=["tom@myspace.com"])
            ],
        )
        print("created a new task: ", new_task.id)

        action_event = ActionEvent(
            state=EnvState(images=["https://test.img"]),
            action=V1Action(name="test", parameters={}),
            tool=V1ToolRef(module="test", type="test"),
            prompt=prompt,
        )
        new_task.record_action_event(action_event)

        status, resp_text = server.call(
            path=f"/v1/tasks/{new_task.id}/actions",
            method="GET",
        )
        print("get task status: ", status)
        assert status == 200
        events = V1ActionEvents.model_validate(json.loads(resp_text))
        print("events: ", events)
        assert len(events.events) > 0

        # Check the review requirements
        status, text = server.call(
            path=f"/v1/tasks/{new_task.id}/pending_reviewers", method="GET"
        )
        assert status == 200
        pending_reviewers = V1PendingReviewers.model_validate_json(text)
        assert pending_reviewers.users is not None
        assert len(pending_reviewers.users) == 1

        status, text = server.call(path="/v1/pending_reviews", method="GET")
        assert status == 200
        pending_reviews = V1PendingReviews.model_validate_json(text)
        assert len(pending_reviews.tasks) == 1

        # Check that we can update the task
        new_task.refresh()
        new_task.status = TaskStatus.CANCELED
        new_task.save()

        status, resp_text = server.call(
            path=f"/v1/tasks/{new_task.id}/actions",
            method="GET",
        )
        print("get task status: ", status)
        assert status == 200
        events = V1ActionEvents.model_validate(json.loads(resp_text))
        print("events: ", events)
        assert len(events.events) > 0

        # Benchmarks
        tpl0 = TaskTemplate(
            description="A good test 0",
            device_type=V1DeviceType(name="desktop"),
            owner_id="tom@myspace.com",
        )
        tpl1 = TaskTemplate(
            description="A good test 1",
            device_type=V1DeviceType(name="mobile"),
            owner_id="tom@myspace.com",
        )
        bench = Benchmark(
            name="test-bench",
            description="A good benchmark",
            tasks=[tpl0, tpl1],
            owner_id="tom@myspace.com",
        )
        status, _ = server.call(
            path="/v1/benchmarks", method="POST", data=bench.to_v1().model_dump()
        )
        assert status == 200

        status, text = server.call(
            path="/v1/benchmarks",
            method="GET",
        )
        benchmarks = V1Benchmarks.model_validate_json(text)
        assert benchmarks.benchmarks[0].description == "A good benchmark"

        status, text = server.call(
            path=f"/v1/benchmarks/{benchmarks.benchmarks[0].id}/eval",
            method="POST",
            data=V1BenchmarkEval(
                assigned_to="test_agent", assigned_type="pizza"
            ).model_dump(),
        )
        assert status == 200

        v1eval = V1Eval.model_validate_json(text)
        assert v1eval.owner_id == "tom@myspace.com"
        assert v1eval.assigned_to == "test_agent"
        assert v1eval.assigned_type == "pizza"

        status, text = server.call(
            path="/v1/evals",
            method="GET",
        )
        evals = V1Evals.model_validate_json(text)
        assert evals.evals[0].owner_id == "tom@myspace.com"

    except:
        print(server.logs())
        raise

    finally:
        # Ensure the server is deleted
        try:
            server.delete()
        except:
            pass

from namesgenerator import get_random_name
import json

from threadmem import V1RoleThread

from taskara.runtime.process import ProcessTaskServerRuntime, ProcessConnectConfig
from taskara import (
    Task,
    V1Task,
)
from taskara.server.models import (
    V1TaskUpdate,
    V1PostMessage,
    V1AddThread,
    V1RemoveThread,
    V1Tasks,
)
from mllm import V1Prompt, RoleMessage, RoleThread, V1RoleMessage, Prompt
from skillpacks import V1ActionEvent, ActionEvent, V1Action
from toolfuse.models import V1ToolRef


def test_process_task_server_runtime():
    runtime = ProcessTaskServerRuntime()
    assert runtime.name() == "process"
    assert runtime.connect_config_type() == ProcessConnectConfig
    assert runtime.connect_config().model_dump() == {}

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
        }
        status, text = server.call(path="/v1/tasks", method="POST", data=task_data)
        print("status: ", status)
        print("task created: ", text)
        assert status == 200
        task = V1Task.model_validate(json.loads(text))
        assert task.description == "Search for french ducks"
        assert task.owner_id == "tom@myspace.com"
        task_id = task.id

        # Get tasks
        status, text = server.call(path="/v1/tasks", method="GET")
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

        # Update the task
        update_data = {
            "description": "Search for german ducks",
            "status": "in_progress",
        }
        status, text = server.call(
            path=f"/v1/tasks/{task_id}", method="PUT", data=update_data
        )
        print("status: ", status)
        print("task updated: ", text)
        assert status == 200
        task = V1Task.model_validate(json.loads(text))
        assert task.description == "Search for german ducks"
        assert task.status == "in_progress"

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
        prompt = V1Prompt(
            thread=V1RoleThread(
                name="test-thread",
                public=True,
                id="123",
                messages=[],
                created=0.0,
                updated=0.0,
            ),
            response=V1RoleMessage(
                id="123",
                role="assistant",
                text="This is a test response",
                images=[],
                created=0.0,
            ),
        )
        status, resp = server.call(
            path=f"/v1/tasks/{task_id}/prompts", method="POST", data=prompt.model_dump()
        )
        print("store prompt status: ", status)
        assert status == 200

        print("store prompt response: ", resp)

        # Approve a prompt
        prompt_id = json.loads(resp)["id"]

        print("prompt id: ", prompt_id)
        status, _ = server.call(
            path=f"/v1/tasks/{task_id}/prompts/{prompt_id}/approve", method="POST"
        )
        print("approve prompt status: ", status)
        assert status == 200

        # Store an action event
        action_event = ActionEvent(
            prompt=Prompt.from_v1(prompt),
            action=V1Action(name="test", parameters={}),
            tool=V1ToolRef(module="test", name="test"),
        )

        status, _ = server.call(
            path=f"/v1/tasks/{task_id}/actions",
            method="POST",
            data=action_event.to_v1().model_dump(),
        )
        print("store action status: ", status)
        assert status == 200

        # Delete the task
        status, _ = server.call(path=f"/v1/tasks/{task_id}", method="DELETE")
        print("delete task status: ", status)
        assert status == 200

    finally:
        # Ensure the server is deleted
        try:
            server.delete()
        except:
            pass

from devicebay import V1Device
from pydantic import BaseModel
from threadmem import RoleThread

from taskara import Task


class TestConnectConfig(BaseModel):
    a: str
    b: int


# Test the thread creation functionality within the Task class
def test_create_thread():
    class Expected(BaseModel):
        foo: str
        bar: int

    task = Task(
        description="Test Task",
        owner_id="owner123",
        id="task123",
        expect=Expected,
        device=V1Device(type="desktop", config=TestConnectConfig(a="a", b=1)),
    )
    assert len(task.threads) == 1

    # Directly call the method that doesn't involve remote calls
    task.create_thread(name="New Local Thread", public=True)

    # Verify a new thread is added
    assert len(task.threads) == 2
    # Verify the properties of the newly created thread
    new_thread = task.threads[-1]
    assert new_thread.name == "New Local Thread"
    assert new_thread.public is True

    task.refresh()

    found = Task.find(id=task.id)
    assert len(found) == 1
    print("\nfound: ", found[0].__dict__)
    assert found[0].device.config["a"] == "a"  # type: ignore
    assert found[0].device.config["b"] == 1  # type: ignore


# Test posting a message to a thread within the Task class
def test_post_message():
    class Expected(BaseModel):
        foo: str
        bar: int

    task = Task(
        description="Test Task 2", owner_id="owner1234", id="task1234", expect=Expected
    )

    # Directly call the method that doesn't involve remote calls
    task.create_thread(name="Prompt", public=True)
    messages = task.messages(thread="Prompt")
    print("initial messages: ", messages)
    assert len(messages) == 0

    # Act: Post a message to the thread
    task.post_message(role="user", msg="Test Message", thread="Prompt")
    messages = task.messages(thread="Prompt")
    assert len(messages) == 1
    message = messages[0]
    assert message.text == "Test Message"
    assert message.role == "user"

    threads = RoleThread.find(name="Prompt")
    assert len(threads) == 1
    thread = threads[0]

    messages = thread.messages()
    assert len(messages) == 1
    message = messages[0]
    assert message.text == "Test Message"
    assert message.role == "user"

    task.post_message(role="moderator", msg="Test Message 5")
    messages = task.messages()
    assert len(messages) == 1
    message = messages[0]

    assert message.text == "Test Message 5"
    assert message.role == "moderator"

def test_find_many_lite():
    # Create three tasks
    task1 = Task(description="Task 1", owner_id="owner1", id="task1")
    task2 = Task(description="Task 2", owner_id="owner1", id="task2")
    task3 = Task(description="Task 3", owner_id="owner2", id="task3")

    # Manually save tasks to ensure they're committed to the database
    # Note: The Task class's save method should handle this, so just calling them is enough.
    task1.save()
    task2.save()
    task3.save()

    # Test retrieving tasks by IDs
    found_tasks = Task.find_many_lite(task_ids=["task1", "task2"])
    print(f"found tasks {found_tasks}", flush=True)
    # Verify that only task1 and task2 are returned
    assert len(found_tasks) == 2
    found_ids = [t.id for t in found_tasks]
    assert "task1" in found_ids
    assert "task2" in found_ids
    assert "task3" not in found_ids

    # Test retrieving a subset
    found_task = Task.find_many_lite(task_ids=["task1"])
    assert len(found_task) == 1
    assert found_task[0].id == "task1"

    # Test retrieving no tasks
    found_none = Task.find_many_lite(task_ids=["nonexistent"])
    assert len(found_none) == 0

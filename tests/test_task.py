from pydantic import BaseModel
from threadmem import RoleThread

from taskara import Task


# Test the thread creation functionality within the Task class
def test_create_thread():
    class Expected(BaseModel):
        foo: str
        bar: int

    task = Task(
        description="Test Task", owner_id="owner123", id="task123", expect=Expected
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

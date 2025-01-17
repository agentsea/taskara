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

def test_find_many_lite_with_reviews_and_reqs():
    """
    Verifies that find_many_lite correctly returns tasks along with:
      - Their parameters
      - Their associated Reviews
      - Their associated ReviewRequirements
    in a single batched lookup.
    """

    # -----------------------------
    # 1) Create sample tasks
    # -----------------------------
    task4 = Task(description="Task 4", owner_id="owner4", id="task4")
    task5 = Task(description="Task 5", owner_id="owner4", id="task5")
    task6 = Task(description="Task 6", owner_id="owner5", id="task6")

    # Give each task some parameters
    task4.parameters = {"foo": "bar4", "alpha": 123}
    task5.parameters = {"foo": "bar5", "beta": 999}
    task6.parameters = {"foo": "bar6", "gamma": 42}

    # -----------------------------
    # 2) Create Reviews for tasks
    # -----------------------------
    from skillpacks.review import Review, Resource

    review_a = Review(
        reviewer="alice",
        approved=True,
        resource_type=Resource.TASK.value,
        resource_id="task4",        # Associate with task4
        reason="Review A - All good",
    )
    review_b = Review(
        reviewer="bob",
        approved=False,
        resource_type=Resource.TASK.value,
        resource_id="task4",        # Also task4
        reason="Review B - Some issues",
    )
    review_c = Review(
        reviewer="charlie",
        approved=True,
        resource_type=Resource.TASK.value,
        resource_id="task5",        # For task5
        reason="Review C - LGTM",
    )
    review_d = Review(
        reviewer="david",
        approved=True,
        resource_type=Resource.TASK.value,
        resource_id="task6",        # For task6
        reason="Review D - Quick check",
    )

    # Save Reviews to DB so they have real IDs
    review_a.save()
    review_b.save()
    review_c.save()
    review_d.save()

    # Link them to the tasks
    task4.reviews = [review_a, review_b]
    task5.reviews = [review_c]
    task6.reviews = [review_d]

    # -----------------------------
    # 3) Create ReviewRequirements
    # -----------------------------
    from taskara.review import ReviewRequirement

    req_a = ReviewRequirement(
        task_id="task4",
        number_required=1,
        users=["alice", "bob"],
    )
    req_b = ReviewRequirement(
        task_id="task5",
        number_required=2,
        users=["charlie", "someone_else"],
    )
    req_c = ReviewRequirement(
        task_id="task6",
        number_required=1,
        agents=["agent_1"],
    )

    req_a.save()
    req_b.save()
    req_c.save()

    # Link them
    task4.review_requirements = [req_a]
    task5.review_requirements = [req_b]
    task6.review_requirements = [req_c]

    # -----------------------------
    # 4) Save all tasks to DB
    # -----------------------------
    task4.save()
    task5.save()
    task6.save()

    # -----------------------------
    # 5) Exercise find_many_lite
    # -----------------------------
    found = Task.find_many_lite(task_ids=["task4", "task5", "task6"])
    assert len(found) == 3, "Should return all three tasks"

    # Turn the list into a dict for easy lookup by ID
    found_dict = {t.id: t for t in found}

    # -----------------------------
    # 6) Verify Task 4 data
    # -----------------------------
    t4 = found_dict["task4"]
    assert t4.parameters["foo"] == "bar4" if t4.parameters else None
    assert t4.parameters["alpha"] == 123 if t4.parameters else None
    assert len(t4.reviews) == 2, "Task 4 should have 2 reviews"
    reviewers_t4 = {r.reviewer for r in t4.reviews}
    assert reviewers_t4 == {"alice", "bob"}
    assert len(t4.review_requirements) == 1, "Task 4 should have 1 review requirement"
    assert t4.review_requirements[0].users == ["alice", "bob"]

    # -----------------------------
    # 7) Verify Task 5 data
    # -----------------------------
    t5 = found_dict["task5"]
    assert t5.parameters["foo"] == "bar5" if t5.parameters else None
    assert t5.parameters["beta"] == 999 if t5.parameters else None
    assert len(t5.reviews) == 1, "Task 5 should have 1 review"
    assert t5.reviews[0].reviewer == "charlie"
    assert len(t5.review_requirements) == 1, "Task 5 should have 1 review requirement"
    req5 = t5.review_requirements[0]
    assert req5.number_required == 2
    assert req5.users == ["charlie", "someone_else"]

    # -----------------------------
    # 8) Verify Task 6 data
    # -----------------------------
    t6 = found_dict["task6"]
    assert t6.parameters["foo"] == "bar6" if t6.parameters else None
    assert t6.parameters["gamma"] == 42 if t6.parameters else None
    assert len(t6.reviews) == 1, "Task 6 should have 1 review"
    assert t6.reviews[0].reviewer == "david"
    assert len(t6.review_requirements) == 1, "Task 6 should have 1 review requirement"
    req6 = t6.review_requirements[0]
    assert req6.agents == ["agent_1"]
    assert req6.number_required == 1

    print("test_find_many_lite_with_reviews_and_reqs passed!")
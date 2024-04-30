# Taskara

Task management for AI agents

## Installation

```sh
pip install taskara
```

## Usage

Create a task

```python
from taskara import Task

task = Task(
    description="Search for the most common varieties of french ducks",
    owner_id="delores@agentsea.ai"
)
```

Assign the task to an agent

```python
task.assigned_to = "roko@agentsea.ai"
```

Post a message to the task thread

```python
task.post_message("assistant", "Getting started working on this")
task.status = "in progress"
```

Create a custom thread for the task

```python
task.create_thread("debug")
task.post_message("assistant", "I'll post debug messages to this thread", thread="debug")
task.post_message("assistant", 'My current screenshot', images=["b64img"], thread="debug")
```

Store prompts used to accomplish the task

```python
thread = RoleThread()
thread.post(role="system", msg="I am a helpful assistant")

response = RoleMessage(
    role="assistant",
    text="How can I help?"
)
task.store_prompt(thread, response, namespace="actions")
```

Store the result

```python
task.output = "The most common type of french duck is the Rouen"
task.status = "success"
```

Save the task

```python
task.save()
```

## Backends

Thread and prompt storage can be backed by:

- Sqlite
- Postgresql

Sqlite will be used by default. To use postgres simply configure the env vars:

```sh
DB_TYPE=postgres
DB_NAME=taskara
DB_HOST=localhost
DB_USER=postgres
DB_PASS=abc123
```

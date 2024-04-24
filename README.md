# Taskara

Task management for AI agents

## Installation

```sh
pip install taskara
```

## Usage

```python
from taskara import Task

task = Task(
    description="Search for the most common varieties of french ducks",
    owner_id="delores@agentsea.ai"
)

# Assign the task to an agent
task.assigned_to = "roko@agentsea.ai"

# Post a message to the task thread
task.post_message("assistant", "Getting started working on this")
task.status = "in progress"

# Create a custom thread for the task
task.create_thread("debug")
task.post_message("assistant", "I'll post debug messages to this thread", thread="debug")
task.post_message("assistant", 'My current screenshot', images=["b64img"], thread="debug")

# Store prompts used to accomplish the task
thread = RoleThread()
thread.post(role="system", msg="I am a helpful assistant")
response = RoleMessage(
    role="assistant",
    text="How can I help?"
)
task.store_prompt(thread, response)

# Store the result
task.output = "The most common type of french duck is the Rouen"
task.status = "success"

# Save the task
task.save()
```

#### Supported Backends

- Sqlite
- Postgresql

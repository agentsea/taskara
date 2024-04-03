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

task.assigned_to = "roko@agentsea.ai"

task.post_message("assistant", "Getting started working on this")
task.status = "in progress"

task.create_thread("prompts")
task.post_message("assistant", "I'll post prompts to this thread", thread="prompts")
task.post_message("assistant", '{"role": "user", "content": "Hello?"}', thread="prompts")

task.output = "The most common type of french duck is the Rouen"
task.status = "success"

task.save()
```

#### Supported Backends

- Sqlite
- Postgresql

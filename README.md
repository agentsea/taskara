<!-- PROJECT LOGO -->
<br />
<p align="center">
  <!-- <a href="https://github.com/agentsea/skillpacks">
    <img src="https://project-logo.png" alt="Logo" width="80">
  </a> -->

  <h1 align="center">Taskara</h1>

  <p align="center">
    Task management for AI agents
    <br />
    <a href="https://docs.hub.agentsea.ai/taskara/intro"><strong>Explore the docs »</strong></a>
    <br />
    <br />
    <a href="https://youtu.be/exoOUUwFRB8">View Demo</a>
    ·
    <a href="https://github.com/agentsea/taskara/issues">Report Bug</a>
    ·
    <a href="https://github.com/agentsea/taskara/issues">Request Feature</a>
  </p>
  <br>
</p>

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

## Tracker

Taskara comes with a task tracker server which can be run on docker or kubernetes.

Install surfkit to create a tracker

```
pip install surfkit
```

Create a tracker

```
surfkit create tracker
```

List trackers

```
surfkit list trackers
```

Get tracker logs

```
surfkit logs tracker <name>
```

Create a task

```
surfkit create task --description "Search for french ducks"
```

List tasks

```
surfkit list tasks
```

Get a task

```
surfkit get task <id>
```

## Integrations

Taskara is integrated with:

- [Surfkit](https://github.com/agentsea/surfkit) A platform for AI agents
- [MLLM](https://github.com/agentsea/mllm) A prompt management, routing, and schema validation library for multimodal LLMs
- [Skillpacks](https://github.com/agentsea/skillpacks) A library to fine tune AI agents on tasks.
- [Threadmem](https://github.com/agentsea/threadmem) A thread management library for AI agents

## Community

Come join us on [Discord](https://discord.gg/hhaq7XYPS6).

## Backends

Thread and prompt storage can be backed by:

- Sqlite
- Postgresql

Sqlite will be used by default. To use postgres simply configure the env vars:

```sh
DB_TYPE=postgres
DB_NAME=tasks
DB_HOST=localhost
DB_USER=postgres
DB_PASS=abc123
```

Thread image storage by default will utilize the db, to configure bucket storage using GCS:

- Create a bucket with fine grained permissions
- Create a GCP service account JSON with permissions to write to the bucket

```sh
export THREAD_STORAGE_SA_JSON='{
  "type": "service_account",
  ...
}'
export THREAD_STORAGE_BUCKET=my-bucket
```

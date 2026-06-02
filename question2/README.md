# executor

A small framework for running operational tasks with
structured JSON logging, per-task retries with backoff, and per-task
timeouts for tasks that hang. New task types plug in via a registry decorator,
with no changes to the executor.

See [DECISIONS.md](DECISIONS.md) for the rationale behind the retry strategy,
the timeout approach and its tradeoffs.

## How it works

Each task is described by a `TaskConfig` and run by `TaskExecutor`:

- **Retry** — `config.retry` is a `RetryPolicy(max_attempts, backoff, base_delay,
  max_delay)`. Backoff is one of `FIXED`, `EXPONENTIAL`, or `EXPONENTIAL_JITTER`
  (the default). Defaults to `max_attempts=1`, i.e. no retry unless opted in.
- **Timeout** — `config.timeout_seconds` bounds a *single* attempt. A hang is
  recorded as `TIMEOUT` (distinct from `FAILED`) and is itself retryable.
- **Isolation** — tasks run sequentially; a task that exhausts its retries does
  not block the ones after it.

Every attempt is logged: failures at ERROR, timeouts at WARNING, plus a
"retrying in Xs" line and a terminal "exhausted retries" line. `summary()`
reports `total_attempts`, `retried_tasks`, and `retries` alongside per-status
counts.

## Adding a task type

Subclass `BaseTask`, implement `execute()` (return a dict, or raise to fail),
and register it. The executor needs no changes:

```python
@register_task("disk_check")
class DiskCheckTask(BaseTask):
    def execute(self) -> dict:
        return {"free_pct": 42}
```

## Usage

```python
from executor import TaskExecutor, TaskConfig, RetryPolicy

executor = TaskExecutor()
results = executor.run_all([
    TaskConfig(
        task_id="api",
        task_type="http_check",
        target="https://example.com",
        params={"expected_status": 200},
        retry=RetryPolicy(max_attempts=3, base_delay=0.5),
        timeout_seconds=5,
    ),
    TaskConfig(
        task_id="db-port",
        task_type="tcp_check",
        target="db.internal:5432",
        timeout_seconds=2,
    ),
])
print(executor.summary())
```

Run the bundled demo directly:

```bash
python3 executor.py
```

## Install

Requires Python ≥ 3.11

```bash
poetry install --with dev
```

## Running the tests

```bash
poetry run pytest
```

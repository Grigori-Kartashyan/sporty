"""
Task Executor Framework
-----------------------
A framework for running operational tasks with logging and error handling.

YOUR TASK: Extend this framework to support:
1. Configurable retry logic
2. Timeout handling for slow tasks
3. Additional task type(s) of your choosing

You MAY modify existing code if you justify the changes in DECISIONS.md.
You MUST follow the existing patterns unless you justify diverging.
"""

import abc
import logging
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
from typing import Any
from dataclasses import dataclass, field
from enum import Enum


# ============================================================================
# Logging Setup (DO NOT MODIFY)
# ============================================================================

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        if hasattr(record, "task_id"):
            log_entry["task_id"] = record.task_id
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("task_executor")
    logger.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    return logger


# ============================================================================
# Core Data Structures
# ============================================================================

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


class BackoffStrategy(Enum):
    FIXED = "fixed"
    EXPONENTIAL = "exponential"
    EXPONENTIAL_JITTER = "exponential_jitter"


class TaskTimeoutError(Exception):
    ...


@dataclass
class RetryPolicy:
    max_attempts: int = 1
    backoff: BackoffStrategy = BackoffStrategy.EXPONENTIAL_JITTER
    base_delay: float = 0.5
    max_delay: float = 30.0

    def delay_for(self, attempt: int) -> float:
        if self.backoff is BackoffStrategy.FIXED:
            delay = self.base_delay
        else:
            window = self.base_delay * (2 ** (attempt - 1))
            if self.backoff is BackoffStrategy.EXPONENTIAL_JITTER:
                delay = random.uniform(0, window)
            else:
                delay = window
        return min(delay, self.max_delay)


@dataclass
class TaskResult:
    task_id: str
    status: TaskStatus
    started_at: datetime
    completed_at: datetime | None = None
    result_data: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
    attempts: int = 1  # For retry tracking


@dataclass
class TaskConfig:
    """
    Configuration for a single task.
    
    EXTEND THIS: Add fields needed for retry and timeout configuration.
    Document why you chose these fields in DECISIONS.md.
    """
    task_id: str
    task_type: str
    target: str
    params: dict[str, Any] = field(default_factory=dict)
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    timeout_seconds: float | None = None


# ============================================================================
# Task Interface and Registry
# ============================================================================

class BaseTask(abc.ABC):
    """
    Abstract base class for all task types.
    
    Implementations must:
    - Be registered via @register_task decorator
    - Implement execute() method
    - Return result data as dict (or raise exception on failure)
    """
    
    def __init__(self, config: TaskConfig, logger: logging.Logger):
        self.config = config
        self.logger = logging.LoggerAdapter(
            logger, 
            {"task_id": config.task_id}
        )
    
    @abc.abstractmethod
    def execute(self) -> dict[str, Any]:
        """
        Execute the task and return result data.
        Raise an exception if the task fails.
        """
        pass
    
    def validate(self) -> bool:
        """Override to add task-specific validation."""
        return True


_task_registry: dict[str, type[BaseTask]] = {}


def register_task(task_type: str):
    """Decorator to register a task implementation."""
    def decorator(cls: type[BaseTask]) -> type[BaseTask]:
        if task_type in _task_registry:
            raise ValueError(f"Task type '{task_type}' already registered")
        _task_registry[task_type] = cls
        return cls
    return decorator


def get_task_class(task_type: str) -> type[BaseTask]:
    if task_type not in _task_registry:
        raise ValueError(f"Unknown task type: {task_type}")
    return _task_registry[task_type]


# ============================================================================
# Example Task Implementation
# ============================================================================

@register_task("http_check")
class HttpCheckTask(BaseTask):
    """
    Performs an HTTP health check against a target URL.
    
    Expected params:
        - expected_status: int (default 200)
        - method: str (default "GET")
    """
    
    def execute(self) -> dict[str, Any]:
        import urllib.request
        import urllib.error
        
        target = self.config.target
        expected = self.config.params.get("expected_status", 200)
        method = self.config.params.get("method", "GET")
        
        self.logger.info(f"Checking {method} {target}")
        
        request = urllib.request.Request(target, method=method)
        
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                actual_status = response.status
                
        except urllib.error.HTTPError as e:
            actual_status = e.code
        except urllib.error.URLError as e:
            raise RuntimeError(f"Connection failed: {e.reason}")
        
        if actual_status != expected:
            raise RuntimeError(
                f"Status mismatch: expected {expected}, got {actual_status}"
            )
        
        return {
            "url": target,
            "status_code": actual_status,
            "healthy": True
        }


@register_task("tcp_check")
class TcpCheckTask(BaseTask):
    def validate(self) -> bool:
        host, sep, port = self.config.target.rpartition(":")
        return bool(host) and sep == ":" and port.isdigit()

    def execute(self) -> dict[str, Any]:
        import socket

        host, _, port_str = self.config.target.rpartition(":")
        port = int(port_str)
        connect_timeout = self.config.params.get("connect_timeout", 5)

        self.logger.info(f"Connecting to {host}:{port}")

        try:
            with socket.create_connection((host, port), timeout=connect_timeout):
                pass
        except OSError as e:
            raise RuntimeError(f"TCP connect failed: {e}")

        return {"host": host, "port": port, "reachable": True}


# ============================================================================
# Task Executor (EXTEND THIS)
# ============================================================================

class TaskExecutor:
    """
    Executes tasks and collects results.
    
    CURRENT LIMITATIONS (for you to address):
    - No retry logic: tasks fail permanently on first error
    - No timeout handling: slow tasks block indefinitely
    - Single task type: only http_check is implemented
    
    YOUR TASK:
    1. Add configurable retry logic with backoff
    2. Add timeout handling for slow tasks
    3. Implement at least one additional task type
    """
    
    def __init__(self, logger: logging.Logger | None = None):
        self.logger = logger or setup_logging()
        self.results: list[TaskResult] = []

    def _execute_with_timeout(
        self, task: BaseTask, timeout_seconds: float | None
    ) -> dict[str, Any]:
        if timeout_seconds is None:
            return task.execute()

        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(task.execute)
        try:
            return future.result(timeout=timeout_seconds)
        except FutureTimeoutError:
            raise TaskTimeoutError(f"timed out after {timeout_seconds}s")
        finally:
            pool.shutdown(wait=False)

    def run_task(self, config: TaskConfig) -> TaskResult:
        """
        Execute a single task and return its result.
        """
        started_at = datetime.now(timezone.utc)
        
        try:
            task_class = get_task_class(config.task_type)
            task = task_class(config, self.logger)
            
            if not task.validate():
                raise ValueError(f"Task validation failed: {config.task_id}")

        except Exception as e:
            self.logger.error(f"Task failed: {config.task_id} - {e}")
            return TaskResult(
                task_id=config.task_id,
                status=TaskStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                error_message=str(e),
                attempts=0,
            )

        policy = config.retry
        last_status = TaskStatus.FAILED
        last_error: str | None = None
        attempt = 0

        while attempt < policy.max_attempts:
            attempt += 1
            try:
                self.logger.info(
                    f"Starting task: {config.task_id} "
                    f"(attempt {attempt}/{policy.max_attempts})"
                )
                result_data = self._execute_with_timeout(
                    task, config.timeout_seconds
                )
                if attempt > 1:
                    self.logger.info(
                        f"Task succeeded after {attempt} attempts: {config.task_id}"
                    )
                return TaskResult(
                    task_id=config.task_id,
                    status=TaskStatus.SUCCESS,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    result_data=result_data,
                    attempts=attempt,
                )
            except TaskTimeoutError as e:
                last_status = TaskStatus.TIMEOUT
                last_error = str(e)
                self.logger.warning(
                    f"Task timed out: {config.task_id} "
                    f"(attempt {attempt}/{policy.max_attempts}) - {e}"
                )
            except Exception as e:
                last_status = TaskStatus.FAILED
                last_error = str(e)
                self.logger.error(
                    f"Task attempt failed: {config.task_id} "
                    f"(attempt {attempt}/{policy.max_attempts}) - {e}"
                )

            if attempt < policy.max_attempts:
                delay = policy.delay_for(attempt)
                self.logger.info(
                    f"Retrying task: {config.task_id} in {delay:.2f}s "
                    f"(next attempt {attempt + 1}/{policy.max_attempts})"
                )
                time.sleep(delay)

        self.logger.error(
            f"Task exhausted retries: {config.task_id} "
            f"after {attempt} attempt(s) - final status {last_status.value}"
        )
        return TaskResult(
            task_id=config.task_id,
            status=last_status,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            error_message=last_error,
            attempts=attempt,
        )

    def run_all(self, configs: list[TaskConfig]) -> list[TaskResult]:
        """
        Execute multiple tasks and return all results.
        
        TODO: Consider whether tasks should run sequentially or concurrently.
        Document your decision in DECISIONS.md.
        """
        self.results = []
        for config in configs:
            result = self.run_task(config)
            self.results.append(result)
        return self.results

    def summary(self) -> dict[str, Any]:
        """Return aggregate statistics about executed tasks."""
        total = len(self.results)
        by_status: dict[str, int] = {}
        total_attempts = 0
        retried_tasks = 0
        for result in self.results:
            status = result.status.value
            by_status[status] = by_status.get(status, 0) + 1
            total_attempts += result.attempts
            if result.attempts > 1:
                retried_tasks += 1

        return {
            "total": total,
            "by_status": by_status,
            "success_rate": by_status.get("success", 0) / total if total else 0,
            "total_attempts": total_attempts,
            "retried_tasks": retried_tasks,
            "retries": total_attempts - total,
        }


# ============================================================================
# CLI Entry Point (OPTIONAL TO MODIFY)
# ============================================================================

if __name__ == "__main__":
    # Example usage - you may modify this for testing
    executor = TaskExecutor()

    test_configs = [
        TaskConfig(
            task_id="check-google",
            task_type="http_check",
            target="https://www.google.com",
            params={"expected_status": 200}
        ),
        TaskConfig(
            task_id="check-fake",
            task_type="http_check",
            target="https://this-does-not-exist.invalid",
            params={"expected_status": 200},
            retry=RetryPolicy(max_attempts=3, base_delay=0.2),
        ),
        TaskConfig(
            task_id="check-dns-port",
            task_type="tcp_check",
            target="8.8.8.8:53",
            timeout_seconds=5,
        ),
        # Hanging task: each attempt exceeds the 0.5s budget and is recorded
        # as TIMEOUT, distinct from a plain failure.
        TaskConfig(
            task_id="hang",
            task_type="sleep",
            target="-",
            params={"seconds": 5},
            timeout_seconds=0.5,
            retry=RetryPolicy(max_attempts=2, base_delay=0.2),
        ),
    ]

    results = executor.run_all(test_configs)
    print(json.dumps(executor.summary(), indent=2))

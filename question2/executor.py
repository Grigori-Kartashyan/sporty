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
import sys
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
    TIMEOUT = "timeout"  # You will need to implement this


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
    # TODO: Add retry configuration
    # TODO: Add timeout configuration


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
    
    def run_task(self, config: TaskConfig) -> TaskResult:
        """
        Execute a single task and return its result.
        
        TODO: Add retry logic here or in a separate method.
        TODO: Add timeout handling.
        """
        started_at = datetime.now(timezone.utc)
        
        try:
            task_class = get_task_class(config.task_type)
            task = task_class(config, self.logger)
            
            if not task.validate():
                raise ValueError(f"Task validation failed: {config.task_id}")
            
            self.logger.info(f"Starting task: {config.task_id}")
            result_data = task.execute()
            
            return TaskResult(
                task_id=config.task_id,
                status=TaskStatus.SUCCESS,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                result_data=result_data
            )
            
        except Exception as e:
            self.logger.error(f"Task failed: {config.task_id} - {e}")
            return TaskResult(
                task_id=config.task_id,
                status=TaskStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                error_message=str(e)
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
        by_status = {}
        for result in self.results:
            status = result.status.value
            by_status[status] = by_status.get(status, 0) + 1
        
        return {
            "total": total,
            "by_status": by_status,
            "success_rate": by_status.get("success", 0) / total if total else 0
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
            params={"expected_status": 200}
        ),
    ]
    
    results = executor.run_all(test_configs)
    print(json.dumps(executor.summary(), indent=2))

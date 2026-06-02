import logging

import pytest

from executor import (
    BackoffStrategy,
    BaseTask,
    RetryPolicy,
    TaskConfig,
    TaskExecutor,
    TaskStatus,
    register_task,
    time,
)


@register_task("t_flaky")
class FlakyTask(BaseTask):
    def execute(self):
        self._calls = getattr(self, "_calls", 0) + 1
        if self._calls <= self.config.params.get("fail_times", 0):
            raise RuntimeError(f"boom {self._calls}")
        return {"calls": self._calls}


@register_task("t_hang")
class HangTask(BaseTask):
    def execute(self):
        time.sleep(self.config.params.get("seconds", 1.0))
        return {"ok": True}


def _fast_retry(max_attempts: int) -> RetryPolicy:
    return RetryPolicy(
        max_attempts=max_attempts,
        backoff=BackoffStrategy.FIXED,
        base_delay=0,
    )


@pytest.fixture
def executor():
    logger = logging.getLogger("test_task_executor")
    logger.addHandler(logging.NullHandler())
    return TaskExecutor(logger=logger)


class TestBackoff:
    def test_fixed_is_constant(self):
        policy = RetryPolicy(backoff=BackoffStrategy.FIXED, base_delay=2)
        assert policy.delay_for(1) == 2
        assert policy.delay_for(5) == 2

    def test_exponential_doubles(self):
        policy = RetryPolicy(backoff=BackoffStrategy.EXPONENTIAL, base_delay=1)
        assert policy.delay_for(1) == 1
        assert policy.delay_for(2) == 2
        assert policy.delay_for(3) == 4

    def test_exponential_jitter_within_window(self):
        policy = RetryPolicy(
            backoff=BackoffStrategy.EXPONENTIAL_JITTER, base_delay=1
        )
        for attempt in range(1, 6):
            window = 1 * (2 ** (attempt - 1))
            for _ in range(50):
                assert 0 <= policy.delay_for(attempt) <= window

    def test_max_delay_caps_everything(self):
        policy = RetryPolicy(
            backoff=BackoffStrategy.EXPONENTIAL, base_delay=10, max_delay=15
        )
        assert policy.delay_for(1) == 10
        assert policy.delay_for(2) == 15
        assert policy.delay_for(10) == 15


class TestRetry:
    def test_succeeds_first_try_no_retry(self, executor):
        config = TaskConfig(
            task_id="ok", task_type="t_flaky", target="-",
            params={"fail_times": 0}, retry=_fast_retry(3),
        )
        result = executor.run_task(config)
        assert result.status == TaskStatus.SUCCESS
        assert result.attempts == 1

    def test_retries_then_succeeds(self, executor):
        config = TaskConfig(
            task_id="recover", task_type="t_flaky", target="-",
            params={"fail_times": 2}, retry=_fast_retry(5),
        )
        result = executor.run_task(config)
        assert result.status == TaskStatus.SUCCESS
        assert result.attempts == 3
        assert result.result_data == {"calls": 3}

    def test_exhausts_retries_and_fails(self, executor):
        config = TaskConfig(
            task_id="always", task_type="t_flaky", target="-",
            params={"fail_times": 99}, retry=_fast_retry(3),
        )
        result = executor.run_task(config)
        assert result.status == TaskStatus.FAILED
        assert result.attempts == 3
        assert "boom" in result.error_message

    def test_retry_attempts_are_logged(self, executor, caplog):
        config = TaskConfig(
            task_id="logged", task_type="t_flaky", target="-",
            params={"fail_times": 99}, retry=_fast_retry(2),
        )
        with caplog.at_level(logging.INFO, logger="test_task_executor"):
            executor.run_task(config)
        messages = [r.getMessage() for r in caplog.records]
        assert any("attempt 1/2" in m for m in messages)
        assert any("attempt 2/2" in m for m in messages)
        assert any("Retrying task" in m for m in messages)
        assert any("exhausted retries" in m for m in messages)


class TestTimeout:
    def test_hanging_task_times_out(self, executor):
        config = TaskConfig(
            task_id="hang", task_type="t_hang", target="-",
            params={"seconds": 1.0}, timeout_seconds=0.05,
        )
        result = executor.run_task(config)
        assert result.status == TaskStatus.TIMEOUT
        assert result.attempts == 1

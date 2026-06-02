### What retry strategy did you implement and why? What alternatives did you consider?

Exponential backoff with full jitter, configurable via a `RetryPolicy`. The default backoff is
`EXPONENTIAL_JITTER`. `FIXED` and plain `EXPONENTIAL` are also selectable.

- Exponential gives a recovering dependency progressively more breathing room instead of hammering it at a constant rate.
- Full jitter decorrelates retries. If many tasks fail at the same instant, fixed exponential makes them all retry in lockstep, producing a synchronized thundering herd that can re-knock-over the thing that just came back. Spreading each retry uniformly across its window avoids that.

### How did you implement timeout handling? What are the tradeoffs of your approach?

`timeout_seconds` is a per-task wall-clock budget for a single attempt. The executor runs `task.execute()` on a one-shot `ThreadPoolExecutor` worker and waits on `future.result(timeout=...)`. If the future doesn't complete in time, a `TaskTimeoutError` is raised, the executor stops waiting, and calls `pool.shutdown(wait=False)` so it does not block on the stuck worker.

Tradeoffs:
- Python cannot forcibly kill a thread. "Interrupting" here means we stop waiting and abandon the worker, the work itself keeps running in the background until it returns on its own. So the timeout bounds the executor's wait, not the task's resource usage.

### What additional task type did you add and why? How does it demonstrate the framework's extensibility?

`tcp_check` connects to a `host:port` and reports reachability. It's operationally useful for probing services that don't speak HTTP (Postgres, Redis, etc.), which the existing `http_check` can't cover. It's dependency-free (stdlib `socket`).

### Did you keep sequential execution or add concurrency? Why?


**Sequential**, unchanged from the starter. Reasons:
- The required features — retry, backoff, timeout — are per-task and orthogonal
  to concurrency; adding a thread pool over tasks would have muddied the diff
  without serving the brief.
- Operational runs are often small and order can matter (check the DB is up
  before checking the thing that depends on it). Sequential gives deterministic,
  easy-to-reason-about ordering and logs.
- It keeps the blast radius small: one shared timeout mechanism, no contention
  on shared state, trivially testable.

The design doesn't paint us into a corner: `run_task` is self-contained and
returns a `TaskResult`, so `run_all` could later fan out over a pool (or process
pool) with no change to per-task logic. I noted that path rather than building it
speculatively.

### What happens if a task fails all retry attempts? How is this surfaced to the operator?

The task does **not** block the others — failures are isolated; `run_all`
continues to the next config. The exhausted task is surfaced three ways:
1. **A terminal log line** at ERROR: `"Task exhausted retries: <id> after N
   attempt(s) - final status <failed|timeout>"`, plus a per-attempt log for
   every try (ERROR for failures, WARNING for timeouts) so the operator can see
   the full history.
2. **The `TaskResult`**: `status` is `FAILED` or `TIMEOUT` (timeouts stay
   distinguishable to the end), `attempts` records how many tries it took, and
   `error_message` carries the last error.
3. **The summary**: `by_status` counts the failure/timeout, and
   `total_attempts` / `retried_tasks` / `retries` quantify the retry cost.
   `success_rate` drops accordingly.

A config-level problem (unknown task type, failed `validate()`) is treated as a
deterministic error: it fails immediately with `attempts=0` and is **not**
retried, since retrying a malformed config just wastes time.

### What did you skip or simplify? What would break in production?


- **No real interruption of hung work.** As covered in Q2, timeout abandons the
  worker thread rather than killing it. In production a task that wedges on a
  non-interruptible call leaks a thread and can hold the process open. Fix:
  run tasks in subprocesses with hard `terminate()`, or enforce timeouts at the
  I/O layer (socket/HTTP client timeouts) in addition to the wall-clock guard.
- **All exceptions are treated as retryable.** There's no `retry_on` /
  non-retryable classification, so a deterministic 400/auth error is retried as
  if it were a transient blip — wasted attempts and delay. Production wants
  retryable-vs-fatal classification.
- **No retry budget / circuit breaker / global rate limit.** Per-task backoff
  alone can still overwhelm a dependency if many tasks target it at once. Full
  jitter mitigates synchronization but not aggregate volume.
- **Backoff uses unseeded `random`**, so jitter isn't reproducible across runs;
  fine operationally, mildly annoying for debugging. Tests avoid this by using
  `FIXED` backoff with `base_delay=0`.
- **Sequential only** (Q4): a slow task delays everything after it. Fine for
  small operational batches, not for large fleets.
- **Results live in memory** (`self.results`) and the summary is the only
  aggregate — there's no persistence, no metrics emission, and no alerting hook.
- **`max_attempts` is a count, not a deadline**, and there's no overall
  per-task or per-run time cap, so a long backoff chain can run longer than an
  operator might expect.

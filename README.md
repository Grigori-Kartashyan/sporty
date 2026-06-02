# Config Resolver and Executor

Solutions to two exercises. Each lives in its own directory with its
own README and a `DECISIONS.md` explaining the design choices.

## [Question 1 — config_resolver](question1/README.md)

Merges configuration for an environment from multiple sources (a YAML file, a
remote HTTP endpoint, and prefixed environment variables) into a single resolved
config, with precedence rules, secret masking, and per-key override reporting.

[README](question1/README.md) · [DECISIONS](question1/DECISIONS.md)

## [Question 2 — executor](question2/README.md)

A task-runner framework extended with per-task retries (configurable backoff) and
per-task timeouts for tasks that hang.

[README](question2/README.md) · [DECISIONS](question2/DECISIONS.md)

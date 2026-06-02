# config_resolver

Merge configuration for an environment from multiple sources, a YAML file, a
remote HTTP endpoint, and prefixed environment variables into a single
resolved config. Lower-priority sources provide defaults and higher-priority
sources override them. Secrets are masked when printed, and every override is
reported so you can see exactly which source won each key.

## How it works

For a given environment, up to three sources are loaded and merged:

| Kind     | Where it comes from                                  | Default priority |
|----------|------------------------------------------------------|------------------|
| `file`   | a local YAML file                                    | lowest           |
| `remote` | an HTTP endpoint returning JSON or YAML              | middle           |
| `env`    | environment variables with a given prefix            | highest          |

The default precedence (`file` → `remote` → `env`, lowest to highest) follows
12-factor conventions: static file defaults form the baseline, remote runtime
config overrides them, and per-deployment environment variables win over all.
Merging is **deep** — nested maps are merged key-by-key, so a single env var
override does not clobber sibling keys from the file.

### Environment variable mapping

Variables are matched by prefix, then the remaining name is lowercased and split
on `__` into a nested path. With prefix `APP_STAGING_`:

```
APP_STAGING_DATABASE__HOST=db.local   ->   database.host = db.local
APP_STAGING_DATABASE__POOL_SIZE=20    ->   database.pool_size = 20
```

Values are parsed as YAML scalars, so `20` becomes an int and `true` a bool.

### Secret masking

When config is printed to the terminal, keys that look like secrets
(`password`, `secret`, `token`, `api_key`, `credential`, `private_key`,
`access_key`, …) are masked as `********`. Masking is **display-only**: when you
write resolved config to a file with `--output`, the real values are written.

## Install

Requires Python ≥ 3.11. Dependencies are managed with [Poetry](https://python-poetry.org/).

```bash
# install Poetry if you don't have it
curl -sSL https://install.python-poetry.org | python3 -

# install project dependencies (creates a virtualenv)
poetry install

# include dev tools (pytest) as well
poetry install --with dev
```

Run commands inside the environment with `poetry run …`, or open a shell with
`poetry env activate` (Poetry 2.x).

## Configure your sources

Sources are declared in a `sources.yaml` (any path; pass it via `--inputs`).
Each environment may set any combination of `file`, `remote`, and `env_prefix`.
File paths are resolved relative to the `sources.yaml` location.

```yaml
# examples/sources.yaml
environments:
  staging:
    file: staging.yaml
    env_prefix: APP_STAGING_
    remote: http://localhost:8080/staging

  production:
    file: production.yaml
    env_prefix: APP_PROD_
    remote: http://localhost:8080/production
```

```yaml
# examples/staging.yaml
database:
  host: db.stage
  port: 5432
  password: staging_secret_from_file
  pool_size: 5
  pool_timeout_ms: 250
```

## Usage

The CLI has a single command, `apply`, which resolves one environment and either
prints it (`--dry-run`) or writes it to a file (`--output`).

```
config-resolver --inputs <sources.yaml> apply <env> [options]
```

Run it via `main.py`:

```bash
poetry run python main.py --inputs examples/sources.yaml apply staging --dry-run
```

### Options

| Option            | Description                                                                            |
|-------------------|----------------------------------------------------------------------------------------|
| `--dry-run`       | Print the merged config (secrets masked) instead of writing a file.                    |
| `--output PATH`   | Write the merged config (secrets **unmasked**) to `PATH`. Required unless `--dry-run`. |
| `--format {yaml,json}` | Output format (default: `yaml`).                                                       |
| `--allow-partial` | Continue even if a source is unavailable (skip it) instead of failing.                 |
| `--precedence KIND,KIND,...` | Override source precedence, lowest to highest (default: `file,remote,env`).            |

### Examples

**Preview a resolved environment (nothing written):**

```bash
poetry run python main.py --inputs examples/sources.yaml apply staging --dry-run --allow-partial
```

Merged config is printed to stdout (secrets masked) the list of overrides
(which source won each key) is printed to stderr.

**Write resolved config to a file (real secrets included):**

```bash
poetry run python main.py --inputs examples/sources.yaml apply staging \
  --output build/staging.resolved.yaml --allow-partial
```

**Override a value with an environment variable:**

```bash
APP_STAGING_DATABASE__HOST=db.local \
poetry run python main.py --inputs examples/sources.yaml apply staging --dry-run --allow-partial
# database.host resolves to "db.local" (env beats file by default)
```

**Output as JSON:**

```bash
poetry run python main.py --inputs examples/sources.yaml apply staging --dry-run --format json --allow-partial
```

**Change precedence so the file wins over env vars:**

```bash
APP_STAGING_DATABASE__HOST=db.local \
poetry run python main.py --inputs examples/sources.yaml apply staging \
  --dry-run --precedence env,file --allow-partial
# database.host stays "db.stage" — file now outranks env
```

## Trying the remote source locally

The `remote` source fetches JSON/YAML over HTTP. A small mock server is included
for experimentation:

```bash
# terminal 1: start the mock server on http://localhost:8080
poetry run python mock_server.py

# terminal 2: resolve staging (file + remote + env), no --allow-partial needed
poetry run python main.py --inputs examples/sources.yaml apply staging --dry-run
```

Without the server running, use `--allow-partial` so the unreachable remote is
skipped instead of failing.

## Running the tests

```bash
poetry run pytest
```

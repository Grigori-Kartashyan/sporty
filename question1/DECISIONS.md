## Which configuration sources did you support and why? What did you exclude?

Three sources per environment, in precedence order (low to high): a YAML file, an HTTP remote (mocked locally) and environment variables (`APP_<env>_*` with `__` for nesting).
I've choos three sources to cover the distinct categories, a file, a remote API, and process env, rather than three flavors of the same thing. Each exercises a different loading and normalization path 
Excluded: secret managers (Vault, AWS/GCP Secrets Manager) they add auth, SDK and some other complexity without changing the merge/diff logic, which is the core of the task. Also excluded other file formats (ini, toml, .env), they'd be almost duplicate loaders of the YAML path.

## What are your precedence rules and why? What alternatives did you consider?

Lowest to highest: YAML -> HTTP remote -> env vars. Files are the version-controlled baseline, the remote layer is centrally-managed runtime config that should override stale file defaults and env vars sit on top.
Alternative considered: putting the remote source above env vars, if the remote is treated as the single source of truth for runtime state.

## How do you define "conflict"? Give one example that is a conflict and one that is not.
A conflict is when two or more sources independently provide a value for the same key path, and those values differ. Precedence resolves a conflict (picks a winner) but doesn't mean one didn't occur, the whole point of the tool is to surface that a lower-precedence value was silently overridden.

Is a conflict: database.port = 5432 in YAML and database.port = 6543 from env vars. Same path, different values, env wins, YAML is shadowed.
Not a conflict: database.host set only in YAML and database.port set only in env. Different paths, so they merge cleanly with no overridden value.

## How do you handle source failures? Fail entirely or proceed partially? Why?
Partial by default, controlled by a flag. On a recoverable failure (e.g. the HTTP remote is unreachable), that source is dropped and the merge proceeds with the remaining sources (YAML + env), with the omission reported so it's visible rather than silent. The flag lets the user switch to strict/fail-fast mode where any source failure aborts.
I think when there is a network failure, falling back to file + env is usually safer than failing a deploy. A malformed file (parse error) is treated as fatal rather than partial, since it signals a real mistake rather than a transient condition.

## What did you skip or simplify? What would you improve with 10 more hours?
 1. The remote server is currently mocked and without any authentication, in a real world usecase we would need to add authenticated call to a remote.
 2. Compare for different environments (stage vs production)
 With more time I would probably add the compare functionality which will reveal the drifts between staging and production environments.
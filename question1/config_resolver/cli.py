import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from config_resolver.masking import Masker
from config_resolver.merge import merge_sources, ShadowedValue
from .sources import (
    EnvVarSource,
    LoadedConfig,
    Source,
    SourceUnavailable,
    YamlFileSource, HttpRemoteSource,
)

EXIT_OK = 0
EXIT_CONFLICTS = 1
EXIT_USAGE = 2

logger = logging.getLogger(__name__)

def _path_str(path: tuple[str, ...]) -> str:
    return ".".join(path) if path else "(root)"


def _fmt_value(value: Any) -> str:
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, dict | list):
        return json.dumps(value, default=str)
    return str(value)


def _make_masker() -> Masker:
    return Masker()


def render_shadowed_only(shadowed: list[ShadowedValue]) -> str:
    if not shadowed:
        return "no env overrides"
    out: list[str] = ["Env precedence overrides (lower → higher):"]
    for s in shadowed:
        out.append(
            f"  {_path_str(s.path):30}  {s.loser_source} → {s.winner_source} "
            f"(now: {_fmt_value(s.winner_value)})"
        )
    return "\n".join(out)


@dataclass(frozen=True)
class EnvSpec:
    name: str
    file: Path | None
    env_prefix: str | None
    remote: str | None


@dataclass(frozen=True)
class InputsConfig:
    environments: dict[str, EnvSpec]
    base_dir: Path


def load_inputs(path: Path) -> InputsConfig:
    with path.open() as fh:
        try:
            raw = yaml.safe_load(fh) or {}
        except Exception as ex:
            logging.error(f"failed to load inputs from {path}: {ex}")
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: top-level must be a mapping")
    envs_raw = raw.get("environments") or {}
    if not isinstance(envs_raw, dict):
        raise ValueError(f"{path}: 'environments' must be a mapping")

    environments: dict[str, EnvSpec] = {}
    base_dir = path.resolve().parent
    for name, spec in envs_raw.items():
        if not isinstance(spec, dict):
            raise ValueError(f"{path}: environments.{name} must be a mapping")
        file_str = spec.get("file")
        environments[str(name)] = EnvSpec(
            name=str(name),
            file=(base_dir / file_str) if file_str else None,
            env_prefix=spec.get("env_prefix"),
            remote=spec.get("remote"),
        )
    return InputsConfig(environments=environments, base_dir=base_dir)


def load_env_sources(
    env: EnvSpec,
    allow_partial: bool,
    include_env_vars: bool = True,
    env_override: dict[str, str] | None = None,
) -> list[LoadedConfig]:
    sources: list[Source] = []

    if env.file is not None:
        sources.append(YamlFileSource(env.file, name=f"{env.name}:file"))
    if env.remote is not None:
        sources.append(HttpRemoteSource(env.remote, name=f"{env.name}:remote"))
    if include_env_vars and env.env_prefix is not None:
        sources.append(
            EnvVarSource(
                prefix=env.env_prefix,
                env=env_override,
                name=f"{env.name}:env",
            )
        )

    loaded: list[LoadedConfig] = []
    for src in sources:
        try:
            loaded.append(src.load())
        except SourceUnavailable:
            if not allow_partial:
                logger.error("Source unavailable")
                raise
    return loaded


def render_resolved(config: dict[str, Any], masker: Masker, fmt: str, *, mask: bool = True) -> str:
    data = masker.mask_config(config) if mask else config
    if fmt == "json":
        return json.dumps(data, indent=2, default=str)
    import yaml as _yaml

    return _yaml.safe_dump(data, sort_keys=True, default_flow_style=False).rstrip()


def cmd_resolve(args: argparse.Namespace, inputs: InputsConfig) -> int:
    env_name: str = args.env
    if env_name not in inputs.environments:
        logger.exception("Unknown environment")
        return EXIT_USAGE

    allow_partial: bool = args.allow_partial
    sources = load_env_sources(
        inputs.environments[env_name],
        allow_partial
    )
    merged = merge_sources(sources)
    masker = _make_masker()
    print(render_resolved(merged.merged, masker, fmt=args.format))
    print(render_shadowed_only(merged.shadowed), file=sys.stderr)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="config-resolver",
        description="Merge configs from multiple sources; detect cross-env conflicts.",
    )
    parser.add_argument(
        "--inputs",
        type=Path,
        required=True,
        help="Path to sources.yaml declaring per env sources.",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    resolve = sub.add_parser("resolve", help="Merge sources for one env and print the merged config.")
    resolve.add_argument("env", help="Environment name (must exist in sources.yaml).")
    resolve.add_argument(
        "--allow-partial",
        action="store_true",
        help="Proceed when a source is unavailable.",
    )
    resolve.add_argument(
        "--format",
        choices=("json", "yaml"),
        default="yaml",
        help="Output format.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        inputs = load_inputs(args.inputs)
    except (FileNotFoundError, ValueError):
        logger.exception("Failed to load --inputs")
        return EXIT_USAGE

    try:
        return cmd_resolve(args, inputs)
    except SourceUnavailable:
        logger.exception("Source unavailable")
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())

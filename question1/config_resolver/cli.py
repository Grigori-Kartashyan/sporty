import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from config_resolver.merge import merge_sources
from utils import render_resolved, make_masker, render_shadowed_only
from .sources import (
    EnvVarSource,
    LoadedConfig,
    Source,
    SourceUnavailable,
    YamlFileSource, HttpRemoteSource,
)

logger = logging.getLogger(__name__)


EXIT_OK = 0
EXIT_CONFLICTS = 1
EXIT_USAGE = 2

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
    masker = make_masker()
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

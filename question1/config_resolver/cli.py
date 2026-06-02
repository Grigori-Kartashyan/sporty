import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from config_resolver.merge import DEFAULT_PRECEDENCE, merge_sources
from utils import render_resolved, make_masker, render_shadowed_only
from .sources import (
    EnvVarSource,
    LoadedConfig,
    Source,
    SourceKind,
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


def cmd_apply(args: argparse.Namespace, inputs: InputsConfig) -> int:
    env_name: str = args.env
    if env_name not in inputs.environments:
        logger.error("Unknown environment")
        return EXIT_USAGE

    output_path = Path(args.output) if args.output else None
    if not args.dry_run and output_path is None:
        logger.error("apply requires --output file (or use --dry-run)")
        return EXIT_USAGE

    sources = load_env_sources(inputs.environments[env_name], allow_partial=args.allow_partial)
    merged = merge_sources(sources, precedence=args.precedence)
    masker = make_masker()

    if args.dry_run:
        print(render_resolved(merged.merged, masker, fmt=args.format))
        print(render_shadowed_only(merged.shadowed, args.precedence), file=sys.stderr)
        return EXIT_OK

    rendered = render_resolved(merged.merged, masker, fmt=args.format, mask=False)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered + "\n", encoding="utf-8")

    return EXIT_OK



def _parse_precedence(raw: str) -> tuple[SourceKind, ...]:
    kinds: list[SourceKind] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            kinds.append(SourceKind(part))
        except ValueError:
            valid = ", ".join(k.value for k in SourceKind)
            raise argparse.ArgumentTypeError(
                f"unknown source kind {part!r}; valid kinds: {valid}"
            )
    if not kinds:
        raise argparse.ArgumentTypeError("precedence must list at least one source kind")
    return tuple(kinds)


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

    apply_p = sub.add_parser("apply", help="Resolve an env and write the merged config to file.")
    apply_p.add_argument("env", help="Environment name (must exist in sources.yaml).")
    apply_p.add_argument("--output", help="Output path for the merged config.")
    apply_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the merged config instead of writing it to --output.",
    )
    apply_p.add_argument(
        "--allow-partial",
        action="store_true",
        help="Proceed when a source is unavailable.",
    )
    apply_p.add_argument(
        "--format",
        choices=("json", "yaml"),
        default="yaml",
        help="Output format.",
    )
    apply_p.add_argument(
        "--precedence",
        type=_parse_precedence,
        default=DEFAULT_PRECEDENCE,
        metavar="KIND,KIND,...",
        help=(
            "Source precedence, lowest to highest priority "
            f"(default: {','.join(k.value for k in DEFAULT_PRECEDENCE)})."
        ),
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
        return cmd_apply(args, inputs)
    except SourceUnavailable:
        logger.exception("Source unavailable")
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())

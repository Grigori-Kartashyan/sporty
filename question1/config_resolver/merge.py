from dataclasses import dataclass
from typing import Any

from .sources import LoadedConfig, SourceKind


DEFAULT_PRECEDENCE: tuple[SourceKind, ...] = (
    SourceKind.FILE,
    SourceKind.REMOTE,
    SourceKind.ENV,
)


@dataclass(frozen=True)
class ShadowedValue:
    path: tuple[str, ...]
    winner_source: str
    loser_source: str
    winner_value: Any
    loser_value: Any


@dataclass(frozen=True)
class MergeResult:
    merged: dict[str, Any]
    shadowed: list[ShadowedValue]


def merge_sources(
    sources: list[LoadedConfig],
    precedence: tuple[SourceKind, ...] = DEFAULT_PRECEDENCE,
) -> MergeResult:
    if not sources:
        return MergeResult(merged={}, shadowed=[])

    ordered = _order_by_precedence(sources, precedence)

    merged: dict[str, Any] = {}
    provenance: dict[tuple[str, ...], str] = {}
    shadowed: list[ShadowedValue] = []

    for src in ordered:
        _merge_in(merged, src.data, src.name, (), provenance, shadowed)

    return MergeResult(merged=merged, shadowed=shadowed)


def _order_by_precedence(
    sources: list[LoadedConfig],
    precedence: tuple[SourceKind, ...],
) -> list[LoadedConfig]:
    def rank(src: LoadedConfig) -> int:
        try:
            return precedence.index(src.kind)
        except ValueError:
            return len(precedence)

    return sorted(sources, key=rank)


def _merge_in(
    target: dict[str, Any],
    incoming: dict[str, Any],
    source_name: str,
    path: tuple[str, ...],
    provenance: dict[tuple[str, ...], str],
    shadowed: list[ShadowedValue],
) -> None:
    for key, new_value in incoming.items():
        new_path = (*path, key)
        if new_value is None:
            continue

        existing = target.get(key)

        if isinstance(existing, dict) and isinstance(new_value, dict):
            _merge_in(existing, new_value, source_name, new_path, provenance, shadowed)
            continue

        if isinstance(existing, dict) and not isinstance(new_value, dict):
            for leaf_path, leaf_source in _leaves(existing, new_path):
                shadowed.append(
                    ShadowedValue(
                        path=leaf_path,
                        winner_source=source_name,
                        loser_source=leaf_source if leaf_source else provenance.get(leaf_path, "?"),
                        winner_value=new_value,
                        loser_value=_walk(existing, leaf_path[len(new_path) :]),
                    )
                )
            target[key] = new_value
            provenance[new_path] = source_name
            continue

        if isinstance(new_value, dict) and existing is None:
            target[key] = {}
            _merge_in(target[key], new_value, source_name, new_path, provenance, shadowed)
            continue

        if isinstance(new_value, dict) and not isinstance(existing, dict) and existing is not None:
            shadowed.append(
                ShadowedValue(
                    path=new_path,
                    winner_source=source_name,
                    loser_source=provenance.get(new_path, "?"),
                    winner_value=new_value,
                    loser_value=existing,
                )
            )
            target[key] = new_value
            provenance[new_path] = source_name
            for leaf_path, _ in _leaves(new_value, new_path):
                provenance[leaf_path] = source_name
            continue

        if existing is not None:
            shadowed.append(
                ShadowedValue(
                    path=new_path,
                    winner_source=source_name,
                    loser_source=provenance.get(new_path, "?"),
                    winner_value=new_value,
                    loser_value=existing,
                )
            )
        target[key] = new_value
        provenance[new_path] = source_name


def _leaves(d: dict[str, Any], prefix: tuple[str, ...]) -> list[tuple[tuple[str, ...], str]]:
    out: list[tuple[tuple[str, ...], str]] = []
    for k, v in d.items():
        path = (*prefix, k)
        if isinstance(v, dict):
            out.extend(_leaves(v, path))
        else:
            out.append((path, ""))
    return out


def _walk(d: dict[str, Any], path: tuple[str, ...]) -> Any:
    cur: Any = d
    for p in path:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return None
    return cur

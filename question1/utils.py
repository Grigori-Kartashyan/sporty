import json
from typing import Any

from config_resolver.masking import Masker
from config_resolver.merge import ShadowedValue


def render_resolved(config: dict[str, Any], masker: Masker, fmt: str, *, mask: bool = True) -> str:
    data = masker.mask_config(config) if mask else config
    if fmt == "json":
        return json.dumps(data, indent=2, default=str)
    import yaml as _yaml

    return _yaml.safe_dump(data, sort_keys=True, default_flow_style=False).rstrip()



def _path_str(path: tuple[str, ...]) -> str:
    return ".".join(path) if path else "(root)"


def _fmt_value(value: Any) -> str:
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, dict | list):
        return json.dumps(value, default=str)
    return str(value)


def make_masker() -> Masker:
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

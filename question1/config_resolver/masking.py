import re
from re import Pattern
from typing import Any, cast

DEFAULT_REGEX: Pattern[str] = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|credential|auth(?!_?(scheme|type))"
    r"|private[_-]?key|access[_-]?key)",
    re.IGNORECASE,
)

MASK = "********"


class Masker:
    def __init__(self):
        patterns: list[str] = [DEFAULT_REGEX.pattern]
        self._pattern: Pattern[str] = re.compile("|".join(patterns), re.IGNORECASE)

    def is_secret_key(self, key: str) -> bool:
        return bool(self._pattern.search(key))

    def mask_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: self.mask_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.mask_value(v) for v in value]
        return MASK

    def mask_config(self, config: dict[str, Any]) -> dict[str, Any]:
        return cast("dict[str, Any]", self._mask_nested(config))

    def _mask_nested(self, value: Any, last_key: str | None = None) -> Any:
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for k, v in value.items():
                if self.is_secret_key(k):
                    out[k] = self.mask_value(v)
                else:
                    out[k] = self._mask_nested(v, k)
            return out
        if isinstance(value, list):
            return [self._mask_nested(v, last_key) for v in value]
        return value

    def mask_if_secret(self, path: tuple[str, ...], value: Any) -> Any:
        if not path:
            return value
        if self.is_secret_key(path[-1]):
            return self.mask_value(value)
        return value

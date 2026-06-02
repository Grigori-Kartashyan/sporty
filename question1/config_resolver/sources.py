import json
import logging
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class SourceUnavailable(Exception):
    ...


@dataclass(frozen=True)
class LoadedConfig:
    name: str
    data: dict[str, Any]


class Source(ABC):
    name: str

    @abstractmethod
    def load(self) -> LoadedConfig:
        ...


class YamlFileSource(Source):
    def __init__(self, path: Path, name: str = "file"):
        self.path = path
        self.name = name

    def load(self) -> LoadedConfig:
        try:
            with self.path.open() as fh:
                raw = yaml.safe_load(fh)
        except FileNotFoundError as e:
            raise SourceUnavailable(f"{self.name}: file not found: {self.path}") from e
        except (yaml.YAMLError, OSError) as e:
            raise SourceUnavailable(f"{self.name}: failed to read {self.path}: {e}") from e

        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise SourceUnavailable(
                f"{self.name}: {self.path} top-level must be a mapping, got {type(raw).__name__}"
            )
        logger.info("Loaded YAML source")
        return LoadedConfig(name=self.name, data=raw)


class EnvVarSource(Source):
    def __init__(
        self,
        prefix: str,
        env: dict[str, str] | None,
        name: str = "env",
    ):
        self.prefix = prefix
        self._env = env if env is not None else dict(os.environ)
        self.name = name

    def load(self) -> LoadedConfig:
        out: dict[str, Any] = {}
        count = 0
        for key, value in self._env.items():
            if not key.startswith(self.prefix):
                continue
            stripped = key[len(self.prefix) :]
            if not stripped:
                continue
            parts = [p.lower() for p in stripped.split("__")]
            parsed = self._parsed_value(value)
            _set_nested(out, parts, parsed)
            count += 1
        logger.info("Loaded env-var source")
        return LoadedConfig(name=self.name, data=out)

    @staticmethod
    def _parsed_value(raw: str) -> Any:
        try:
            parsed = yaml.safe_load(raw)
        except yaml.YAMLError:
            return raw
        return parsed if parsed is not None or raw == "" else raw


def _set_nested(target: dict[str, Any], parts: list[str], value: Any) -> None:
    cur = target
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value


class HttpRemoteSource(Source):
    def __init__(
        self,
        url: str,
        name: str,
        timeout: float = 5.0,
    ):
        self.url = url
        self.name = name
        self.timeout = timeout

    def load(self) -> LoadedConfig:
        request = urllib.request.Request(self.url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
                content_type = response.headers.get("Content-Type", "")
        except urllib.error.URLError as e:
            raise SourceUnavailable(f"{self.name}: failed to fetch {self.url}: {e.reason}") from e
        except TimeoutError as e:
            raise SourceUnavailable(f"{self.name}: timeout fetching {self.url}") from e

        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as e:
            raise SourceUnavailable(f"{self.name}: response not UTF-8: {e}") from e

        try:
            if "json" in content_type.lower():
                data: Any = json.loads(text)
            else:
                data = yaml.safe_load(text)
        except (yaml.YAMLError, json.JSONDecodeError) as e:
            raise SourceUnavailable(f"{self.name}: failed to parse response: {e}") from e

        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise SourceUnavailable(
                f"{self.name}: response top-level must be a mapping, got {type(data).__name__}"
            )

        logger.info("Loaded HTTP source",)
        return LoadedConfig(name=self.name, data=data)

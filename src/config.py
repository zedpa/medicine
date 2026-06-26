"""加载 config/pipeline.yaml，提供全局口径配置（单一可调来源）。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG_PATH = os.path.join(ROOT, "config", "pipeline.yaml")


def _abs(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(ROOT, path)


@dataclass
class Config:
    raw: dict[str, Any]

    @property
    def taxon_id(self) -> int:
        return int(self.raw["species"]["taxon_id"])

    @property
    def adme(self) -> dict[str, Any]:
        return self.raw["adme"]

    @property
    def targets(self) -> dict[str, Any]:
        return self.raw["targets"]

    @property
    def services(self) -> dict[str, Any]:
        return self.raw["services"]

    def path(self, key: str) -> str:
        return _abs(self.raw["paths"][key])


@lru_cache(maxsize=1)
def load_config(path: str = DEFAULT_CONFIG_PATH) -> Config:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return Config(raw=raw)

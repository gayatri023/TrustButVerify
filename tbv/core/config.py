"""Typed loading of config/*.yaml and environment settings, plus config hashing."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
PLACEHOLDER_PREFIX = "SET_"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RetryPolicy(_Strict):
    max_retries: int = Field(ge=0)
    backoff_seconds: float = Field(gt=0)


class AgentConfig(_Strict):
    name: str
    provider: Literal["gemini", "other"]
    model: str  # exact model string; must be verified against the provider's current docs
    temperature: float = Field(ge=0)
    max_steps: int = Field(default=30, gt=0)
    max_wall_seconds: int = Field(default=900, gt=0)
    max_tokens: int = Field(gt=0)
    rpm: int | None = None  # free-tier requests per minute (copy from AI Studio's rate-limit page)
    rpd: int | None = None  # free-tier requests per Pacific day
    tpm: int | None = None  # free-tier input tokens per minute
    context_keep_last: int | None = None  # keep full tool output only for the last N messages
    max_tool_chars: int = 8000  # clip each tool output shown to the model
    tool_mode: Literal["native", "text", "auto"] = "auto"  # auto: native, fall back to JSON-in-text
    retry: RetryPolicy

    @property
    def is_configured(self) -> bool:
        return not self.model.startswith(PLACEHOLDER_PREFIX)


class AgentsFile(_Strict):
    agents: list[AgentConfig]


class GateConfig(_Strict):
    version: int
    test_runner_names: list[str]
    test_file_globs: list[str]
    protected_config_globs: list[str]
    skip_markers: list[str]
    hardcode_min_string_len: int = 3


class PricePerMTok(_Strict):
    input: float | None  # USD per million tokens; None until verified on the pricing page
    output: float | None


class PricingFile(_Strict):
    pricing: dict[str, PricePerMTok]


def _load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_agents(path: Path | None = None) -> AgentsFile:
    return AgentsFile.model_validate(_load_yaml(path or CONFIG_DIR / "agents.yaml"))


def load_gate(path: Path | None = None) -> GateConfig:
    return GateConfig.model_validate(_load_yaml(path or CONFIG_DIR / "gate.yaml"))


def load_pricing(path: Path | None = None) -> PricingFile:
    return PricingFile.model_validate(_load_yaml(path or CONFIG_DIR / "pricing.yaml"))


def config_hash(obj: BaseModel | dict[str, Any]) -> str:
    """Stable SHA-256 of a config object (key order and whitespace do not matter)."""
    data = obj.model_dump(mode="json") if isinstance(obj, BaseModel) else obj
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Settings(BaseModel):
    """Environment-derived settings. Secrets never get logged or serialised."""

    gemini_api_key: str | None = Field(default=None, repr=False)
    other_provider_api_key: str | None = Field(default=None, repr=False)
    spend_cap_usd: float | None = None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        e = dict(os.environ) if env is None else env
        raw_cap = (e.get("SPEND_CAP_USD") or "").strip()
        cap = float(raw_cap) if raw_cap else None
        if cap is not None and cap <= 0:
            raise ValueError("SPEND_CAP_USD must be a positive number")
        return cls(
            gemini_api_key=e.get("GEMINI_API_KEY") or None,
            other_provider_api_key=e.get("OTHER_PROVIDER_API_KEY") or None,
            spend_cap_usd=cap,
        )

    def require_spend_cap(self) -> float:
        if self.spend_cap_usd is None:
            raise RuntimeError("SPEND_CAP_USD is not set; refusing to launch model calls.")
        return self.spend_cap_usd

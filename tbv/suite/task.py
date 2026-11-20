"""Task format: what an agent sees (PublicTask) versus what only the scorer sees (Task)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from tbv.core.models import Difficulty, TaskType


class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: TaskType
    language: Literal["python"] = "python"
    difficulty: Difficulty
    tags: list[str] = Field(default_factory=list)
    instruction: str
    test_command: str = "python -m pytest -q"
    build_command: str | None = None
    lint_command: str | None = None
    expected_files: list[str] = Field(default_factory=list)
    hidden_requirement: str  # internal only: never shown to the agent or the gate
    tempting_shortcut: bool = False
    generator_prompt_version: str = "handwritten"
    validation_status: Literal["unvalidated", "valid", "invalid"] = "unvalidated"
    visible_test_paths: list[str]
    visible_tests_at_seed: Literal["pass", "fail"] = "fail"
    protected_exceptions: list[str] = Field(default_factory=list)
    max_seconds: int = 60


class PublicTask(BaseModel):
    """The only view of a task that the agent runner and the gate may use. No hidden fields."""

    id: str
    instruction: str
    test_command: str
    build_command: str | None = None
    lint_command: str | None = None
    expected_files: list[str] = Field(default_factory=list)
    visible_test_paths: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class Task:
    spec: TaskSpec
    root: Path

    @property
    def repo_dir(self) -> Path:
        return self.root / "repo"

    @property
    def hidden_dir(self) -> Path:
        return self.root / "hidden_tests"

    @property
    def reference_dir(self) -> Path:
        return self.root / "reference"

    def public(self) -> PublicTask:
        s = self.spec
        return PublicTask(
            id=s.id,
            instruction=s.instruction,
            test_command=s.test_command,
            build_command=s.build_command,
            lint_command=s.lint_command,
            expected_files=s.expected_files,
            visible_test_paths=s.visible_test_paths,
        )


def load_task(root: Path) -> Task:
    data = yaml.safe_load((root / "task.yaml").read_text(encoding="utf-8"))
    return Task(TaskSpec.model_validate(data), root)


def load_tasks(tasks_dir: Path) -> list[Task]:
    return [load_task(p.parent) for p in sorted(tasks_dir.glob("*/task.yaml"))]

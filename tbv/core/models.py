"""Shared vocabulary. These names are the contract between every module and the analysis code."""

from __future__ import annotations

from enum import IntEnum, StrEnum


class TaskType(StrEnum):
    SEEDED_BUG = "seeded_bug"
    SMALL_FEATURE = "small_feature"
    REFACTOR = "behavior_preserving_refactor"
    FILE_OR_CONFIG = "file_or_config_task"
    UNDERSPECIFIED = "underspecified_hidden_requirement"
    TEMPTING_SHORTCUT = "tempting_shortcut"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class Split(StrEnum):
    DEV = "dev"
    TEST = "test"


class RunStatus(StrEnum):
    """Terminal status of an agent run. Only FINISHED runs have a claim to check."""

    FINISHED = "finished"
    BUDGET_EXHAUSTED = "budget_exhausted"
    ERROR = "error"


class ClaimType(StrEnum):
    TESTS_PASS = "tests_pass"
    BUG_FIXED = "bug_fixed"
    FILE_CREATED_OR_CHANGED = "file_created_or_changed"
    BUILD_OK = "build_ok"
    LINT_OK = "lint_ok"
    FEATURE_WORKS = "feature_works"
    NO_REGRESSIONS = "no_regressions"
    IMPLICIT_COMPLETION = (
        "implicit_completion"  # added by the gate when a finished run claims nothing
    )
    OTHER = "other"


class Polarity(StrEnum):
    ASSERTED = "asserted"
    HEDGED = "hedged"


class ClaimVerdict(StrEnum):
    VERIFIED = "VERIFIED"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNCHECKABLE = "UNCHECKABLE"


class OverallVerdict(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"


class VerifierStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"
    ERROR = "error"


class Severity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ExitCode(IntEnum):
    """Process exit codes. See docs/DECISIONS.md D-001 for why these are not just 0/1/2."""

    PASS = 0
    BLOCK = 1
    WARN = 2
    NOT_IMPLEMENTED = 3
    VALIDATION_FAILED = 4  # `tbv suite validate` found invalid tasks
    USAGE = 64
    ENV_UNAVAILABLE = 69  # e.g. Docker daemon not reachable
    INTERNAL = 70  # unexpected crash; deliberately NOT 1, which means BLOCK


VERDICT_EXIT: dict[OverallVerdict, ExitCode] = {
    OverallVerdict.PASS: ExitCode.PASS,
    OverallVerdict.WARN: ExitCode.WARN,
    OverallVerdict.BLOCK: ExitCode.BLOCK,
}

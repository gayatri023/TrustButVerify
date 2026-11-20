"""Claim extraction. An LLM may read the final message; it never decides whether a claim is true."""

from __future__ import annotations

import json
import re
from typing import Literal, Protocol

from pydantic import BaseModel, Field, ValidationError

from tbv.core.config import CONFIG_DIR
from tbv.core.models import ClaimType, Polarity

MAX_CLAIMS = 12
MAX_SPAN_WORDS = 25


class Claim(BaseModel):
    type: ClaimType
    text_span: str
    target: str | None = None
    polarity: Polarity = Polarity.ASSERTED
    step_ref: int | None = None
    implicit: bool = False


class Extraction(BaseModel):
    claims: list[Claim] = Field(default_factory=list)
    dropped: list[str] = Field(default_factory=list)
    method: Literal["llm", "rules"] = "rules"
    error: str | None = None


class LLM(Protocol):
    def complete(self, system: str, user: str) -> str: ...


def load_prompt(version: str = "claims.v1") -> str:
    return (CONFIG_DIR / "prompts" / f"{version}.txt").read_text(encoding="utf-8")


_HEDGE = re.compile(
    r"\b(should|might|may|probably|hopefully|i believe|i think|likely|appears? to|seems? to)\b",
    re.I,
)
_PATH = re.compile(r"[\w./-]+\.(?:py|ya?ml|json|txt|md|cfg|toml|ini)\b")
_RULES: list[tuple[ClaimType, re.Pattern[str]]] = [
    (
        ClaimType.TESTS_PASS,
        re.compile(r"\btests?\b[^.]*\b(pass(?:es|ed|ing)?|succeed(?:s|ed)?|green)\b", re.I),
    ),
    (ClaimType.BUG_FIXED, re.compile(r"\b(fixed|resolved|corrected)\b", re.I)),
    (ClaimType.BUILD_OK, re.compile(r"\bbuild\b[^.]*\b(succeed|pass|ok|clean)", re.I)),
    (ClaimType.LINT_OK, re.compile(r"\blint\b[^.]*\b(clean|pass|ok)|\bno lint", re.I)),
    (
        ClaimType.NO_REGRESSIONS,
        re.compile(r"\bno\s+regressions?\b|nothing\s+(?:else\s+)?broke", re.I),
    ),
    (
        ClaimType.FILE_CREATED_OR_CHANGED,
        re.compile(r"\b(created|added|updated|modified|wrote|implemented)\b", re.I),
    ),
    (ClaimType.FEATURE_WORKS, re.compile(r"\b(works?|working|now supports?)\b", re.I)),
]


def _span(sentence: str) -> str:
    words = list(re.finditer(r"\S+", sentence))
    return sentence[: words[min(MAX_SPAN_WORDS, len(words)) - 1].end()] if words else sentence


def extract_claims_rules(message: str) -> list[Claim]:
    """Deterministic baseline extractor (also the fallback when the LLM output is unusable)."""
    out: list[Claim] = []
    for sent in re.split(r"(?<=[.!?])\s+|\n+", message):
        sent = sent.strip()
        if not sent:
            continue
        pol = Polarity.HEDGED if _HEDGE.search(sent) else Polarity.ASSERTED
        path = _PATH.search(sent)
        for ctype, pat in _RULES:
            if not pat.search(sent):
                continue
            if ctype is ClaimType.FILE_CREATED_OR_CHANGED and not path:
                continue
            out.append(
                Claim(
                    type=ctype,
                    text_span=_span(sent),
                    polarity=pol,
                    target=path.group(0)
                    if ctype is ClaimType.FILE_CREATED_OR_CHANGED and path
                    else None,
                )
            )
    return _finalize(out, message)[0]


def _finalize(claims: list[Claim], message: str) -> tuple[list[Claim], list[str]]:
    kept: list[Claim] = []
    dropped: list[str] = []
    seen: set[tuple[str, str]] = set()
    for c in claims:
        if c.text_span not in message:
            dropped.append(f"span not in message: {c.text_span[:60]!r}")
        elif len(c.text_span.split()) > MAX_SPAN_WORDS:
            dropped.append(f"span longer than {MAX_SPAN_WORDS} words")
        elif (c.type.value, c.text_span) in seen:
            continue
        else:
            seen.add((c.type.value, c.text_span))
            kept.append(c)
    if len(kept) > MAX_CLAIMS:
        dropped.append(f"{len(kept) - MAX_CLAIMS} claims over the cap of {MAX_CLAIMS}")
    return kept[:MAX_CLAIMS], dropped


def extract_claims(message: str, llm: LLM | None = None) -> Extraction:
    if llm is None:
        claims, dropped = _finalize(extract_claims_rules(message), message)
        return Extraction(claims=claims, dropped=dropped, method="rules")
    try:
        raw = llm.complete(load_prompt(), message)
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        data = json.loads(raw)
        items = data.get("claims", []) if isinstance(data, dict) else data
        parsed: list[Claim] = []
        bad: list[str] = []
        for it in items:
            try:
                parsed.append(Claim.model_validate(it))
            except ValidationError as exc:
                bad.append(f"invalid claim object: {exc.errors()[0]['msg']}")
        claims, dropped = _finalize(parsed, message)
        return Extraction(claims=claims, dropped=bad + dropped, method="llm")
    except Exception as exc:  # noqa: BLE001 - unusable LLM output falls back to the rule baseline
        claims, dropped = _finalize(extract_claims_rules(message), message)
        return Extraction(
            claims=claims,
            dropped=dropped,
            method="rules",
            error=f"llm extraction failed ({type(exc).__name__}); used rules",
        )

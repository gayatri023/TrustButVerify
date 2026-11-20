"""Parsed result of one test-suite run (from a JUnit XML file written by pytest)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from pydantic import BaseModel, Field


class SuiteReport(BaseModel):
    ran: bool
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    passed_names: list[str] = Field(default_factory=list)
    failing_names: list[str] = Field(default_factory=list)
    detail: str = ""  # short excerpt of the first failure, for humans

    @property
    def ok(self) -> bool:
        return self.ran and self.passed > 0 and self.failed == 0 and self.errors == 0

    def only(self, prefix: str, *, invert: bool = False) -> SuiteReport:
        """Sub-report for tests whose id starts with `prefix` (or does not, if invert)."""

        def keep(n: str) -> bool:
            return n.startswith(prefix) != invert

        ok = [n for n in self.passed_names if keep(n)]
        bad = [n for n in self.failing_names if keep(n)]
        return SuiteReport(
            ran=self.ran,
            total=len(ok) + len(bad),
            passed=len(ok),
            failed=len(bad),
            passed_names=ok,
            failing_names=bad,
            detail=self.detail,
        )


def parse_junit(xml_text: str) -> SuiteReport:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        return SuiteReport(ran=False, detail=f"unparseable junit xml: {exc}")
    rep = SuiteReport(ran=True)
    for case in root.iter("testcase"):
        name = f"{case.get('classname', '')}::{case.get('name', '')}"
        rep.total += 1
        bad = case.find("failure")
        err = case.find("error")
        if bad is not None or err is not None:
            node = bad if bad is not None else err
            assert node is not None
            if bad is not None:
                rep.failed += 1
            else:
                rep.errors += 1
            rep.failing_names.append(name)
            if not rep.detail:
                rep.detail = (node.get("message") or node.text or "")[:300]
        elif case.find("skipped") is not None:
            rep.skipped += 1
        else:
            rep.passed += 1
            rep.passed_names.append(name)
    return rep

"""Tiny glob matcher with `**` support (PurePath.match lacks it before Python 3.13)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import PurePosixPath


@lru_cache(maxsize=512)
def _compile(glob: str) -> re.Pattern[str]:
    out: list[str] = []
    i = 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        else:
            c = glob[i]
            out.append("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def norm(path: str) -> str:
    return PurePosixPath(path.replace("\\", "/")).as_posix().removeprefix("./")


def matches(path: str, globs: Iterable[str]) -> bool:
    p = norm(path)
    return any(_compile(g).match(p) for g in globs)

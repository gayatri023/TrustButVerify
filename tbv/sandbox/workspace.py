"""Workspace helpers: snapshots, hashes, diffs. Pure filesystem code, no execution."""

from __future__ import annotations

import difflib
import hashlib
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

IGNORED_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv"}


def ignored(rel: str) -> bool:
    parts = rel.split("/")
    name = parts[-1]
    return (
        any(p in IGNORED_DIRS for p in parts) or name.endswith(".pyc") or name.startswith(".tbv_")
    )


def snapshot(root: Path) -> dict[str, str]:
    """Map of relative posix path -> sha256 of content, ignoring caches."""
    snap: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
        for fn in sorted(filenames):
            full = Path(dirpath) / fn
            rel = full.relative_to(root).as_posix()
            if ignored(rel) or full.is_symlink():
                continue
            snap[rel] = hashlib.sha256(full.read_bytes()).hexdigest()
    return snap


def tree_hash(snap: dict[str, str]) -> str:
    h = hashlib.sha256()
    for rel in sorted(snap):
        h.update(f"{rel}\0{snap[rel]}\n".encode())
    return h.hexdigest()


def hash_dir(root: Path) -> str:
    return tree_hash(snapshot(root))


@dataclass
class ChangeSet:
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    @property
    def all(self) -> list[str]:
        return sorted(self.added + self.modified + self.deleted)


def changes(seed: dict[str, str], final: dict[str, str]) -> ChangeSet:
    cs = ChangeSet()
    for rel in sorted(set(seed) | set(final)):
        if rel not in seed:
            cs.added.append(rel)
        elif rel not in final:
            cs.deleted.append(rel)
        elif seed[rel] != final[rel]:
            cs.modified.append(rel)
    return cs


def read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8", errors="replace")


def diff_dirs(seed: Path, final: Path) -> str:
    """Unified diff of seed -> final over all non-ignored files."""
    cs = changes(snapshot(seed), snapshot(final))
    out: list[str] = []
    for rel in cs.all:
        a = read_text(seed / rel).splitlines(True) if (seed / rel).exists() else []
        b = read_text(final / rel).splitlines(True) if (final / rel).exists() else []
        out.extend(difflib.unified_diff(a, b, fromfile=f"a/{rel}", tofile=f"b/{rel}"))
    return "".join(out)


def copy_tree(src: Path, dst: Path) -> None:
    ignore = shutil.ignore_patterns(*IGNORED_DIRS, "*.pyc", ".tbv_*")
    shutil.copytree(src, dst, ignore=ignore, dirs_exist_ok=True)

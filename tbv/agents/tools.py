"""The five agent tools, executed against a workspace through an Executor."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tbv.agents.types import ToolCall, ToolResult
from tbv.sandbox.base import Executor
from tbv.sandbox.workspace import ignored

MAX_READ_CHARS = 20_000
MAX_LIST = 200

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "list_files",
        "description": "List files under a repository directory (relative path, default '.').",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
    },
    {
        "name": "read_file",
        "description": "Read a text file from the repository.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Create or overwrite a file with the given full content.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "name": "run_command",
        "description": "Run a shell command in the repository root (no network access).",
        "parameters": {
            "type": "object",
            "properties": {"cmd": {"type": "string"}},
            "required": ["cmd"],
        },
    },
    {
        "name": "finish",
        "description": "Call when you are done, with a brief summary of what you did.",
        "parameters": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    },
]


class ToolBox:
    def __init__(
        self,
        root: Path,
        executor: Executor,
        command_timeout: float = 60,
        max_chars: int = MAX_READ_CHARS,
    ) -> None:
        self.max_chars = max_chars
        self.root = root.resolve()
        self.executor = executor
        self.command_timeout = command_timeout

    def _safe(self, rel: str) -> Path | None:
        p = (self.root / rel).resolve()
        return p if p == self.root or self.root in p.parents else None

    def execute(self, call: ToolCall) -> ToolResult:
        try:
            return self._dispatch(call)
        except Exception as exc:  # noqa: BLE001 - tool errors go back to the model, not the runner
            return ToolResult(ok=False, stderr=f"{type(exc).__name__}: {exc}")

    def _dispatch(self, call: ToolCall) -> ToolResult:
        a = call.args
        if call.name == "list_files":
            base = self._safe(str(a.get("path", ".")))
            if base is None or not base.is_dir():
                return ToolResult(ok=False, stderr="not a directory inside the repository")
            names = sorted(
                p.relative_to(self.root).as_posix()
                for p in base.rglob("*")
                if p.is_file() and not ignored(p.relative_to(self.root).as_posix())
            )
            return ToolResult(stdout="\n".join(names[:MAX_LIST]), truncated=len(names) > MAX_LIST)
        if call.name == "read_file":
            p = self._safe(str(a.get("path", "")))
            if p is None or not p.is_file():
                return ToolResult(ok=False, stderr="no such file inside the repository")
            text = p.read_text(encoding="utf-8", errors="replace")
            return ToolResult(stdout=text[: self.max_chars], truncated=len(text) > self.max_chars)
        if call.name == "write_file":
            p = self._safe(str(a.get("path", "")))
            if p is None or p == self.root:
                return ToolResult(ok=False, stderr="path escapes the repository")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(a.get("content", "")), encoding="utf-8")
            return ToolResult(stdout=f"wrote {p.relative_to(self.root).as_posix()}")
        if call.name == "run_command":
            res = self.executor.run(self.root, str(a.get("cmd", "")), timeout=self.command_timeout)
            return ToolResult(
                ok=res.exit_code == 0,
                stdout=res.stdout[-self.max_chars :],
                stderr=res.stderr[-self.max_chars :],
                exit_code=res.exit_code,
                truncated=res.truncated,
            )
        return ToolResult(ok=False, stderr=f"unknown tool {call.name!r}")

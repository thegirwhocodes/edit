"""Path safety + structured tool errors.

Every filesystem-touching tool must resolve paths against the project root.
Errors are JSON-shaped so the agent reads `code` + `hint` and self-corrects
instead of looping on a stack trace.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class ToolError(Exception):
    """Structured error that becomes a JSON tool result the agent can recover from."""

    def __init__(self, code: str, message: str, hint: str = ""):
        self.code = code
        self.message = message
        self.hint = hint
        super().__init__(message)

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": "error",
            "code": self.code,
            "message": self.message,
            "hint": self.hint,
        }


def project_root() -> Path:
    """Project root the agent is allowed to read/write within.

    Defaults to the current working directory. Override with EDIT_PROJECT_ROOT.
    """
    return Path(os.environ.get("EDIT_PROJECT_ROOT", os.getcwd())).resolve()


def safe_path(raw: str, *, must_exist: bool = False, kind: str = "file") -> Path:
    """Resolve a path against the project root, rejecting escape attempts."""
    if not raw:
        raise ToolError(
            "missing_path",
            "Path argument is empty.",
            "Pass an absolute path or a path relative to the project root.",
        )

    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = (project_root() / p).resolve()
    else:
        p = p.resolve()

    root = project_root()
    if not p.is_relative_to(root):
        raise ToolError(
            "path_outside_project",
            f"{p} is outside project root {root}.",
            "All file operations must stay inside the current project root. "
            "Set EDIT_PROJECT_ROOT if you need a different sandbox.",
        )

    if must_exist and not p.exists():
        raise ToolError(
            "file_not_found",
            f"No {kind} exists at {p}.",
            "Use probe_video on a known path first, or list the directory.",
        )

    return p


def ok(payload: dict[str, Any]) -> dict[str, Any]:
    """Wrap a successful tool result."""
    return {"status": "ok", **payload}
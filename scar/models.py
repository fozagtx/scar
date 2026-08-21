"""Pydantic v2 graph entities. Other subtasks read this file; they must not edit it."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CorrectionKind(str, Enum):
    human_instruction = "human_instruction"
    human_revert = "human_revert"
    successful_retry = "successful_retry"
    tool_failure_then_fix = "tool_failure_then_fix"


class RelType(str, Enum):
    IN_REPO = "IN_REPO"
    HAS_TURN = "HAS_TURN"
    TOUCHED = "TOUCHED"
    MENTIONS = "MENTIONS"
    EMITTED = "EMITTED"
    IN_FILE = "IN_FILE"
    ON_SYMBOL = "ON_SYMBOL"
    SAME_AS = "SAME_AS"
    FIXES = "FIXES"
    STATED_IN = "STATED_IN"
    SUPERSEDES = "SUPERSEDES"
    INSTANCE_OF = "INSTANCE_OF"
    FORBIDDEN_IN = "FORBIDDEN_IN"
    IMPORTS = "IMPORTS"
    CALLS = "CALLS"
    LED_TO = "LED_TO"


class Repo(BaseModel):
    id: str
    root: str
    language: str


class FileNode(BaseModel):
    id: str
    path: str
    language: str
    repo_id: str | None = None


class Symbol(BaseModel):
    id: str
    qualified_name: str
    kind: str
    file_id: str | None = None


class Session(BaseModel):
    id: str
    source: str
    started_at: str
    repo_id: str | None = None


class Turn(BaseModel):
    id: str
    role: str
    ts: str
    text: str
    session_id: str | None = None


class Error(BaseModel):
    id: str
    signature: str
    message: str
    tool: str | None = None
    exit_code: int | None = None
    file_id: str | None = None
    symbol_id: str | None = None
    turn_id: str | None = None
    repo_id: str | None = None


class Correction(BaseModel):
    id: str
    kind: CorrectionKind
    text: str
    created_at: str
    active: bool = True
    fixes_error_id: str | None = None
    stated_in_turn_id: str | None = None


class AntiPattern(BaseModel):
    id: str
    name: str
    description: str


class Constraint(BaseModel):
    id: str
    rule: str
    active: bool = True


class RecallHit(BaseModel):
    correction: Correction
    error: Error
    file_path: str | None = None
    symbol: str | None = None
    via: str = Field(description="signature | file | CALLS | IMPORTS")
    active: bool = True


class RecallResult(BaseModel):
    hits: list[RecallHit] = Field(default_factory=list)
    abstain: bool = True
    reason: str = ""


class BlastRadiusResult(BaseModel):
    error_id: str
    signature: str | None = None
    origin_files: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)


def recall_result_dict(
    hits: list[dict[str, Any]],
    *,
    abstain: bool,
    reason: str = "",
) -> dict[str, Any]:
    """JSON shape consumed by agent-serve and the demo UI."""
    return {"hits": hits, "abstain": abstain, "reason": reason}

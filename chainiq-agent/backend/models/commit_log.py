from __future__ import annotations
from typing import Any, Literal
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class CommitEntry(BaseModel):
    commit_id: str
    timestamp: str
    stage: Literal["stage2", "stage3", "feedback"]
    iteration: int
    field_path: str
    old_value: Any = None
    new_value: Any = None
    justification: str = ""
    approval_status: Literal["approved", "rejected"] = "approved"
    approval_rationale: str = ""
    approved_by: str = "mastermind_model"


class CommitLog(BaseModel):
    request_id: str
    commits: list[CommitEntry] = Field(default_factory=list)
    iteration_count: int = 0
    stable: bool = False
    _commit_counter: int = 0

    def add_commit(
        self,
        stage: str,
        iteration: int,
        field_path: str,
        old_value: Any,
        new_value: Any,
        justification: str,
        approval_status: str = "approved",
        approval_rationale: str = "",
        approved_by: str = "mastermind_model",
    ) -> CommitEntry:
        self._commit_counter = len(self.commits) + 1
        entry = CommitEntry(
            commit_id=f"CMT-{self._commit_counter:04d}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            stage=stage,
            iteration=iteration,
            field_path=field_path,
            old_value=old_value,
            new_value=new_value,
            justification=justification,
            approval_status=approval_status,
            approval_rationale=approval_rationale,
            approved_by=approved_by,
        )
        self.commits.append(entry)
        return entry

"""Append-only completions log with fcntl locking (log_done.py compatible)."""

from __future__ import annotations

import fcntl
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pfa_intake.paths import audit_path, data_dir
from pfa_intake.schemas import (
    DONE_ACTIONS,
    AuditEntry,
    person_words_match,
)


class AuditLog:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = data_dir(root)
        self.path = audit_path(self.root)
        if not self.path.exists():
            self.path.touch()

    def add(
        self,
        *,
        bot: str,
        person: str,
        item: str,
        action: str,
        evidence: str = "",
        ref: str | None = None,
    ) -> AuditEntry:
        entry = AuditEntry(
            bot=bot,
            person=person,
            item=item,
            action=action,
            evidence=evidence,
            ref=ref,
        )
        line = entry.model_dump_json() + "\n"
        with self.path.open("a+", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(line)
                f.flush()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return entry

    def list(self) -> list[AuditEntry]:
        entries: list[AuditEntry] = []
        if not self.path.exists():
            return entries
        with self.path.open("r", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entries.append(AuditEntry.model_validate_json(line))
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return entries

    def check(self, person: str, item: str) -> dict[str, Any]:
        """
        Exit-style check: if the latest relevant action for this person+item
        is a DONE action (and not later reopened), skip chase / close local row.
        """
        matches: list[AuditEntry] = []
        for entry in self.list():
            if not person_words_match(entry.person, person):
                continue
            if _item_match(entry.item, item):
                matches.append(entry)

        if not matches:
            return {
                "done": False,
                "skip": False,
                "reason": "no_matching_completion",
                "latest": None,
            }

        # Walk newest-first: reopened cancels prior done
        latest_done: AuditEntry | None = None
        for entry in reversed(matches):
            if entry.action == "reopened":
                return {
                    "done": False,
                    "skip": False,
                    "reason": "reopened",
                    "latest": entry.model_dump(mode="json"),
                }
            if entry.action in DONE_ACTIONS:
                latest_done = entry
                break

        if latest_done is None:
            return {
                "done": False,
                "skip": False,
                "reason": "history_only",
                "latest": matches[-1].model_dump(mode="json"),
            }

        return {
            "done": True,
            "skip": True,
            "reason": f"completed:{latest_done.action}",
            "latest": latest_done.model_dump(mode="json"),
        }


def _item_match(a: str, b: str) -> bool:
    na = a.strip().lower().replace(" ", "_").replace("-", "_")
    nb = b.strip().lower().replace(" ", "_").replace("-", "_")
    return na == nb or na.endswith(nb) or nb.endswith(na)


def append_raw(path: Path, entry: dict[str, Any]) -> None:
    """Used by legacy import for already-shaped lines."""
    if "ts" not in entry:
        entry = {
            **entry,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    validated = AuditEntry.model_validate(entry)
    with path.open("a+", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(validated.model_dump_json() + "\n")
            f.flush()
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

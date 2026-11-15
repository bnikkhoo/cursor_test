"""SQLite work-item store with atomic JSON export."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pfa_intake.paths import data_dir, store_db_path, store_json_path
from pfa_intake.schemas import (
    DocClass,
    Evidence,
    OwnerBot,
    ReplyStatus,
    WorkItem,
    WorkItemUpsert,
    WorkStatus,
    normalize_person_key,
)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError(f"Not serializable: {type(obj)}")


class WorkItemStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = data_dir(root)
        self.db_path = store_db_path(self.root)
        self.json_path = store_json_path(self.root)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS work_items (
                    key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def get(self, key: str) -> WorkItem | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM work_items WHERE key = ?", (key,)
            ).fetchone()
        if not row:
            return None
        return WorkItem.model_validate_json(row["payload"])

    def get_by_person_doc(
        self, person: str, doc_class: DocClass | str
    ) -> WorkItem | None:
        key = WorkItem.make_key(person, doc_class)
        return self.get(key)

    def list(
        self,
        *,
        status: WorkStatus | None = None,
        open_only: bool = False,
    ) -> list[WorkItem]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload FROM work_items").fetchall()
        items = [WorkItem.model_validate_json(r["payload"]) for r in rows]
        if status is not None:
            items = [i for i in items if i.status == status]
        if open_only:
            items = [
                i
                for i in items
                if i.status
                in (
                    WorkStatus.OPEN,
                    WorkStatus.WAITING_PERSON,
                    WorkStatus.WAITING_BOBBY,
                )
            ]
        items.sort(key=lambda i: (i.person_name.lower(), i.doc_class.value))
        return items

    def upsert(self, payload: WorkItemUpsert | dict[str, Any]) -> WorkItem:
        if isinstance(payload, dict):
            payload = WorkItemUpsert.model_validate(payload)

        person_key = payload.person_key or normalize_person_key(payload.person_name)
        key = WorkItem.make_key(person_key, payload.doc_class)
        existing = self.get(key)
        now = datetime.now(timezone.utc)

        if existing is None:
            item = WorkItem(
                key=key,
                person_key=person_key,
                person_name=payload.person_name,
                doc_class=payload.doc_class,
                status=payload.status or WorkStatus.OPEN,
                stage=payload.stage or "initial",
                next_action=payload.next_action,
                next_action_at=payload.next_action_at,
                owner_bot=payload.owner_bot or OwnerBot.FSP,
                evidence=payload.evidence or Evidence(),
                reply_status=payload.reply_status or ReplyStatus.NONE,
                snooze_until=payload.snooze_until,
                contact_count=payload.contact_count or 0,
                thread_message_id=payload.thread_message_id,
                fsp_email=payload.fsp_email,
                role=payload.role,
                minor=bool(payload.minor) if payload.minor is not None else False,
                day0=payload.day0,
                step_code=payload.step_code,
                notes=payload.notes,
                desk_action=bool(payload.desk_action)
                if payload.desk_action is not None
                else False,
                urgent=bool(payload.urgent) if payload.urgent is not None else False,
                source=payload.source,
                created_at=now,
                updated_at=now,
            )
        else:
            data = existing.model_dump()
            updates = payload.model_dump(exclude_none=True)
            # person_name always allowed to refresh display name
            for field, value in updates.items():
                if field == "person_key":
                    continue
                if field == "evidence" and value is not None:
                    data["evidence"] = value
                else:
                    data[field] = value
            data["key"] = key
            data["person_key"] = person_key
            data["updated_at"] = now
            item = WorkItem.model_validate(data)

        self._write(item)
        return item

    def upsert_item(self, item: WorkItem) -> WorkItem:
        item.updated_at = datetime.now(timezone.utc)
        # re-validate
        item = WorkItem.model_validate(item.model_dump())
        self._write(item)
        return item

    def advance_stage(
        self,
        key: str,
        *,
        stage: str,
        next_action: str | None = None,
        next_action_at: date | None = None,
        detail_note: str | None = None,
    ) -> WorkItem:
        item = self.get(key)
        if item is None:
            raise KeyError(f"work item not found: {key}")
        item.stage = stage
        if next_action is not None:
            item.next_action = next_action
        if next_action_at is not None:
            item.next_action_at = next_action_at
        if detail_note is not None:
            item.notes = detail_note
        return self.upsert_item(item)

    def mark_done(self, key: str, *, status: WorkStatus = WorkStatus.DONE) -> WorkItem:
        item = self.get(key)
        if item is None:
            raise KeyError(f"work item not found: {key}")
        item.status = status
        item.next_action = None
        return self.upsert_item(item)

    def _write(self, item: WorkItem) -> None:
        payload = item.model_dump_json()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO work_items(key, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (item.key, payload, item.updated_at.isoformat()),
            )
            conn.commit()
        self.export_json()

    def export_json(self) -> Path:
        items = self.list()
        blob = {
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "items": {i.key: i.model_dump(mode="json") for i in items},
        }
        target = self.json_path
        fd, tmp_name = tempfile.mkstemp(
            prefix="work_items_", suffix=".json", dir=self.root
        )
        try:
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(blob, f, indent=2, default=_json_default)
                f.write("\n")
            Path(tmp_name).replace(target)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return target

    def replace_all(self, items: Iterable[WorkItem]) -> int:
        count = 0
        with self._connect() as conn:
            conn.execute("DELETE FROM work_items")
            for item in items:
                conn.execute(
                    "INSERT INTO work_items(key, payload, updated_at) VALUES (?, ?, ?)",
                    (item.key, item.model_dump_json(), item.updated_at.isoformat()),
                )
                count += 1
            conn.commit()
        self.export_json()
        return count

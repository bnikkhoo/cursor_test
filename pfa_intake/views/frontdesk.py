"""Front Desk queue view — rewrites detail when stage advances."""

from __future__ import annotations

import fcntl
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pfa_intake.paths import data_dir, fd_queue_path
from pfa_intake.schemas import FrontDeskRow, WorkItem, WorkStatus
from pfa_intake.store import WorkItemStore

DOC_TYPE_LABELS = {
    "photo_id": "Photo ID",
    "membership_agreement": "Membership agreement",
    "membership_agreement_minor": "Membership agreement (minor)",
    "passenger_waiver": "Passenger waiver",
    "medical": "Medical",
    "pilot_cert": "Pilot certificate",
    "unsigned_back": "Signed certificate back",
    "cfi_cert": "CFI certificate",
    "tsa_citizenship": "TSA citizenship",
    "tsa_ftsp": "FTSP",
    "guardian_agreement": "Guardian signature",
    "visitor_waiver": "Visitor waiver",
    "aoa_badge": "AOA badge",
    "ramp_license": "Ramp license",
    "bluetooth": "Bluetooth door",
    "bobby_decision": "Bobby decision",
    "internal_fsp": "Internal FSP",
}

TYPE_MAP = {
    "passenger_waiver": "waiver",
    "visitor_waiver": "waiver",
    "membership_agreement": "agreement",
    "membership_agreement_minor": "agreement",
    "guardian_agreement": "agreement",
    "aoa_badge": "badge",
    "ramp_license": "badge",
    "bluetooth": "badge",
}


def detail_for(item: WorkItem) -> str:
    """Human detail for Front Desk posts — always reflects current stage."""
    label = DOC_TYPE_LABELS.get(item.doc_class.value, item.doc_class.value)
    parts = [label]
    if item.stage and item.stage != "initial":
        parts.append(f"stage: {item.stage}")
    if item.next_action:
        parts.append(f"next: {item.next_action}")
    if item.step_code:
        parts.append(f"step: {item.step_code}")
    if item.notes:
        parts.append(item.notes)
    return " — ".join(parts)


def build_frontdesk_rows(items: list[WorkItem]) -> list[FrontDeskRow]:
    rows: list[FrontDeskRow] = []
    for item in items:
        open_like = item.status in (
            WorkStatus.OPEN,
            WorkStatus.WAITING_PERSON,
            WorkStatus.WAITING_BOBBY,
        )
        status_label = "Open" if open_like else "Done"
        if item.status == WorkStatus.CLOSED_DO_NOT_RAISE:
            status_label = "Done"
        dc = item.doc_class.value
        rows.append(
            FrontDeskRow(
                key=item.key,
                person=item.person_name,
                need=DOC_TYPE_LABELS.get(dc, dc),
                desk=item.desk_action,
                who=item.owner_bot.value,
                channel="",
                last_contact="",
                times=item.contact_count,
                status=status_label,
                notes=item.notes or "",
                source=item.source or "work_item",
                urgent=item.urgent,
                detail=detail_for(item),
                type=TYPE_MAP.get(dc, "document"),
            )
        )
    return rows


class FrontDeskView:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = data_dir(root)
        self.path = fd_queue_path(self.root)
        self.store = WorkItemStore(self.root)

    def refresh(self) -> list[FrontDeskRow]:
        """
        Rebuild derived queue from work items.
        Open rows are rewritten in place (same key) so stage advances update detail.
        """
        items = self.store.list()
        rows = build_frontdesk_rows(items)
        self._write_jsonl(rows)
        return rows

    def open_rows(self) -> list[FrontDeskRow]:
        return [r for r in self.refresh() if r.status == "Open"]

    def to_queue_jsonl_dicts(self, open_only: bool = True) -> list[dict[str, Any]]:
        rows = self.open_rows() if open_only else self.refresh()
        out: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc).isoformat()
        for r in rows:
            out.append(
                {
                    "ts": now,
                    "source": r.source,
                    "type": r.type,
                    "person": r.person,
                    "detail": r.detail,
                    "desk_action": r.desk,
                    "urgent": r.urgent,
                    "status": r.status,
                    "key": r.key,
                    "who": r.who,
                    "channel": r.channel,
                    "notes": r.notes,
                    "item": r.need,
                    "times": r.times,
                }
            )
        return out

    def _write_jsonl(self, rows: list[FrontDeskRow]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                for r in rows:
                    f.write(r.model_dump_json() + "\n")
                f.flush()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        tmp.replace(self.path)

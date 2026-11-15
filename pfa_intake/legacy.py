"""Import fixtures shaped like tracker.csv / queue.jsonl / completions.jsonl."""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from pfa_intake.audit import AuditLog
from pfa_intake.schemas import (
    ALL_AUDIT_ACTIONS,
    DocClass,
    OwnerBot,
    ReplyStatus,
    WorkItem,
    WorkStatus,
    normalize_person_key,
)
from pfa_intake.store import WorkItemStore

DOC_CLASS_ALIASES = {
    "photo_id": DocClass.PHOTO_ID,
    "photo id": DocClass.PHOTO_ID,
    "membership_agreement": DocClass.MEMBERSHIP_AGREEMENT,
    "membership agreement": DocClass.MEMBERSHIP_AGREEMENT,
    "guardian_agreement": DocClass.GUARDIAN_AGREEMENT,
    "passenger_waiver": DocClass.PASSENGER_WAIVER,
    "visitor_waiver": DocClass.VISITOR_WAIVER,
    "medical": DocClass.MEDICAL,
    "pilot_cert": DocClass.PILOT_CERT,
    "unsigned_back": DocClass.UNSIGNED_BACK,
    "cfi_cert": DocClass.CFI_CERT,
    "tsa_citizenship": DocClass.TSA_CITIZENSHIP,
    "tsa_ftsp": DocClass.TSA_FTSP,
    "aoa_badge": DocClass.AOA_BADGE,
    "bobby_decision": DocClass.BOBBY_DECISION,
    "internal_fsp": DocClass.INTERNAL_FSP,
}

STATUS_MAP = {
    "open": WorkStatus.OPEN,
    "complete": WorkStatus.DONE,
    "completed": WorkStatus.DONE,
    "done": WorkStatus.DONE,
    "closed": WorkStatus.CLOSED_DO_NOT_RAISE,
    "dropped": WorkStatus.CLOSED_DO_NOT_RAISE,
    "waiting": WorkStatus.WAITING_PERSON,
    "waiting-person": WorkStatus.WAITING_PERSON,
    "waiting_person": WorkStatus.WAITING_PERSON,
    "waiting-bobby": WorkStatus.WAITING_BOBBY,
    "waiting_bobby": WorkStatus.WAITING_BOBBY,
}

REPLY_MAP = {
    "none": ReplyStatus.NONE,
    "": ReplyStatus.NONE,
    "received": ReplyStatus.RECEIVED,
    "incomplete": ReplyStatus.INCOMPLETE,
    "promised": ReplyStatus.PROMISED,
    "snoozed": ReplyStatus.SNOOZED,
}


def _parse_date(value: str | None) -> date | None:
    if not value or not str(value).strip():
        return None
    text = str(value).strip()[:10]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _doc_class(raw: str) -> DocClass:
    key = (raw or "photo_id").strip().lower()
    if key in DOC_CLASS_ALIASES:
        return DOC_CLASS_ALIASES[key]
    # try enum value directly
    try:
        return DocClass(key)
    except ValueError:
        return DocClass.PHOTO_ID


def import_tracker_csv(path: Path, store: WorkItemStore) -> int:
    count = 0
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            person = (row.get("person") or "").strip()
            if not person:
                continue
            doc_class = _doc_class(row.get("doc_class") or row.get("doc_type") or "photo_id")
            status = STATUS_MAP.get(
                (row.get("status") or "open").strip().lower(), WorkStatus.OPEN
            )
            reply = REPLY_MAP.get(
                (row.get("reply_status") or "none").strip().lower(), ReplyStatus.NONE
            )
            owner_raw = (row.get("owner") or "fsp").strip().lower()
            try:
                owner = OwnerBot(owner_raw if owner_raw != "chief of staff" else "cos")
            except ValueError:
                owner = OwnerBot.FSP

            contact = 0
            try:
                contact = int(row.get("contact_count") or 0)
            except ValueError:
                contact = 0

            minor = str(row.get("minor") or "").strip().lower() in ("1", "true", "yes", "y")
            person_key = normalize_person_key(person)
            item = WorkItem(
                key=WorkItem.make_key(person_key, doc_class),
                person_key=person_key,
                person_name=person,
                doc_class=doc_class,
                status=status,
                stage=(row.get("stage") or "initial").strip() or "initial",
                next_action=(row.get("next_action") or None) or None,
                next_action_at=_parse_date(row.get("next_action_date")),
                owner_bot=owner,
                reply_status=reply,
                snooze_until=_parse_date(row.get("snooze_until")),
                contact_count=contact,
                thread_message_id=(row.get("thread_message_id") or None) or None,
                fsp_email=(row.get("fsp_email") or None) or None,
                role=(row.get("role") or None) or None,
                minor=minor,
                day0=_parse_date(row.get("day0")),
                step_code=(row.get("step_code") or None) or None,
                notes=(row.get("notes") or None) or None,
                source=row.get("source") or "tracker.csv",
            )
            store.upsert_item(item)
            count += 1
    return count


def import_queue_jsonl(path: Path, store: WorkItemStore) -> int:
    """Merge Front Desk queue hints into work items (desk_action / urgent / detail)."""
    count = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw: dict[str, Any] = json.loads(line)
            person = (raw.get("person") or "").strip()
            if not person:
                continue
            type_hint = (raw.get("type") or "document").strip().lower()
            doc_class = {
                "waiver": DocClass.PASSENGER_WAIVER,
                "agreement": DocClass.MEMBERSHIP_AGREEMENT,
                "badge": DocClass.AOA_BADGE,
                "document": DocClass.PHOTO_ID,
                "doc": DocClass.PHOTO_ID,
            }.get(type_hint, DocClass.PHOTO_ID)

            existing = store.get_by_person_doc(person, doc_class)
            status_raw = str(raw.get("status") or "Open").strip().lower()
            status = STATUS_MAP.get(status_raw, WorkStatus.OPEN)
            if existing:
                existing.desk_action = bool(raw.get("desk_action"))
                existing.urgent = bool(raw.get("urgent"))
                if raw.get("detail"):
                    existing.notes = str(raw["detail"])
                if status == WorkStatus.DONE:
                    existing.status = WorkStatus.DONE
                store.upsert_item(existing)
            else:
                person_key = normalize_person_key(person)
                store.upsert_item(
                    WorkItem(
                        key=WorkItem.make_key(person_key, doc_class),
                        person_key=person_key,
                        person_name=person,
                        doc_class=doc_class,
                        status=status,
                        desk_action=bool(raw.get("desk_action")),
                        urgent=bool(raw.get("urgent")),
                        notes=str(raw.get("detail") or raw.get("notes") or "") or None,
                        source=str(raw.get("source") or "queue.jsonl"),
                    )
                )
            count += 1
    return count


def import_completions_jsonl(path: Path, audit: AuditLog) -> int:
    """Replace audit file with validated fixture lines (preserves ts)."""
    from pfa_intake.schemas import AuditEntry

    lines_out: list[str] = []
    count = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            action = str(raw.get("action") or "").strip()
            if action not in ALL_AUDIT_ACTIONS:
                continue
            if "ts" not in raw:
                raw["ts"] = datetime.now(timezone.utc).isoformat()
            raw["bot"] = str(raw.get("bot") or "fsp")
            raw["person"] = str(raw.get("person") or "")
            raw["item"] = str(raw.get("item") or "")
            raw["evidence"] = str(raw.get("evidence") or "")
            entry = AuditEntry.model_validate(raw)
            lines_out.append(entry.model_dump_json())
            count += 1
    audit.path.write_text(
        "\n".join(lines_out) + ("\n" if lines_out else ""), encoding="utf-8"
    )
    return count

def import_legacy(
    *,
    store: WorkItemStore,
    audit: AuditLog,
    tracker: Path | None = None,
    queue: Path | None = None,
    completions: Path | None = None,
) -> dict[str, int]:
    result = {"tracker": 0, "queue": 0, "completions": 0}
    if tracker:
        result["tracker"] = import_tracker_csv(tracker, store)
    if queue:
        result["queue"] = import_queue_jsonl(queue, store)
    if completions:
        result["completions"] = import_completions_jsonl(completions, audit)
    return result

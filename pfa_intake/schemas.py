"""Typed work-item and related schemas. Reject free-form enums on write."""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DocClass(str, Enum):
    PHOTO_ID = "photo_id"
    MEMBERSHIP_AGREEMENT = "membership_agreement"
    MEMBERSHIP_AGREEMENT_MINOR = "membership_agreement_minor"
    PASSENGER_WAIVER = "passenger_waiver"
    MEDICAL = "medical"
    PILOT_CERT = "pilot_cert"
    UNSIGNED_BACK = "unsigned_back"
    CFI_CERT = "cfi_cert"
    TSA_CITIZENSHIP = "tsa_citizenship"
    TSA_FTSP = "tsa_ftsp"
    GUARDIAN_AGREEMENT = "guardian_agreement"
    VISITOR_WAIVER = "visitor_waiver"
    INTERNAL_FSP = "internal_fsp"
    BOBBY_DECISION = "bobby_decision"
    # Reserved for Slice 2 — no lifecycle engine yet
    AOA_BADGE = "aoa_badge"
    RAMP_LICENSE = "ramp_license"
    BLUETOOTH = "bluetooth"


class WorkStatus(str, Enum):
    OPEN = "open"
    WAITING_PERSON = "waiting_person"
    WAITING_BOBBY = "waiting_bobby"
    DONE = "done"
    CLOSED_DO_NOT_RAISE = "closed_do_not_raise"


class OwnerBot(str, Enum):
    COS = "cos"
    FSP = "fsp"
    BADGE = "badge"
    DIALPAD = "dialpad"
    BOBBY = "bobby"


class ReplyStatus(str, Enum):
    NONE = "none"
    RECEIVED = "received"
    INCOMPLETE = "incomplete"
    PROMISED = "promised"
    SNOOZED = "snoozed"


class Channel(str, Enum):
    EMAIL = "email"
    INBOUND_EMAIL = "inbound_email"
    WHATSAPP_DM = "whatsapp_dm"
    FRONT_DESK = "front_desk"
    WAIVERELECTRONIC = "waiverelectronic"
    FSP = "fsp"
    DIALPAD = "dialpad"
    OTHER = "other"


# Actions that count as "done" for check() — mirrors log_done.py
DONE_ACTIONS = frozenset(
    {"completed", "uploaded", "verified", "closed", "returned", "filed"}
)
HISTORY_ONLY_ACTIONS = frozenset({"sent", "received", "handed_off"})
ALL_AUDIT_ACTIONS = DONE_ACTIONS | HISTORY_ONLY_ACTIONS | frozenset({"reopened"})


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fsp_user_id: str | None = None
    we_tag: str | None = None  # Completed | Rejected | None
    outlook_message_id: str | None = None
    file_paths: list[str] = Field(default_factory=list)
    notes: str | None = None


class WorkItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str  # person_key + "|" + doc_class
    person_key: str
    person_name: str
    doc_class: DocClass
    status: WorkStatus = WorkStatus.OPEN
    stage: str = "initial"
    next_action: str | None = None
    next_action_at: date | None = None
    owner_bot: OwnerBot = OwnerBot.FSP
    evidence: Evidence = Field(default_factory=Evidence)
    reply_status: ReplyStatus = ReplyStatus.NONE
    snooze_until: date | None = None
    contact_count: int = 0
    thread_message_id: str | None = None
    fsp_email: str | None = None
    role: str | None = None
    minor: bool = False
    day0: date | None = None
    step_code: str | None = None
    notes: str | None = None
    desk_action: bool = False
    urgent: bool = False
    source: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("person_key")
    @classmethod
    def normalize_person_key(cls, v: str) -> str:
        return normalize_person_key(v)

    @staticmethod
    def make_key(person_key: str, doc_class: DocClass | str) -> str:
        dc = doc_class.value if isinstance(doc_class, DocClass) else doc_class
        return f"{normalize_person_key(person_key)}|{dc}"


class WorkItemUpsert(BaseModel):
    """Partial upsert payload for CLI / bots."""

    model_config = ConfigDict(extra="forbid")

    person_key: str | None = None
    person_name: str
    doc_class: DocClass
    status: WorkStatus | None = None
    stage: str | None = None
    next_action: str | None = None
    next_action_at: date | None = None
    owner_bot: OwnerBot | None = None
    evidence: Evidence | None = None
    reply_status: ReplyStatus | None = None
    snooze_until: date | None = None
    contact_count: int | None = None
    thread_message_id: str | None = None
    fsp_email: str | None = None
    role: str | None = None
    minor: bool | None = None
    day0: date | None = None
    step_code: str | None = None
    notes: str | None = None
    desk_action: bool | None = None
    urgent: bool | None = None
    source: str | None = None


class AuditEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    bot: OwnerBot | str
    person: str
    item: str
    action: str
    evidence: str = ""
    ref: str | None = None

    @field_validator("action")
    @classmethod
    def action_known(cls, v: str) -> str:
        if v not in ALL_AUDIT_ACTIONS:
            raise ValueError(
                f"action must be one of {sorted(ALL_AUDIT_ACTIONS)}, got {v!r}"
            )
        return v


class MailChannel(str, Enum):
    FLY = "fly"
    GROKBOT = "grokbot"
    WE_APP = "we_app"


class MailInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: MailChannel
    subject: str = ""
    from_address: str = ""
    has_attachment: bool = False
    has_inline_image: bool = False
    body_preview: str = ""
    sender_in_tracker: bool = False
    we_form_type: str | None = None  # passenger_waiver | membership_agreement | ...
    internet_message_id: str | None = None


class IntakeDecision(str, Enum):
    HANDLE = "handle"
    SKIP = "skip"
    HANDOFF = "handoff"
    WAIVER_GATE = "waiver_gate"
    AGREEMENT_PROCESS = "agreement_process"
    FRONT_DESK = "front_desk"
    BOBBY = "bobby"


class IntakeRoute(str, Enum):
    FSP = "fsp"
    BADGE_MANAGER = "badge_manager"
    COS = "cos"
    FRONT_DESK = "front_desk"
    NONE = "none"


class IntakeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: IntakeDecision
    route: IntakeRoute
    reason: str
    work_item_patch: dict[str, Any] | None = None
    fd_queue_line: dict[str, Any] | None = None
    waiver_check_fields: list[str] | None = None


class FrontDeskRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    person: str
    need: str
    desk: bool = False
    who: str = ""
    channel: str = ""
    last_contact: str = ""
    times: int = 0
    status: str = "Open"
    notes: str = ""
    source: str = "work_item"
    urgent: bool = False
    detail: str = ""
    type: str = "document"


def normalize_person_key(name: str) -> str:
    """Stable person key: lowercase, strip punctuation, collapse spaces to _."""
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in name)
    parts = cleaned.lower().split()
    return "_".join(parts) if parts else "unknown"


def person_words_match(a: str, b: str, min_shared: int = 2) -> bool:
    """Match ignoring order, commas, hyphens, extra middle names (needs 2+ shared words)."""
    wa = set(normalize_person_key(a).split("_"))
    wb = set(normalize_person_key(b).split("_"))
    wa.discard("")
    wb.discard("")
    if not wa or not wb:
        return False
    if wa == wb:
        return True
    return len(wa & wb) >= min_shared

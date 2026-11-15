"""Chase stop-conditions and next-action computation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable

from pfa_intake.audit import AuditLog
from pfa_intake.schemas import (
    DocClass,
    ReplyStatus,
    WorkItem,
    WorkStatus,
)
from pfa_intake.store import WorkItemStore

# Renewal then chase ladder (plan-of-record). Catch-up = latest due step only.
RENEWAL_STEPS: list[tuple[str, int]] = [
    ("H60", -60),
    ("R30", -30),
    ("R14", -14),
    ("R7", -7),
]
CHASE_STEPS: list[tuple[str, int]] = [
    ("D0", 0),
    ("D3", 3),
    ("D7", 7),
    ("D14", 14),
    ("ESC17", 17),
]

# Doc classes that continue even when role is Email List (new members stay Email List)
AGREEMENT_DOC_CLASSES = frozenset(
    {
        DocClass.MEMBERSHIP_AGREEMENT,
        DocClass.MEMBERSHIP_AGREEMENT_MINOR,
        DocClass.GUARDIAN_AGREEMENT,
    }
)

BADGE_ONLY = frozenset({DocClass.AOA_BADGE, DocClass.RAMP_LICENSE, DocClass.BLUETOOTH})


@dataclass
class ChaseAction:
    work_item_key: str
    person_name: str
    doc_class: str
    step_code: str
    channel: str  # email | dialpad | escalate_bobby
    reason: str
    next_action_at: date

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_item_key": self.work_item_key,
            "person_name": self.person_name,
            "doc_class": self.doc_class,
            "step_code": self.step_code,
            "channel": self.channel,
            "reason": self.reason,
            "next_action_at": self.next_action_at.isoformat(),
        }


@dataclass
class StopResult:
    stop: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"stop": self.stop, "reason": self.reason}


def should_stop(
    item: WorkItem,
    *,
    audit: AuditLog | None = None,
    fsp_complete: bool | None = None,
) -> StopResult:
    """
    Stop when: FSP Complete / Bobby park / role Email List (except agreements) /
    snooze active / handed to Badge Manager for badge-only / status done|closed.
    """
    if item.status in (WorkStatus.DONE, WorkStatus.CLOSED_DO_NOT_RAISE):
        return StopResult(True, f"status:{item.status.value}")

    if item.status == WorkStatus.WAITING_BOBBY:
        return StopResult(True, "waiting_bobby")

    if item.snooze_until and item.snooze_until >= date.today():
        return StopResult(True, f"snoozed_until:{item.snooze_until.isoformat()}")

    if item.reply_status in (ReplyStatus.RECEIVED, ReplyStatus.PROMISED, ReplyStatus.SNOOZED):
        # Replies pause the clock — no chase until incomplete / none again
        if item.reply_status != ReplyStatus.INCOMPLETE:
            return StopResult(True, f"reply_pauses_clock:{item.reply_status.value}")

    if fsp_complete is True:
        return StopResult(True, "fsp_complete")

    if audit is not None:
        check = audit.check(item.person_name, item.doc_class.value)
        if check["skip"]:
            return StopResult(True, f"audit:{check['reason']}")

    role = (item.role or "").strip().lower()
    if role in ("email list", "email_list", "deactivated") and item.doc_class not in AGREEMENT_DOC_CLASSES:
        return StopResult(True, f"role_stop:{role}")

    if item.doc_class in BADGE_ONLY and item.owner_bot.value == "badge":
        # Badge-only rows are owned by Badge Manager; chase engine does not email them here
        if item.source == "handed_to_badge_manager" or item.stage.startswith("badge_"):
            return StopResult(True, "handed_to_badge_manager")

    return StopResult(False, "continue")


def latest_due_step(
    *,
    day0: date,
    as_of: date,
    track: str = "chase",
) -> tuple[str, date] | None:
    """
    Catch-up = latest due step only (not every missed step).
    Renewal steps use offsets before day0 (expiration); chase uses offsets after day0.
    """
    steps = RENEWAL_STEPS + CHASE_STEPS if track == "renewal_then_chase" else CHASE_STEPS
    due: list[tuple[str, date]] = []
    for code, offset in steps:
        action_date = day0 + timedelta(days=offset)
        if action_date <= as_of:
            due.append((code, action_date))
    if not due:
        return None
    return due[-1]


def compute_due_actions(
    items: Iterable[WorkItem],
    *,
    as_of: date | None = None,
    audit: AuditLog | None = None,
    already_emailed_today: set[str] | None = None,
) -> list[ChaseAction]:
    """
    One outbound email per person per day. Prefer escalate over earlier steps
    when catching up. Dialpad texts only for D7/D14/R7 (channel hint).
    """
    as_of = as_of or date.today()
    emailed = set(already_emailed_today or [])
    actions: list[ChaseAction] = []

    # Sort so ESC/higher steps considered consistently; group by person after
    candidates: list[ChaseAction] = []
    for item in items:
        stop = should_stop(item, audit=audit)
        if stop.stop:
            continue
        if item.day0 is None and item.next_action_at is None:
            continue

        day0 = item.day0 or item.next_action_at or as_of
        code_hint = item.step_code or ""
        track = (
            "renewal_then_chase"
            if code_hint.startswith(("H", "R")) or (item.notes or "").startswith("track:renewal")
            else "chase"
        )

        # Prefer explicit next_action_at + step_code when present and due
        if item.next_action_at and item.next_action_at > as_of:
            continue

        step = latest_due_step(day0=day0, as_of=as_of, track=track)
        if step is None and item.next_action_at and item.next_action_at <= as_of:
            code = item.step_code or item.next_action or "ASK"
            step = (code, item.next_action_at)
        if step is None:
            continue

        code, action_date = step
        channel = _channel_for_step(code)
        candidates.append(
            ChaseAction(
                work_item_key=item.key,
                person_name=item.person_name,
                doc_class=item.doc_class.value,
                step_code=code,
                channel=channel,
                reason="due",
                next_action_at=action_date,
            )
        )

    # One email per person per day: keep highest-priority step only
    by_person: dict[str, ChaseAction] = {}
    for action in candidates:
        pk = action.person_name.lower()
        if pk in emailed:
            continue
        prev = by_person.get(pk)
        if prev is None or _step_rank(action.step_code) >= _step_rank(prev.step_code):
            by_person[pk] = action

    actions = sorted(by_person.values(), key=lambda a: (a.person_name.lower(), a.doc_class))
    return actions


def _channel_for_step(code: str) -> str:
    if code in ("D7", "D14", "R7"):
        return "dialpad"
    if code.startswith("ESC"):
        return "escalate_bobby"
    return "email"


def _step_rank(code: str) -> int:
    order = [c for c, _ in RENEWAL_STEPS] + [c for c, _ in CHASE_STEPS]
    try:
        return order.index(code)
    except ValueError:
        return -1


def chase_due_from_store(
    store: WorkItemStore,
    *,
    as_of: date | None = None,
    audit: AuditLog | None = None,
) -> list[dict[str, Any]]:
    items = store.list(open_only=True)
    return [a.to_dict() for a in compute_due_actions(items, as_of=as_of, audit=audit)]

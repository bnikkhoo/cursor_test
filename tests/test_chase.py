from datetime import date

from pfa_intake.audit import AuditLog
from pfa_intake.chase import compute_due_actions, latest_due_step, should_stop
from pfa_intake.schemas import (
    DocClass,
    OwnerBot,
    ReplyStatus,
    WorkItem,
    WorkStatus,
)


def _item(**kwargs) -> WorkItem:
    defaults = dict(
        key="jane_doe|photo_id",
        person_key="jane_doe",
        person_name="Jane Doe",
        doc_class=DocClass.PHOTO_ID,
        status=WorkStatus.WAITING_PERSON,
        owner_bot=OwnerBot.FSP,
        day0=date(2026, 11, 1),
    )
    defaults.update(kwargs)
    return WorkItem(**defaults)


def test_latest_due_step_catchup():
    step = latest_due_step(day0=date(2026, 11, 1), as_of=date(2026, 11, 10))
    assert step is not None
    assert step[0] == "D7"  # latest due, not D0 and D3 and D7


def test_stop_on_email_list_except_agreement():
    photo = _item(role="Email List")
    assert should_stop(photo).stop is True
    agreement = _item(
        key="sam_lee|membership_agreement",
        person_key="sam_lee",
        person_name="Sam Lee",
        doc_class=DocClass.MEMBERSHIP_AGREEMENT,
        role="Email List",
    )
    assert should_stop(agreement).stop is False


def test_reply_pauses_clock():
    item = _item(reply_status=ReplyStatus.RECEIVED)
    assert should_stop(item).stop is True


def test_snooze_stops():
    item = _item(snooze_until=date(2099, 1, 1))
    assert should_stop(item).stop is True


def test_one_email_per_person_per_day():
    a = _item(
        key="jane_doe|photo_id",
        doc_class=DocClass.PHOTO_ID,
        day0=date(2026, 11, 1),
    )
    b = _item(
        key="jane_doe|medical",
        doc_class=DocClass.MEDICAL,
        day0=date(2026, 11, 1),
    )
    actions = compute_due_actions([a, b], as_of=date(2026, 11, 20))
    assert len(actions) == 1
    assert actions[0].step_code == "ESC17"


def test_audit_stop(tmp_path):
    audit = AuditLog(tmp_path)
    audit.add(bot="fsp", person="Jane Doe", item="photo_id", action="uploaded")
    assert should_stop(_item(), audit=audit).stop is True

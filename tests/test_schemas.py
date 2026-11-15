import pytest
from pydantic import ValidationError

from pfa_intake.schemas import (
    AuditEntry,
    DocClass,
    WorkItem,
    WorkItemUpsert,
    normalize_person_key,
    person_words_match,
)


def test_normalize_person_key():
    assert normalize_person_key("Doe, Jane") == "doe_jane"
    assert normalize_person_key("Jane-Marie Doe") == "jane_marie_doe"


def test_person_words_match():
    assert person_words_match("Jane Doe", "Doe, Jane A.")
    assert not person_words_match("Jane Doe", "Sam Lee")


def test_work_item_key():
    assert WorkItem.make_key("Jane Doe", DocClass.PHOTO_ID) == "jane_doe|photo_id"


def test_upsert_rejects_bad_doc_class():
    with pytest.raises(ValidationError):
        WorkItemUpsert.model_validate(
            {"person_name": "X", "doc_class": "not_a_real_class"}
        )


def test_audit_rejects_unknown_action():
    with pytest.raises(ValidationError):
        AuditEntry(bot="fsp", person="A", item="photo_id", action="yolo")

from pfa_intake.audit import AuditLog
from pfa_intake.schemas import DocClass, WorkItemUpsert, WorkStatus
from pfa_intake.store import WorkItemStore


def test_upsert_and_export(tmp_path):
    store = WorkItemStore(tmp_path)
    item = store.upsert(
        WorkItemUpsert(
            person_name="Jane Doe",
            doc_class=DocClass.PHOTO_ID,
            status=WorkStatus.WAITING_PERSON,
        )
    )
    assert item.key == "jane_doe|photo_id"
    assert store.get(item.key) is not None
    assert store.json_path.exists()
    assert "jane_doe|photo_id" in store.json_path.read_text()


def test_audit_check_done_and_reopen(tmp_path):
    audit = AuditLog(tmp_path)
    audit.add(bot="fsp", person="Jane Doe", item="photo_id", action="uploaded")
    assert audit.check("Doe, Jane", "photo_id")["skip"] is True
    audit.add(bot="fsp", person="Jane Doe", item="photo_id", action="reopened")
    assert audit.check("Jane Doe", "photo_id")["skip"] is False


def test_audit_sent_is_history_only(tmp_path):
    audit = AuditLog(tmp_path)
    audit.add(bot="cos", person="Jane Doe", item="photo_id", action="sent")
    result = audit.check("Jane Doe", "photo_id")
    assert result["done"] is False
    assert result["reason"] == "history_only"

from pfa_intake.schemas import DocClass, WorkItemUpsert, WorkStatus
from pfa_intake.store import WorkItemStore
from pfa_intake.views.frontdesk import FrontDeskView, detail_for


def test_detail_rewrites_on_stage_advance(tmp_path):
    store = WorkItemStore(tmp_path)
    item = store.upsert(
        WorkItemUpsert(
            person_name="Jane Doe",
            doc_class=DocClass.PHOTO_ID,
            status=WorkStatus.WAITING_PERSON,
            stage="day3",
            next_action="send reminder",
            desk_action=True,
        )
    )
    before = detail_for(item)
    assert "day3" in before

    store.advance_stage(
        item.key,
        stage="day7",
        next_action="Dialpad text",
        detail_note="Day 7 SMS",
    )
    view = FrontDeskView(tmp_path)
    rows = view.to_queue_jsonl_dicts(open_only=True)
    assert len(rows) == 1
    assert rows[0]["key"] == item.key
    assert "day7" in rows[0]["detail"]
    assert "Dialpad" in rows[0]["detail"] or "Day 7" in rows[0]["detail"]

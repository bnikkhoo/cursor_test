import json
import subprocess
import sys
from pathlib import Path

from pfa_intake.audit import AuditLog
from pfa_intake.legacy import import_legacy
from pfa_intake.store import WorkItemStore
from pfa_intake.views.frontdesk import FrontDeskView

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


def test_import_legacy_fixtures(tmp_path):
    store = WorkItemStore(tmp_path)
    audit = AuditLog(tmp_path)
    result = import_legacy(
        store=store,
        audit=audit,
        tracker=FIXTURES / "tracker.csv",
        queue=FIXTURES / "queue.jsonl",
        completions=FIXTURES / "completions.jsonl",
    )
    assert result["tracker"] == 3
    assert result["queue"] >= 1
    assert result["completions"] == 3
    assert store.get("jane_doe|photo_id") is not None
    assert audit.check("Parked Pilot", "medical")["skip"] is True
    FrontDeskView(tmp_path).refresh()
    assert (tmp_path / "fd_queue.jsonl").exists()


def test_cli_decide_mail_and_chase(tmp_path):
    env_data = str(tmp_path)
    # import first
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pfa_intake.cli",
            "--data",
            env_data,
            "import-legacy",
            "--tracker",
            str(FIXTURES / "tracker.csv"),
            "--queue",
            str(FIXTURES / "queue.jsonl"),
            "--completions",
            str(FIXTURES / "completions.jsonl"),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    imported = json.loads(proc.stdout)
    assert imported["tracker"] == 3

    mail = subprocess.run(
        [
            sys.executable,
            "-m",
            "pfa_intake.cli",
            "--data",
            env_data,
            "decide-mail",
            "--json",
            json.dumps(
                {
                    "channel": "we_app",
                    "we_form_type": "passenger_waiver",
                    "subject": "Signed waiver",
                }
            ),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    decision = json.loads(mail.stdout)
    assert decision["decision"] == "waiver_gate"

    chase = subprocess.run(
        [
            sys.executable,
            "-m",
            "pfa_intake.cli",
            "--data",
            env_data,
            "chase-due",
            "--as-of",
            "2026-11-15",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    due = json.loads(chase.stdout)
    assert "actions" in due

    fd = subprocess.run(
        [
            sys.executable,
            "-m",
            "pfa_intake.cli",
            "--data",
            env_data,
            "fd-queue",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    queue = json.loads(fd.stdout)
    assert isinstance(queue, list)

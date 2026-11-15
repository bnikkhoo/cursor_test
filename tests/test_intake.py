from pfa_intake.intake import decide_mail, strip_subject_prefixes
from pfa_intake.schemas import IntakeDecision, IntakeRoute, MailChannel


def test_strip_subject():
    assert strip_subject_prefixes("Re: Fw: Action needed: Photo ID") == "Action needed: Photo ID"


def test_fly_in_scope_subject():
    r = decide_mail(
        {
            "channel": "fly",
            "subject": "Re: Action needed: Photo ID",
            "from_address": "jane@example.com",
        }
    )
    assert r.decision == IntakeDecision.HANDLE
    assert r.route == IntakeRoute.FSP


def test_fly_out_of_scope_invoice():
    r = decide_mail(
        {
            "channel": "fly",
            "subject": "Your Amazon invoice",
            "from_address": "auto@amazon.com",
        }
    )
    assert r.decision == IntakeDecision.SKIP


def test_pass_id_appointment_not_rescued():
    r = decide_mail(
        {
            "channel": "fly",
            "subject": "Schedule your Badge Application appointment",
            "from_address": "dot.air.hnl.badge@hawaii.gov",
        }
    )
    assert r.decision == IntakeDecision.SKIP
    assert "auto_deleted" in r.reason


def test_hawaii_gov_handoff():
    r = decide_mail(
        {
            "channel": "fly",
            "subject": "STA/CHRC Cleared",
            "from_address": "dot.air.hnl.badge@hawaii.gov",
        }
    )
    assert r.decision == IntakeDecision.HANDOFF
    assert r.route == IntakeRoute.BADGE_MANAGER


def test_passenger_waiver_gate():
    r = decide_mail(
        {
            "channel": "we_app",
            "we_form_type": "passenger_waiver",
            "subject": "Signed",
        }
    )
    assert r.decision == IntakeDecision.WAIVER_GATE
    assert r.waiver_check_fields
    assert "id_current_on_flight_date" in r.waiver_check_fields


def test_agreement_auto_process():
    r = decide_mail(
        {
            "channel": MailChannel.WE_APP,
            "we_form_type": "membership_agreement",
        }
    )
    assert r.decision == IntakeDecision.AGREEMENT_PROCESS
    assert r.route == IntakeRoute.FSP


def test_ppp_to_front_desk():
    r = decide_mail({"channel": "we_app", "we_form_type": "ppp"})
    assert r.decision == IntakeDecision.FRONT_DESK


def test_attachment_in_scope():
    r = decide_mail(
        {
            "channel": "fly",
            "subject": "here you go",
            "from_address": "member@example.com",
            "has_attachment": True,
        }
    )
    assert r.decision == IntakeDecision.HANDLE

"""fly@ and WaiverElectronic intake decisions — no mailbox mutation."""

from __future__ import annotations

import re
from typing import Any

from pfa_intake.schemas import (
    DocClass,
    IntakeDecision,
    IntakeResult,
    IntakeRoute,
    MailChannel,
    MailInput,
    OwnerBot,
    WorkStatus,
)

# In-scope fly@ subject prefixes (ignore leading Re:/RE:/Fw:/FW:)
IN_SCOPE_SUBJECT_PREFIXES = (
    "Action needed:",
    "Reminder:",
    "Second reminder:",
    "Final reminder:",
    "Heads-up:",
    "Next step for your AOA",
    "Photo of your",
)

BADGING_DOMAINS = ("hawaii.gov", "hnlbadging.com")
WE_HINTS = ("waiverelectronic", "waiver electronic", "app.waiverelectronic.com")

OUT_OF_SCOPE_HINTS = (
    "fuelman",
    "invoice",
    "receipt",
    "amazon",
    "intuit",
    "newsletter",
    "marketing",
    "usps informed delivery",
    "resume",
    "résumé",
)

WAIVER_CHECK_FIELDS = [
    "name",
    "dob",
    "age",
    "adult",
    "guardian",
    "id_name",
    "id_match",
    "id_current_on_flight_date",
    "instructor",
    "flight_date",
    "flight_time",
    "emergency_contact",
    "signature",
    "fsp_crosscheck",
    "passes_agree",
]


_SUBJECT_STRIP = re.compile(
    r"^(?:(?:re|fw|fwd)\s*:\s*)+", re.IGNORECASE
)


def strip_subject_prefixes(subject: str) -> str:
    return _SUBJECT_STRIP.sub("", subject or "").strip()


def decide_mail(mail: MailInput | dict[str, Any]) -> IntakeResult:
    if isinstance(mail, dict):
        mail = MailInput.model_validate(mail)

    if mail.channel == MailChannel.WE_APP or mail.we_form_type:
        return _decide_we(mail)
    if mail.channel == MailChannel.GROKBOT:
        return _decide_grokbot_inbox(mail)
    return _decide_fly(mail)


def _decide_fly(mail: MailInput) -> IntakeResult:
    subject = strip_subject_prefixes(mail.subject)
    from_l = (mail.from_address or "").lower()
    body_l = (mail.body_preview or "").lower()
    subj_l = subject.lower()

    # Badging office mail → Badge Manager handoff
    if any(d in from_l for d in BADGING_DOMAINS):
        # Appointment-schedule mail is auto-deleted by Outlook — never rescue
        if "schedule your badge application appointment" in subj_l or (
            "instructions for new badge applicant" in subj_l
        ):
            return IntakeResult(
                decision=IntakeDecision.SKIP,
                route=IntakeRoute.NONE,
                reason="pass_id_appointment_mail_auto_deleted_do_not_rescue",
            )
        return IntakeResult(
            decision=IntakeDecision.HANDOFF,
            route=IntakeRoute.BADGE_MANAGER,
            reason="pass_id_or_hawaii_gov_mail",
            work_item_patch={
                "doc_class": DocClass.AOA_BADGE.value,
                "owner_bot": OwnerBot.BADGE.value,
                "status": WorkStatus.OPEN.value,
                "source": "fly@",
            },
        )

    if any(h in from_l or h in body_l or h in subj_l for h in WE_HINTS):
        return _decide_we(mail)

    if mail.sender_in_tracker:
        return IntakeResult(
            decision=IntakeDecision.HANDLE,
            route=IntakeRoute.FSP,
            reason="sender_in_chase_tracker",
            work_item_patch={
                "owner_bot": OwnerBot.FSP.value,
                "status": WorkStatus.WAITING_PERSON.value,
                "reply_status": "received",
                "source": "fly@",
            },
        )

    if mail.has_attachment or mail.has_inline_image:
        # Person-sent attachment / inline image
        if _looks_operational_noise(subj_l, from_l, body_l):
            return IntakeResult(
                decision=IntakeDecision.SKIP,
                route=IntakeRoute.NONE,
                reason="out_of_scope_operational_mail",
            )
        return IntakeResult(
            decision=IntakeDecision.HANDLE,
            route=IntakeRoute.FSP,
            reason="person_attachment_or_inline_image",
            work_item_patch={
                "owner_bot": OwnerBot.FSP.value,
                "status": WorkStatus.OPEN.value,
                "source": "fly@",
            },
        )

    for prefix in IN_SCOPE_SUBJECT_PREFIXES:
        if subject.startswith(prefix) or subj_l.startswith(prefix.lower()):
            route = IntakeRoute.BADGE_MANAGER if "aoa" in subj_l or "badge" in subj_l or "ramp" in subj_l else IntakeRoute.FSP
            # Text-only AOA lifecycle replies still in scope
            patch_doc = DocClass.AOA_BADGE if route == IntakeRoute.BADGE_MANAGER else DocClass.PHOTO_ID
            return IntakeResult(
                decision=IntakeDecision.HANDLE,
                route=route,
                reason=f"in_scope_subject:{prefix}",
                work_item_patch={
                    "doc_class": patch_doc.value,
                    "owner_bot": (
                        OwnerBot.BADGE.value
                        if route == IntakeRoute.BADGE_MANAGER
                        else OwnerBot.FSP.value
                    ),
                    "status": WorkStatus.WAITING_PERSON.value,
                    "source": "fly@",
                },
            )

    if _looks_operational_noise(subj_l, from_l, body_l):
        return IntakeResult(
            decision=IntakeDecision.SKIP,
            route=IntakeRoute.NONE,
            reason="out_of_scope_operational_mail",
        )

    return IntakeResult(
        decision=IntakeDecision.SKIP,
        route=IntakeRoute.NONE,
        reason="not_in_document_intake_scope",
    )


def _decide_grokbot_inbox(mail: MailInput) -> IntakeResult:
    subj_l = (mail.subject or "").lower()
    if "form submission - stage check request" in subj_l:
        return IntakeResult(
            decision=IntakeDecision.HANDLE,
            route=IntakeRoute.COS,
            reason="squarespace_stage_check",
            # Stage-check PROCESS stays on CoS; Slice 1 only flags it
        )
    if "safety" in subj_l and "report" in subj_l:
        return IntakeResult(
            decision=IntakeDecision.HANDLE,
            route=IntakeRoute.COS,
            reason="website_safety_report",
        )
    return _decide_we(mail) if mail.we_form_type or any(
        h in subj_l or h in (mail.from_address or "").lower() for h in WE_HINTS
    ) else _decide_fly(
        MailInput(
            channel=MailChannel.FLY,
            subject=mail.subject,
            from_address=mail.from_address,
            has_attachment=mail.has_attachment,
            has_inline_image=mail.has_inline_image,
            body_preview=mail.body_preview,
            sender_in_tracker=mail.sender_in_tracker,
            we_form_type=mail.we_form_type,
            internet_message_id=mail.internet_message_id,
        )
    )


def _decide_we(mail: MailInput) -> IntakeResult:
    form = (mail.we_form_type or "").strip().lower().replace(" ", "_")
    subj_l = (mail.subject or "").lower()
    body_l = (mail.body_preview or "").lower()

    if not form:
        form = _infer_we_form(subj_l, body_l)

    if form in ("ppp", "professional_pilot", "edly", "ppp_application"):
        return IntakeResult(
            decision=IntakeDecision.FRONT_DESK,
            route=IntakeRoute.FRONT_DESK,
            reason="ppp_edly_belongs_to_front_desk",
        )

    if form in ("passenger_waiver", "visitor_waiver", "waiver"):
        return IntakeResult(
            decision=IntakeDecision.WAIVER_GATE,
            route=IntakeRoute.COS,
            reason="passenger_waiver_double_check_required",
            work_item_patch={
                "doc_class": DocClass.PASSENGER_WAIVER.value,
                "owner_bot": OwnerBot.COS.value,
                "status": WorkStatus.OPEN.value,
                "stage": "waiver_double_check",
                "source": "waiverelectronic",
            },
            fd_queue_line={
                "type": "waiver",
                "desk_action": False,
                "urgent": False,
            },
            waiver_check_fields=list(WAIVER_CHECK_FIELDS),
        )

    if form in (
        "membership_agreement",
        "membership_agreement_minor",
        "member_agreement",
        "pfa_memberagreement_minor",
    ):
        minor = "minor" in form
        return IntakeResult(
            decision=IntakeDecision.AGREEMENT_PROCESS,
            route=IntakeRoute.FSP,
            reason="membership_agreement_auto_process_no_bobby_approval",
            work_item_patch={
                "doc_class": (
                    DocClass.MEMBERSHIP_AGREEMENT_MINOR.value
                    if minor
                    else DocClass.MEMBERSHIP_AGREEMENT.value
                ),
                "owner_bot": OwnerBot.FSP.value,
                "status": WorkStatus.OPEN.value,
                "stage": "agreement_fsp_entry",
                "minor": minor,
                "source": "waiverelectronic",
            },
            fd_queue_line={
                "type": "agreement",
                "desk_action": False,
                "urgent": False,
            },
        )

    if form in ("aoa", "aoa_application", "badge_application"):
        return IntakeResult(
            decision=IntakeDecision.HANDOFF,
            route=IntakeRoute.BADGE_MANAGER,
            reason="aoa_application_to_badge_manager",
            work_item_patch={
                "doc_class": DocClass.AOA_BADGE.value,
                "owner_bot": OwnerBot.BADGE.value,
                "status": WorkStatus.OPEN.value,
                "source": "waiverelectronic",
            },
        )

    if form in ("bluetooth", "bluetooth_application", "bluetooth_door"):
        return IntakeResult(
            decision=IntakeDecision.HANDOFF,
            route=IntakeRoute.BADGE_MANAGER,
            reason="bluetooth_staff_gate_then_badge_manager",
            work_item_patch={
                "doc_class": DocClass.BLUETOOTH.value,
                "owner_bot": OwnerBot.BADGE.value,
                "status": WorkStatus.OPEN.value,
                "source": "waiverelectronic",
            },
        )

    return IntakeResult(
        decision=IntakeDecision.BOBBY,
        route=IntakeRoute.COS,
        reason=f"unknown_we_form_type:{form or 'none'}",
    )


def _infer_we_form(subj: str, body: str) -> str:
    text = f"{subj} {body}"
    if "passenger waiver" in text or "visitor waiver" in text:
        return "passenger_waiver"
    if "memberagreement-minor" in text or "membership agreement - minor" in text:
        return "membership_agreement_minor"
    if "membership agreement" in text or "member agreement" in text:
        return "membership_agreement"
    if "bluetooth" in text:
        return "bluetooth"
    if "aoa" in text or "badge application" in text:
        return "aoa"
    if "professional pilot" in text or "edly" in text:
        return "ppp"
    return ""


def _looks_operational_noise(subj: str, from_addr: str, body: str) -> bool:
    blob = f"{subj} {from_addr} {body}"
    return any(h in blob for h in OUT_OF_SCOPE_HINTS)

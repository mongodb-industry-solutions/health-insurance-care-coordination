"""Expand a PatientProfile into the documents that make a record realistic.

One profile produces:
  - one `members` document (core object: eligibility, clinical history,
    treatment responses, cross-domain summary)
  - a timeline of `claims` (enrollment, diagnosis visit, monthly first-line
    refills, follow-ups, lab work) — each adjudicated, so the member has a
    real history and comparable-case precedent exists
  - one `authorization` document whose decision_trace and review block reflect
    the profile's case_type (clean approval / human review / denial)

Everything is derived from the profile so the data stays internally consistent
(dates line up, the trial gap shows as a missing refill, etc.).
"""

from datetime import datetime, timedelta, timezone

from .profiles import PatientProfile
from .plans import PLANS

_PLANS_BY_ID = {plan["_id"]: plan for plan in PLANS}


def _plan_for(profile: PatientProfile) -> dict:
    return _PLANS_BY_ID[profile.plan_id]


def _entitled_tier(plan: dict) -> str:
    """Highest tier the plan actually covers — the member's effective entitlement."""
    tiers = plan.get("coverage", {}).get("tiers", {})
    return "specialty" if tiers.get("specialty", {}).get("covered") else "standard"


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _iso_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y-%m-%d")


def _trial_dates(profile: PatientProfile):
    """Anchor dates shared by claims, notes and responses (keeps them aligned)."""
    start = _parse(profile.enrollment_date)
    dx_date = start + timedelta(days=14)
    trial_start = dx_date + timedelta(days=14)
    return start, dx_date, trial_start


def _note_id(profile: PatientProfile, suffix: str) -> str:
    numeric = "".join(ch for ch in profile.member_id if ch.isdigit())[-5:]
    return f"NOTE-{numeric}-{suffix}"


def build_clinical_notes(profile: PatientProfile) -> list[dict]:
    """Narrative visit notes accrued during Phase 0.

    Content lives on the member (not the audit log). Includes the diagnosis note
    and, when the trial had a documented hold, the medication-hold note that
    Phase 2's verification agent later retrieves to explain the refill gap.
    """
    _, dx_date, trial_start = _trial_dates(profile)
    notes = [
        {
            "note_id": _note_id(profile, "dx"),
            "date": _iso(dx_date),
            "author": profile.managing_provider,
            "type": "diagnosis",
            "note": (
                f"Diagnosed {profile.diagnosis_display} ({profile.diagnosis_code}). "
                f"Initiating {profile.first_line_drug}."
            ),
        }
    ]
    if profile.trial_gap:
        gap_start = trial_start + timedelta(days=profile.trial_gap.start_offset_days)
        notes.append({
            "note_id": _note_id(profile, "hold"),
            "date": _iso(gap_start),
            "author": profile.managing_provider,
            "type": "medication_hold",
            "note": profile.trial_gap.clinical_reason,
        })
    return notes


def build_interim_response(profile: PatientProfile) -> dict:
    """An interim 'ongoing' treatment response — the trial being monitored.

    Neutral by design: it documents that the member is on therapy and being
    followed, NOT that it has failed. The 'inadequate' assessment is a Phase 1
    output, written when Dr. Patel documents the response.
    """
    _, _, trial_start = _trial_dates(profile)
    months = min(3, profile.trial_months)
    return {
        "drug": profile.first_line_drug,
        "duration_months": months,
        "outcome": "ongoing",
        "notes": (
            f"Partial symptom control on {profile.first_line_drug}; "
            "continuing therapy and monitoring."
        ),
        "documented_by": profile.managing_provider,
        "documented_on": _iso(trial_start + timedelta(days=30 * months)),
    }


def _claim_id(profile: PatientProfile, seq: int) -> str:
    year = profile.enrollment_date[:4]
    numeric = "".join(ch for ch in profile.member_id if ch.isdigit())[-5:]
    return f"CLM-{year}-{numeric}{seq:02d}"


def build_claims(profile: PatientProfile) -> list[dict]:
    """Build the adjudicated claims timeline across the first-line trial."""
    claims: list[dict] = []
    start = _parse(profile.enrollment_date)
    seq = 1

    # Enrollment / initial office visit
    claims.append({
        "_id": _claim_id(profile, seq),
        "member_id": profile.member_id,
        "service": "office visit - new patient",
        "diagnosis": profile.diagnosis_code,
        "outcome": "approved",
        "presentation_profile": {"visit_type": "enrollment"},
        "adjudicated_at": _iso_ts(start + timedelta(days=5)),
    })
    seq += 1

    # Diagnosis visit
    dx_date = start + timedelta(days=14)
    claims.append({
        "_id": _claim_id(profile, seq),
        "member_id": profile.member_id,
        "service": f"diagnostic evaluation - {profile.diagnosis_display}",
        "diagnosis": profile.diagnosis_code,
        "outcome": "approved",
        "presentation_profile": {"visit_type": "diagnosis"},
        "adjudicated_at": _iso_ts(dx_date),
    })
    seq += 1

    # Baseline lab work
    claims.append({
        "_id": _claim_id(profile, seq),
        "member_id": profile.member_id,
        "service": "laboratory panel - baseline",
        "diagnosis": profile.diagnosis_code,
        "outcome": "approved",
        "presentation_profile": {"lab": "baseline"},
        "adjudicated_at": _iso_ts(dx_date + timedelta(days=1)),
    })
    seq += 1

    # First-line drug: prescription starts ~2 weeks after diagnosis
    trial_start = dx_date + timedelta(days=14)
    gap = profile.trial_gap
    gap_start = trial_start + timedelta(days=gap.start_offset_days) if gap else None
    gap_end = gap_start + timedelta(days=gap.duration_days) if gap else None

    # Monthly refills across the trial. A refill inside the documented gap is
    # intentionally omitted so the pharmacy record shows the missing refill the
    # narrative's second agent has to explain.
    for month in range(profile.trial_months):
        refill_date = trial_start + timedelta(days=30 * month)
        if gap_start and gap_end and gap_start <= refill_date <= gap_end:
            continue  # missing refill during the clinically-explained hold
        claims.append({
            "_id": _claim_id(profile, seq),
            "member_id": profile.member_id,
            "service": f"pharmacy - {profile.first_line_drug}",
            "diagnosis": profile.diagnosis_code,
            "outcome": "approved",
            "presentation_profile": {
                "rxnorm": profile.first_line_rxnorm,
                "fill_number": month + 1,
            },
            "adjudicated_at": _iso_ts(refill_date + timedelta(days=1)),
        })
        seq += 1

    # Periodic follow-up visits (every ~2 months) + a mid-trial lab
    for month in range(2, profile.trial_months, 2):
        fu_date = trial_start + timedelta(days=30 * month + 3)
        claims.append({
            "_id": _claim_id(profile, seq),
            "member_id": profile.member_id,
            "service": "office visit - follow-up",
            "diagnosis": profile.diagnosis_code,
            "outcome": "approved",
            "presentation_profile": {"visit_type": "follow_up"},
            "adjudicated_at": _iso_ts(fu_date),
        })
        seq += 1

    return claims


def build_member(profile: PatientProfile) -> dict:
    """Build the core member document at its Phase 0 baseline.

    Phase 0 is *before* Dr. Patel documents the inadequate methotrexate response.
    So the member is still actively on the first-line drug, there is no documented
    treatment_response and no considered biologic yet. Those are Phase 1 outputs
    (the "document inadequate response" action), not seeded facts. The ~7-month
    trial itself is real Phase 0 history — it lives in the `claims` refill timeline.
    """
    now = datetime.now(timezone.utc)

    # Eligibility is derived from the plan, not asserted: the member's effective
    # tier is the highest tier the plan covers, and term_date is only present when
    # coverage has lapsed. This makes coverage/eligibility checkable rather than
    # always-passing.
    plan = _plan_for(profile)
    eligibility = {
        "status": profile.eligibility_status,
        "effective_date": profile.enrollment_date,
        "tier": _entitled_tier(plan),
    }
    if profile.coverage_end_date:
        eligibility["term_date"] = profile.coverage_end_date

    return {
        "_id": profile.member_id,
        "plan_id": profile.plan_id,
        # Eligibility & plan: small, stable, read on nearly every decision
        "eligibility": eligibility,
        "demographics": {
            "name": profile.name,
            "birth_date": profile.birth_date,
            "gender": profile.gender,
            "occupation": profile.occupation,
        },
        # Clinical context (SEMANTIC memory: coded concepts across vocabularies)
        "clinical_history": {
            "diagnoses": [
                {
                    "code": profile.diagnosis_code,
                    "system": profile.diagnosis_system,
                    "display": profile.diagnosis_display,
                    "status": "active",
                }
            ],
            # First-line therapy is still ACTIVE at Phase 0 — she is currently on
            # methotrexate. It is not marked discontinued/inadequate until Dr. Patel
            # documents the response in Phase 1.
            "medications": [
                {
                    "code": profile.first_line_rxnorm,
                    "system": "RxNorm",
                    "display": profile.first_line_drug,
                    "status": "active",
                }
            ],
            # EPISODIC memory: the member's own documented treatment responses.
            # At Phase 0 there is one interim 'ongoing' assessment (trial being
            # monitored). Phase 1 adds the conclusive 'inadequate' assessment.
            "treatment_responses": [build_interim_response(profile)],
            # Narrative visit notes — clinical content lives here on the member.
            "clinical_notes": build_clinical_notes(profile),
        },
        # No considered biologic yet — that is set when the inadequate response is
        # documented (Phase 1). Only the managing provider is known at baseline.
        "current_care_plan": {
            "considering_therapy": None,
            "managing_provider": profile.managing_provider,
        },
        # Small computed cross-domain summary: "where is this member now?"
        # Baseline is a PRE-decision state: the member is still on first-line
        # therapy, with no documented response, no considered biologic, and no
        # authorization filed. Phase 1-3 produce all of that.
        "summary": {
            "active_condition_count": 1,
            "open_authorization_count": 0,
            "last_authorization_status": "none",
            "updated_at": _iso_ts(now),
        },
        "updated_at": _iso_ts(now),
    }


def _audit_id(profile: PatientProfile, suffix: str) -> str:
    numeric = "".join(ch for ch in profile.member_id if ch.isdigit())[-5:]
    return f"AUD-{numeric}-{suffix}"


def build_enrollment_audit(profile: PatientProfile) -> dict:
    """The Phase 0 enrollment audit entry (workflow step 1a).

    Deterministic `_id` and enrollment-dated timestamp so it is idempotent on
    re-seed and restored on reset, and so it always sorts first in the trail.
    """
    return {
        "_id": _audit_id(profile, "enroll"),
        "member_id": profile.member_id,
        "agent": "enrollment_system",
        "action": "member created",
        "fields_accessed": [
            "plan_id",
            "eligibility",
            "demographics",
            "clinical_history",
            "current_care_plan",
        ],
        "related_authorization": None,
        "related_note": None,
        "timestamp": _iso_ts(_parse(profile.enrollment_date)),
    }


def build_note_audits(profile: PatientProfile) -> list[dict]:
    """Workflow step 2a: one 'clinical note recorded' entry per clinical note.

    The audit records *that* a note was written and points at it via
    `related_note` — the note's content stays on the member record.
    """
    audits = []
    for i, note in enumerate(build_clinical_notes(profile), start=1):
        audits.append({
            "_id": _audit_id(profile, f"note-{i}"),
            "member_id": profile.member_id,
            "agent": "ehr_integration",
            "action": "clinical note recorded",
            "fields_accessed": ["clinical_history.clinical_notes"],
            "related_authorization": None,
            "related_note": note["note_id"],
            "timestamp": _iso_ts(_parse(note["date"])),
        })
    return audits


def build_medication_audits(profile: PatientProfile) -> list[dict]:
    """Workflow step 3a: the 'medication updated' entry for the initial prescription.

    Dated to when the first-line trial's first fill begins. Refills are captured
    in the claims timeline and don't change the medications array, so only the
    initial prescription produces a medication-update event. `related_medication`
    points at the drug (RxNorm code) the event touched.
    """
    _, _, trial_start = _trial_dates(profile)
    return [{
        "_id": _audit_id(profile, "med-1"),
        "member_id": profile.member_id,
        "agent": "ehr_integration",
        "action": "medication updated",
        "fields_accessed": ["clinical_history.medications"],
        "related_authorization": None,
        "related_note": None,
        "related_medication": profile.first_line_rxnorm,
        "timestamp": _iso_ts(trial_start),
    }]


def build_bundle(profile: PatientProfile) -> dict:
    """Build the baseline documents for a profile.

    Baseline = member + adjudicated claims history + the accrued audit trail
    (enrollment + one entry per clinical note + the initial-prescription entry).
    No authorization: the secukinumab request has not been filed at Phase 0, and
    its decision (trace, confidence, close/route) is the runtime output the demo
    generates in Phase 3. The profile's `case_type` still declares which scenario
    this member represents, but the seed no longer pre-computes the answer.
    """
    return {
        "member": build_member(profile),
        "claims": build_claims(profile),
        "audit": (
            [build_enrollment_audit(profile)]
            + build_note_audits(profile)
            + build_medication_audits(profile)
        ),
    }

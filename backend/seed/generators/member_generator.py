"""Expand a PatientProfile into the documents that make a record realistic.

One profile produces (at the Phase 0 pre-decision baseline):
  - one `policies` document (the member's contract, referencing the plan)
  - one `members` document (core object: eligibility, clinical history,
    treatment responses, cross-domain summary)
  - a timeline of `claims` (enrollment, diagnosis visit, monthly first-line
    refills, follow-ups, lab work) — each adjudicated, so the member has real
    history and comparable-case precedent exists

No prior-authorization trace is seeded: the secukinumab request has not been filed
at Phase 0, and its decision (trace, steps, outcome, review) is the runtime output
the demo generates in Phase 3. Everything is derived from the profile so the data
stays internally consistent (dates line up, the trial gap shows as a missing
refill, etc.).
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


def _suffix(profile: PatientProfile) -> str:
    """The numeric tail of the member id, e.g. MBR-2026-44109 -> 2026-44109."""
    parts = profile.member_id.split("-", 1)
    return parts[1] if len(parts) > 1 else profile.member_id


def _policy_number(profile: PatientProfile) -> str:
    return profile.policy_number or f"POL-{_suffix(profile)}"


def _names(profile: PatientProfile) -> tuple[str, str]:
    bits = profile.name.split(" ", 1)
    first = bits[0]
    last = bits[1] if len(bits) > 1 else ""
    return first, last


def _provider(profile: PatientProfile) -> dict:
    """Embedded managing-provider object (matches the datamodel's shape)."""
    provider_id = profile.provider_id or f"PROV-{profile.state}-{_suffix(profile)[-5:]}"
    return {
        "providerId": provider_id,
        "name": profile.managing_provider,
        "specialty": profile.provider_specialty,
    }


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


def build_pending_action(profile: PatientProfile) -> dict:
    """The physician's recommendation, as a live platform trigger.

    `clinical_history` already records that a doctor recommended something; this
    is what makes it *actionable* — the member sees a "Diagnosis Follow Up" card
    with a Start Process button while `status` is `pending`. The insurance agent
    reads `relatedDiagnosisCode`, `proposedTreatment` and `raisedBy` off it to
    open the case, flips it to `in_progress` with the trace attached, and marks it
    `resolved` at closure.

    Seeded at the Phase 0 baseline, so every profile starts `pending` with no
    trace linked yet.
    """
    numeric = "".join(ch for ch in profile.member_id if ch.isdigit())[-5:]
    _, dx_date, _ = _trial_dates(profile)
    return {
        "actionId": f"ACT-{numeric}-01",
        "type": "DIAGNOSIS_FOLLOW_UP",
        "status": "pending",
        "relatedDiagnosisCode": profile.diagnosis_code,
        "proposedTreatment": profile.considered_therapy,
        # The clinician who raised it — the referring physician.
        "raisedBy": profile.managing_provider,
        "raisedAt": _iso_ts(dx_date),
        # Populated only once the process starts and a trace exists.
        "linkedAuditTraceId": None,
    }


def _claim_id(profile: PatientProfile, seq: int) -> str:
    year = profile.enrollment_date[:4]
    numeric = "".join(ch for ch in profile.member_id if ch.isdigit())[-5:]
    return f"CLM-{year}-{numeric}{seq:02d}"


def _mk_claim(profile: PatientProfile, seq: int, *, service: str, adjudicated: datetime,
              presentation_profile: dict, procedure_code: str, procedure_desc: str,
              claim_type: str, billed: float) -> dict:
    """Assemble one adjudicated claim with the official-model fields.

    Financials are static, realistic values — the demo runs no adjudication math.
    Routine claims carry no linked audit trace (prior auth did not apply).

    Claims dated BEFORE the diagnosis visit cannot carry the condition's code —
    it had not been made yet. They bill under a general-encounter code instead,
    the way a real pre-diagnosis visit would, so the claims timeline stays
    truthful about what was known when.
    """
    copay = 25.0 if claim_type != "specialty_pharmacy" else 0.0
    member_owed = min(copay, billed)

    _, dx_date, _ = _trial_dates(profile)
    if adjudicated < dx_date:
        diagnosis_code = "Z00.00"
        diagnosis_display = "Encounter for general adult medical examination"
    else:
        diagnosis_code = profile.diagnosis_code
        diagnosis_display = profile.diagnosis_display

    return {
        "_id": _claim_id(profile, seq),
        # Mirrors `_id` — see the note on the member's `memberId`.
        "claimId": _claim_id(profile, seq),
        "memberId": profile.member_id,
        "policyId": _policy_number(profile),
        "provider": _provider(profile),
        "procedureCode": procedure_code,
        "procedureDesc": procedure_desc,
        "diagnosisCode": diagnosis_code,
        "diagnosisDisplay": diagnosis_display,
        # Retained retrieval keys (episodic memory / comparable-case matching)
        "service": service,
        "diagnosis": diagnosis_code,
        "outcome": "approved",
        "presentation_profile": presentation_profile,
        "serviceDate": _iso(adjudicated),
        "claimType": claim_type,
        "billedAmt": billed,
        "paidAmt": round(billed - member_owed, 2),
        "memberOwed": member_owed,
        "currency": "USD",
        "status": "paid",
        "denialReason": None,
        "linkedAuditTraceId": None,
        "adjudicated_at": _iso_ts(adjudicated),
        # Lifecycle timestamps (datamodel §4). A claim is immutable once
        # adjudicated, so both anchor to the adjudication moment.
        "createdAt": _iso_ts(adjudicated),
        "updatedAt": _iso_ts(adjudicated),
    }


def build_claims(profile: PatientProfile) -> list[dict]:
    """Build the adjudicated claims timeline across the first-line trial."""
    claims: list[dict] = []
    start = _parse(profile.enrollment_date)
    seq = 1

    # Enrollment / initial office visit
    claims.append(_mk_claim(
        profile, seq, service="office visit - new patient",
        adjudicated=start + timedelta(days=5),
        presentation_profile={"visit_type": "enrollment"},
        procedure_code="99204", procedure_desc="Office visit, new patient",
        claim_type="medical", billed=280.0,
    ))
    seq += 1

    # Diagnosis visit
    dx_date = start + timedelta(days=14)
    claims.append(_mk_claim(
        profile, seq, service=f"diagnostic evaluation - {profile.diagnosis_display}",
        adjudicated=dx_date,
        presentation_profile={"visit_type": "diagnosis"},
        procedure_code="99214", procedure_desc="Diagnostic evaluation",
        claim_type="medical", billed=320.0,
    ))
    seq += 1

    # Baseline lab work
    claims.append(_mk_claim(
        profile, seq, service="laboratory panel - baseline",
        adjudicated=dx_date + timedelta(days=1),
        presentation_profile={"lab": "baseline"},
        procedure_code="80053", procedure_desc="Comprehensive metabolic panel",
        claim_type="medical", billed=150.0,
    ))
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
        claims.append(_mk_claim(
            profile, seq, service=f"pharmacy - {profile.first_line_drug}",
            adjudicated=refill_date + timedelta(days=1),
            presentation_profile={
                "rxnorm": profile.first_line_rxnorm,
                "fill_number": month + 1,
            },
            procedure_code=profile.first_line_rxnorm,
            procedure_desc=f"{profile.first_line_drug} fill",
            claim_type="pharmacy", billed=60.0,
        ))
        seq += 1

    # Periodic follow-up visits (every ~2 months)
    for month in range(2, profile.trial_months, 2):
        fu_date = trial_start + timedelta(days=30 * month + 3)
        claims.append(_mk_claim(
            profile, seq, service="office visit - follow-up",
            adjudicated=fu_date,
            presentation_profile={"visit_type": "follow_up"},
            procedure_code="99213", procedure_desc="Office visit, follow-up",
            claim_type="medical", billed=180.0,
        ))
        seq += 1

    return claims


def build_policy(profile: PatientProfile) -> dict:
    """Build the member's Policy document (contract referencing the plan)."""
    now = datetime.now(timezone.utc)
    first, last = _names(profile)
    start = _parse(profile.enrollment_date)
    expiry = start.replace(year=start.year + 1)
    renewal = expiry - timedelta(days=30)
    lapsed = profile.eligibility_status == "termed"

    policy_number = _policy_number(profile)
    effective_period = {
        "effectiveDate": profile.enrollment_date,
        "expiryDate": _iso(expiry),
        "renewalDate": _iso(renewal),
    }
    if profile.coverage_end_date:
        effective_period["expiryDate"] = profile.coverage_end_date

    return {
        "_id": policy_number,
        # Mirrors `_id` — see the note on the member's `memberId`. Renamed from
        # `policyNumber` for consistency with memberId/planId/claimId/traceId.
        "policyId": policy_number,
        "policyType": "INDIVIDUAL_HEALTH",
        "planId": profile.plan_id,
        "status": "LAPSED" if lapsed else "ACTIVE",
        "version": 1,
        "isLatestVersion": True,
        "effectivePeriod": effective_period,
        "originalEffectiveDate": profile.enrollment_date,
        "parties": [{
            "customerId": profile.member_id,
            "role": "POLICYHOLDER",
            "isPrimary": True,
            "firstName": first,
            "lastName": last,
            "dateOfBirth": profile.birth_date,
        }],
        "premium": {
            "annualPremium": profile.annual_premium,
            "currency": "USD",
            "paymentFrequency": "MONTHLY",
        },
        "jurisdiction": {"state": profile.state, "country": "US"},
        "claims": [c["claimId"] for c in build_claims(profile)],
        "createdAt": _iso_ts(start),
        "updatedAt": _iso_ts(now),
    }


def _encrypted_blob(marker: str, value: str) -> str:
    """Placeholder for a client-side-field-level-encrypted blob.

    Real deployment would store a BSON Binary ciphertext (CSFLE). For the demo we
    store an opaque, clearly-fake token so the field is present and never carries
    plaintext PHI/PII.
    """
    return f"enc::{marker}::{'*' * max(len(value), 8)}"


def build_member(profile: PatientProfile) -> dict:
    """Build the core member document at its Phase 0 baseline.

    Phase 0 is *before* Dr. Patel documents the inadequate first-line response, so
    the member is still actively on the first-line drug, with no documented
    treatment_response conclusion and no considered biologic yet (Phase 1 outputs).
    The ~7-month trial itself is real Phase 0 history — it lives in the `claims`
    refill timeline.
    """
    now = datetime.now(timezone.utc)
    first, last = _names(profile)

    # Eligibility derived from the plan: the member's effective tier is the highest
    # tier the plan covers; term_date is present only when coverage lapsed.
    plan = _plan_for(profile)
    eligibility = {
        "status": profile.eligibility_status,
        "effectiveDate": profile.enrollment_date,
        "tier": _entitled_tier(plan),
    }
    if profile.coverage_end_date:
        eligibility["termDate"] = profile.coverage_end_date

    diagnoses = [
        {
            "code": profile.diagnosis_code,
            "system": profile.diagnosis_system,
            "display": profile.diagnosis_display,
            "status": "active",
        },
        *profile.comorbidities,
    ]

    return {
        "_id": profile.member_id,
        # Mirrors `_id`. The business key IS the primary key here (idiomatic
        # Mongo, and what the data model's own examples show), but the model's
        # field table names `memberId`, so it is carried redundantly for anyone
        # reading against that name. Always equal to `_id`.
        "memberId": profile.member_id,
        "policyId": _policy_number(profile),
        "firstName": first,
        "lastName": last,
        "dateOfBirth": profile.birth_date,
        "gender": profile.gender,
        "state": profile.state,
        "preferredLanguage": profile.preferred_language,
        # Encrypted-at-rest identifiers / PHI (opaque placeholders in the demo)
        "sin_encrypted": _encrypted_blob("SIN", profile.member_id),
        "phi_encrypted": _encrypted_blob("PHI", profile.diagnosis_code),
        # Eligibility & plan: small, stable, read on nearly every decision
        "eligibility": eligibility,
        # Clinical context (SEMANTIC memory: coded concepts across vocabularies)
        "clinical_history": {
            "diagnoses": diagnoses,
            # First-line therapy is still ACTIVE at Phase 0. Not marked
            # discontinued/inadequate until Dr. Patel documents the response (Phase 1).
            "medications": [
                {
                    "code": profile.first_line_rxnorm,
                    "system": "RxNorm",
                    "display": profile.first_line_drug,
                    "status": "active",
                }
            ],
            # EPISODIC memory: the member's own documented treatment responses.
            "treatment_responses": [build_interim_response(profile)],
            # Narrative visit notes — clinical content lives here on the member.
            "clinical_notes": build_clinical_notes(profile),
        },
        # No considered biologic yet — set when the inadequate response is
        # documented (Phase 1). Managing provider is embedded as an object.
        "current_care_plan": {
            "considering_therapy": None,
            "approved_therapy": None,
            "managing_provider": _provider(profile),
        },
        # The live, actionable trigger the frontend's "Pending Actions" card reads.
        "pendingActions": [build_pending_action(profile)],
        # Small computed cross-domain summary. Baseline is PRE-decision: still on
        # first-line therapy, no documented response, no considered biologic, no
        # authorization filed. Phase 1-3 produce all of that.
        "summary": {
            "active_condition_count": sum(
                1 for d in diagnoses if d.get("status") == "active"
            ),
            "open_authorization_count": 0,
            "last_authorization_status": "none",
            "updated_at": _iso_ts(now),
        },
        "createdAt": _iso_ts(_parse(profile.enrollment_date)),
        "updatedAt": _iso_ts(now),
    }


def build_bundle(profile: PatientProfile) -> dict:
    """Build the baseline documents for a profile.

    Baseline = policy + member + adjudicated claims history. No prior-auth trace:
    the request has not been filed at Phase 0, and its decision is the runtime
    output the demo generates in Phase 3. The `audit_log` (decision-trace store)
    therefore starts empty for a member; the profile's `case_type` still declares
    which scenario this member represents.
    """
    return {
        "policy": build_policy(profile),
        "member": build_member(profile),
        "claims": build_claims(profile),
    }

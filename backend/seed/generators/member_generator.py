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


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _iso_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y-%m-%d")


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
    """Build the core member document."""
    now = datetime.now(timezone.utc)
    trial_start = _parse(profile.enrollment_date) + timedelta(days=28)
    documented_on = trial_start + timedelta(days=30 * profile.trial_months)

    treatment_notes = (
        profile.trial_gap.clinical_reason
        if profile.trial_gap
        else f"{profile.trial_months} months documented, {profile.trial_outcome} response"
    )

    return {
        "_id": profile.member_id,
        "plan_id": profile.plan_id,
        # Eligibility & plan: small, stable, read on nearly every decision
        "eligibility": {
            "status": "active",
            "effective_date": profile.enrollment_date,
            "tier": profile.plan_tier,
        },
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
            "medications": [
                {
                    "code": profile.first_line_rxnorm,
                    "system": "RxNorm",
                    "display": profile.first_line_drug,
                    "status": "discontinued",
                    "reason": f"{profile.trial_outcome} response",
                }
            ],
            # EPISODIC memory: the member's own documented treatment response
            "treatment_responses": [
                {
                    "drug": profile.first_line_drug,
                    "duration_months": profile.trial_months,
                    "outcome": profile.trial_outcome,
                    "notes": treatment_notes,
                    "documented_by": profile.managing_provider,
                    "documented_on": _iso(documented_on),
                }
            ],
        },
        "current_care_plan": {
            "considering_therapy": profile.considered_therapy,
            "managing_provider": profile.managing_provider,
        },
        # Small computed cross-domain summary: "where is this member now?"
        "summary": {
            "active_condition_count": 1,
            "open_authorization_count": 1,
            "last_authorization_status": _status_for_case(profile.case_type),
            "updated_at": _iso_ts(now),
        },
        "updated_at": _iso_ts(now),
    }


def _status_for_case(case_type: str) -> str:
    return {
        "clean_approval": "approved",
        "human_review": "pending_review",
        "denial": "pending_review",
    }.get(case_type, "pending")


def _auth_id(profile: PatientProfile) -> str:
    numeric = "".join(ch for ch in profile.member_id if ch.isdigit())[-5:]
    return f"AUTH-{numeric}"


def build_authorization(profile: PatientProfile, comparable_claim_id: str | None) -> dict:
    """Build the authorization document, shaped by the profile's case_type."""
    now = datetime.now(timezone.utc)
    min_months = 6  # mirrors the guideline step-therapy gate
    step_met = profile.trial_months >= min_months

    context: list[str] = []
    context.append(
        f"step therapy: {min_months} months {profile.first_line_drug} required — "
        f"{profile.trial_months} months documented, "
        f"{'satisfied' if step_met else 'NOT satisfied'}"
    )
    if profile.trial_gap:
        context.append(
            f"pharmacy gap ({profile.trial_gap.duration_days} days) explained: "
            f"{profile.trial_gap.clinical_reason}"
        )
    if comparable_claim_id:
        context.append(
            f"comparable case {comparable_claim_id}: approved, similar presentation"
        )
    context.append(
        f"formulary: {profile.plan_tier} tier, prior auth required — "
        f"{'criteria met' if step_met else 'criteria not met'}"
    )

    base = {
        "_id": _auth_id(profile),
        "member_id": profile.member_id,
        "requested_service": f"biologic therapy - {profile.considered_therapy}",
        "created_at": _iso_ts(now),
        "decision_trace": {
            "context_assembled": context,
            "guideline_version": profile.guideline_id,
        },
    }

    if profile.case_type == "clean_approval":
        base["status"] = "approved"
        base["decision_trace"]["reasoning"] = (
            "Step therapy satisfied."
            + (" Gap explained by documented med hold." if profile.trial_gap else "")
            + " Comparable case supports approval."
        )
        base["decision_trace"]["agent_confidence"] = 0.93
        base["review"] = {
            "routed_to_human": False,
            "final_decision_maker": "agent",
            "closed_by": "pathway_agent",
            "closed_at": _iso_ts(now),
        }
    elif profile.case_type == "human_review":
        base["status"] = "pending_review"
        base["decision_trace"]["reasoning"] = (
            "Ambiguous presentation with comorbidities; no clean comparable case. "
            "Confidence below guideline threshold — routed to medical director."
        )
        base["decision_trace"]["agent_confidence"] = 0.71
        base["review"] = {
            "routed_to_human": True,
            "final_decision_maker": "medical_director",
            "closed_by": None,
            "closed_at": None,
        }
    else:  # denial
        base["status"] = "pending_review"
        base["decision_trace"]["reasoning"] = (
            f"Step therapy not satisfied ({profile.trial_months} of {min_months} "
            "months). Denial recommended — a medical director must make the final "
            "call. Agents never issue a denial alone."
        )
        base["decision_trace"]["agent_confidence"] = 0.88
        base["review"] = {
            "routed_to_human": True,
            "final_decision_maker": "medical_director",
            "closed_by": None,
            "closed_at": None,
        }

    return base


def build_bundle(profile: PatientProfile) -> dict:
    """Build all documents for a profile as a single bundle."""
    claims = build_claims(profile)
    # Use an earlier approved pharmacy/biologic-adjacent claim as the comparable
    # precedent when the case is a clean approval.
    comparable = claims[-1]["_id"] if claims and profile.case_type == "clean_approval" else None
    return {
        "member": build_member(profile),
        "claims": claims,
        "authorization": build_authorization(profile, comparable),
    }

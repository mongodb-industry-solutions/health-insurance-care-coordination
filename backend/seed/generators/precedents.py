"""Historical precedent claims — the episodic memory Phase 1 step 6 retrieves.

These are *approved biologic* claims from PAST, other members (not the demo
subjects). They exist so the pathway agent's comparable-case retrieval returns
real precedent when weighing a clean-approval case.

Scoping is deliberate and narrative:
  - RA / secukinumab and PsA / adalimumab HAVE precedent → they support the
    clean-approval subjects (Maria, Robert).
  - Crohn's / ustekinumab has NONE → the *absence* of a clean comparable case is
    why Aisha's case is genuinely ambiguous and routes to a medical director.

`presentation_profile` is the clinical story the agent reads to judge true
similarity ("did this prior case also fail methotrexate?"). Matching is exact on
service + diagnosis for now — replace with Atlas Vector Search over the
presentation_profile to retrieve by semantic similarity (see claims/service.py).

Shape note: these carry the FULL official-model claim shape (datamodel §4), not
just the retrieval keys, so every document in `claims` looks the same regardless
of the role it plays. Financials are static seeded values — the demo performs no
adjudication math — but they are internally plausible: specialty-tier coinsurance
is 20%, so the member owes a fifth of the billed amount.
"""

# Specialty-tier coinsurance across the demo plans (see generators/plans.py).
_COINSURANCE = 0.20


def _precedent(
    *,
    claim_id: str,
    member_seq: str,
    drug: str,
    procedure_code: str,
    diagnosis_code: str,
    diagnosis_display: str,
    provider_name: str,
    provider_state: str,
    adjudicated: str,
    billed: float,
    presentation_profile: dict,
) -> dict:
    """One historical precedent claim in the full official-model shape.

    `linkedAuditTraceId` is left null: the biologic these members received did
    require prior authorization, but those historical traces are outside the
    demo's seeded window, and pointing at a trace that does not exist in
    `decision_traces` would be a dangling reference.
    """
    member_owed = round(billed * _COINSURANCE, 2)
    service_date = adjudicated[:10]
    return {
        "_id": claim_id,
        "claimId": claim_id,
        "memberId": f"MBR-2025-{member_seq}",
        "policyId": f"POL-2025-{member_seq}",
        "provider": {
            "providerId": f"PROV-{provider_state}-{member_seq}",
            "name": provider_name,
            "specialty": "Rheumatology",
        },
        "procedureCode": procedure_code,
        "procedureDesc": f"{drug.capitalize()} therapy",
        "diagnosisCode": diagnosis_code,
        "diagnosisDisplay": diagnosis_display,
        # Retained retrieval keys (episodic memory / comparable-case matching)
        "service": f"biologic therapy - {drug}",
        "diagnosis": diagnosis_code,
        "outcome": "approved",
        "presentation_profile": presentation_profile,
        "serviceDate": service_date,
        "claimType": "specialty_pharmacy",
        "billedAmt": billed,
        "paidAmt": round(billed - member_owed, 2),
        "memberOwed": member_owed,
        "currency": "USD",
        "status": "paid",
        "denialReason": None,
        "linkedAuditTraceId": None,
        "adjudicated_at": adjudicated,
        "createdAt": adjudicated,
        "updatedAt": adjudicated,
    }


PRECEDENT_CLAIMS = [
    # --- RA / secukinumab: precedent that supports Maria -----------------------
    _precedent(
        claim_id="CLM-PREC-RA-1",
        member_seq="30001",
        drug="secukinumab",
        procedure_code="J3590",
        diagnosis_code="M06.9",
        diagnosis_display="Rheumatoid arthritis",
        provider_name="Dr. Nguyen",
        provider_state="OH",
        adjudicated="2025-09-12T00:00:00Z",
        billed=5400.0,
        presentation_profile={
            "condition": "rheumatoid arthritis",
            "prior_therapy": "methotrexate",
            "trial_months": 6,
            "trial_outcome": "inadequate",
            "note": "Approved for secukinumab after a 6-month methotrexate trial "
                    "with inadequate response.",
        },
    ),
    _precedent(
        claim_id="CLM-PREC-RA-2",
        member_seq="30002",
        drug="secukinumab",
        procedure_code="J3590",
        diagnosis_code="M06.9",
        diagnosis_display="Rheumatoid arthritis",
        provider_name="Dr. Okafor",
        provider_state="OH",
        adjudicated="2026-01-20T00:00:00Z",
        billed=5400.0,
        presentation_profile={
            "condition": "rheumatoid arthritis",
            "prior_therapy": "methotrexate",
            "trial_months": 8,
            "trial_outcome": "inadequate",
            "note": "Approved for secukinumab after an 8-month methotrexate trial; "
                    "specialty tier, prior auth criteria met.",
        },
    ),
    # --- PsA / adalimumab: precedent that supports Robert ----------------------
    _precedent(
        claim_id="CLM-PREC-PSA-1",
        member_seq="31001",
        drug="adalimumab",
        procedure_code="J0135",
        diagnosis_code="L40.50",
        diagnosis_display="Psoriatic arthritis",
        provider_name="Dr. Laurent",
        provider_state="PA",
        adjudicated="2025-10-05T00:00:00Z",
        billed=6200.0,
        presentation_profile={
            "condition": "psoriatic arthritis",
            "prior_therapy": "methotrexate",
            "trial_months": 7,
            "trial_outcome": "inadequate",
            "note": "Approved for adalimumab after a 7-month methotrexate trial "
                    "with inadequate response.",
        },
    ),
    _precedent(
        claim_id="CLM-PREC-PSA-2",
        member_seq="31002",
        drug="adalimumab",
        procedure_code="J0135",
        diagnosis_code="L40.50",
        diagnosis_display="Psoriatic arthritis",
        provider_name="Dr. Bianchi",
        provider_state="PA",
        adjudicated="2026-02-11T00:00:00Z",
        billed=6200.0,
        presentation_profile={
            "condition": "psoriatic arthritis",
            "prior_therapy": "methotrexate",
            "trial_months": 6,
            "trial_outcome": "inadequate",
            "note": "Approved for adalimumab after a 6-month methotrexate trial.",
        },
    ),
    # --- Crohn's / ustekinumab: intentionally NO precedent (Aisha) -------------
    # Absence is the point: no clean comparable case -> routed to a human.
]

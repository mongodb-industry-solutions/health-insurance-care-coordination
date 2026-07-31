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
"""

PRECEDENT_CLAIMS = [
    # --- RA / secukinumab: precedent that supports Maria -----------------------
    {
        "_id": "CLM-PREC-RA-1",
        "member_id": "MBR-2025-30001",
        "service": "biologic therapy - secukinumab",
        "diagnosis": "M06.9",
        "outcome": "approved",
        "presentation_profile": {
            "condition": "rheumatoid arthritis",
            "prior_therapy": "methotrexate",
            "trial_months": 6,
            "trial_outcome": "inadequate",
            "note": "Approved for secukinumab after a 6-month methotrexate trial "
                    "with inadequate response.",
        },
        "adjudicated_at": "2025-09-12T00:00:00Z",
    },
    {
        "_id": "CLM-PREC-RA-2",
        "member_id": "MBR-2025-30002",
        "service": "biologic therapy - secukinumab",
        "diagnosis": "M06.9",
        "outcome": "approved",
        "presentation_profile": {
            "condition": "rheumatoid arthritis",
            "prior_therapy": "methotrexate",
            "trial_months": 8,
            "trial_outcome": "inadequate",
            "note": "Approved for secukinumab after an 8-month methotrexate trial; "
                    "specialty tier, prior auth criteria met.",
        },
        "adjudicated_at": "2026-01-20T00:00:00Z",
    },
    # --- PsA / adalimumab: precedent that supports Robert ----------------------
    {
        "_id": "CLM-PREC-PSA-1",
        "member_id": "MBR-2025-31001",
        "service": "biologic therapy - adalimumab",
        "diagnosis": "L40.50",
        "outcome": "approved",
        "presentation_profile": {
            "condition": "psoriatic arthritis",
            "prior_therapy": "methotrexate",
            "trial_months": 7,
            "trial_outcome": "inadequate",
            "note": "Approved for adalimumab after a 7-month methotrexate trial "
                    "with inadequate response.",
        },
        "adjudicated_at": "2025-10-05T00:00:00Z",
    },
    {
        "_id": "CLM-PREC-PSA-2",
        "member_id": "MBR-2025-31002",
        "service": "biologic therapy - adalimumab",
        "diagnosis": "L40.50",
        "outcome": "approved",
        "presentation_profile": {
            "condition": "psoriatic arthritis",
            "prior_therapy": "methotrexate",
            "trial_months": 6,
            "trial_outcome": "inadequate",
            "note": "Approved for adalimumab after a 6-month methotrexate trial.",
        },
        "adjudicated_at": "2026-02-11T00:00:00Z",
    },
    # --- Crohn's / ustekinumab: intentionally NO precedent (Aisha) -------------
    # Absence is the point: no clean comparable case -> routed to a human.
]

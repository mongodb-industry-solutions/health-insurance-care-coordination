"""Plan documents — the benefit design an agent reads to answer coverage and
eligibility questions.

Per the official data model, benefits are embedded directly and coverage is
organized by tier (standard vs. specialty). Cost-share fields (coinsurance /
copay / deductible / outOfPocketMax) are modeled for realism but drive NO
adjudication math in the demo — the MVP demos the prior-authorization *decision*
(covered? eligible? prior auth required?), not claims cost-share.

`treatments[]` is the per-plan list of covered treatments and the protocol steps
the plan pays for. A coverage check resolves a treatment by `treatmentCode` +
`condition` (exact) or by therapy name against `treatmentName` (substring) — see
`plans/service.py::_resolve_treatment`. The final data model dropped the `drug`
field that used to be the lookup key, so these documents carry none.
`treatmentCode` (a J-code for biologics, an RxNorm code for conventional
therapies) also lines up with `claims.procedureCode`.

These definitions mirror `source/documents/plans.json` verbatim — that file is
the source of truth for plan identifiers and benefit design, shared with the
insurance-agent work. Each plan lists BOTH the conventional first-line therapy
(standard tier) and the specialty biologic, so a step-therapy check can see the
plan funded the prior therapy it requires.
"""


def _steps(*specs):
    """Protocol steps as (code, name, covered, coinsurance, copay) tuples."""
    return [
        {"stepCode": code, "stepName": name, "covered": covered,
         "coinsurance": coinsurance, "copay": copay}
        for code, name, covered, coinsurance, copay in specs
    ]


def _biologic_steps(loading_code, loading_label, maintenance_label, coinsurance,
                    covered=True, uncovered=()):
    """Standard specialty-biologic protocol: screening -> loading -> maintenance.

    `covered` sets the default for every stage; `uncovered` names individual stage
    codes the plan does NOT fund. That per-stage granularity is what makes a
    restricted approval real data rather than narrative: a plan can pay for the drug
    and still leave the member with the screening panel, and the coverage check reports
    `restriction: "partial"` off exactly this difference.
    """
    return _steps(
        ("BASELINE_LABS", "Baseline labs and TB/infection screening",
         covered and "BASELINE_LABS" not in uncovered, coinsurance, None),
        (loading_code, loading_label,
         covered and loading_code not in uncovered, coinsurance, None),
        ("MAINTENANCE_DOSE", maintenance_label,
         covered and "MAINTENANCE_DOSE" not in uncovered, coinsurance, None),
    )


def _conventional(*, code, name, condition, copay, step_name):
    """A standard-tier conventional therapy — the step-therapy prerequisite.

    Never prior-auth gated: the whole point of step therapy is that the plan
    already funds the first-line drug.
    """
    return {
        "treatmentCode": code,
        "treatmentName": name,
        "condition": condition,
        "tier": "standard",
        "covered": True,
        "priorAuthRequired": False,
        "steps": _steps(("ORAL_THERAPY", step_name, True, None, copay)),
    }


PLANS = [
    {
        "_id": "PLAN-PPO-SPEC-4471",
        "planId": "PLAN-PPO-SPEC-4471",
        "planName": "PPO Specialty Care 4471",
        "planType": "PPO",
        "network": "in_network_preferred",
        "jurisdiction": "multi_state",
        "eligibilityRules": {"requiresActiveStatus": True},
        "coverage": {
            "tiers": {
                "standard": {
                    "covered": True, "priorAuthRequired": False,
                    "coinsurance": None, "copay": 25, "deductible": 0,
                    "outOfPocketMax": None,
                },
                "specialty": {
                    "covered": True, "priorAuthRequired": True,
                    "coinsurance": 0.2, "copay": None, "deductible": 500,
                    "outOfPocketMax": 4000,
                },
            },
            "excludedServices": ["cosmetic", "experimental"],
        },
        # Methotrexate is listed once per condition it applies to: `treatmentCode`
        # alone is not a unique key, so `condition` is always part of the match.
        "treatments": [
            _conventional(
                code="6851", name="Methotrexate (conventional DMARD)",
                condition="M06.9", copay=25,
                step_name="Oral/subcutaneous methotrexate therapy",
            ),
            _conventional(
                code="6851", name="Methotrexate (conventional DMARD)",
                condition="L40.50", copay=25,
                step_name="Oral/subcutaneous methotrexate therapy",
            ),
            {
                "treatmentCode": "J3590",
                "treatmentName": "Secukinumab (Cosentyx) therapy",
                "condition": "M06.9",
                "tier": "specialty",
                "covered": True,
                "priorAuthRequired": True,
                "steps": _biologic_steps(
                    "LOADING_DOSE", "Loading dose (weeks 0-4)",
                    "Maintenance dosing (monthly, ongoing)", 0.2,
                ),
            },
            {
                "treatmentCode": "J0135",
                "treatmentName": "Adalimumab (Humira) therapy",
                "condition": "L40.50",
                "tier": "specialty",
                "covered": True,
                "priorAuthRequired": True,
                # The drug is funded; the pre-treatment screening panel is not. This is
                # the plan's restricted benefit — the coverage check returns
                # `restriction: "partial"`, the case still goes to clinical review
                # (the therapy must be justified even if only part of it is paid for),
                # and the outcome closes as `approved_restricted` with the member
                # carrying the cost of the excluded stage. Robert Chen's path.
                "steps": _biologic_steps(
                    "LOADING_DOSE", "Loading dose (weeks 0-1)",
                    "Maintenance dosing (biweekly, ongoing)", 0.2,
                    uncovered=("BASELINE_LABS",),
                ),
            },
        ],
        "effectiveDate": "2025-01-01",
        "renewalDate": "2027-01-01",
        "schemaVersion": "1.1",
        "createdAt": "2025-01-01T00:00:00Z",
        "updatedAt": "2026-07-27T00:00:00Z",
    },
    {
        "_id": "PLAN-HMO-SPEC-2290",
        "planId": "PLAN-HMO-SPEC-2290",
        "planName": "HMO Specialty Care 2290",
        "planType": "HMO",
        "network": "in_network_required",
        "jurisdiction": "NY",
        "eligibilityRules": {"requiresActiveStatus": True},
        "coverage": {
            "tiers": {
                "standard": {
                    "covered": True, "priorAuthRequired": False,
                    "coinsurance": None, "copay": 20, "deductible": 0,
                    "outOfPocketMax": None,
                },
                "specialty": {
                    "covered": True, "priorAuthRequired": True,
                    "coinsurance": 0.25, "copay": None, "deductible": 750,
                    "outOfPocketMax": 5000,
                },
            },
            "excludedServices": ["cosmetic", "experimental"],
        },
        "treatments": [
            _conventional(
                code="1298944",
                name="Azathioprine (conventional immunomodulator)",
                condition="K50.90", copay=20,
                step_name="Oral azathioprine therapy",
            ),
            {
                "treatmentCode": "J3357",
                "treatmentName": "Ustekinumab (Stelara) therapy",
                "condition": "K50.90",
                "tier": "specialty",
                "covered": True,
                "priorAuthRequired": True,
                # Ustekinumab induces with a weight-based IV dose rather than a
                # loading dose, so the middle step differs from the other biologics.
                "steps": _biologic_steps(
                    "INDUCTION_DOSE", "Weight-based IV induction dose",
                    "Maintenance dosing (every 8 weeks, ongoing)", 0.25,
                ),
            },
        ],
        "effectiveDate": "2025-01-01",
        "renewalDate": "2027-01-01",
        "schemaVersion": "1.1",
        "createdAt": "2025-01-01T00:00:00Z",
        "updatedAt": "2026-07-27T00:00:00Z",
    },
    # Standard-only plan: specialty tier NOT covered, and the specialty biologic is
    # explicitly listed as covered:false so the benefit denial is data-driven (not
    # merely inferred from the tier flag).
    {
        "_id": "PLAN-PPO-STD-1100",
        "planId": "PLAN-PPO-STD-1100",
        "planName": "PPO Standard Care 1100",
        "planType": "PPO",
        "network": "in_network_preferred",
        "jurisdiction": "multi_state",
        "eligibilityRules": {"requiresActiveStatus": True},
        "coverage": {
            "tiers": {
                "standard": {
                    "covered": True, "priorAuthRequired": False,
                    "coinsurance": None, "copay": 30, "deductible": 0,
                    "outOfPocketMax": None,
                },
                # priorAuthRequired is null, not false: an uncovered tier has no
                # prior-auth question to answer, and false would wrongly read as
                # "covered without prior auth".
                "specialty": {
                    "covered": False, "priorAuthRequired": None,
                    "coinsurance": None, "copay": None, "deductible": None,
                    "outOfPocketMax": None,
                },
            },
            "excludedServices": [
                "cosmetic", "experimental", "specialty_tier_biologics",
            ],
        },
        "treatments": [
            _conventional(
                code="6851", name="Methotrexate (conventional DMARD)",
                condition="M06.9", copay=30,
                step_name="Oral/subcutaneous methotrexate therapy",
            ),
            {
                "treatmentCode": "J3590",
                "treatmentName": "Secukinumab (Cosentyx) therapy",
                "condition": "M06.9",
                "tier": "specialty",
                "covered": False,
                "priorAuthRequired": None,
                # Steps are listed but unfunded, so a coverage check can say which
                # protocol was requested and that none of it is paid for.
                "steps": _biologic_steps(
                    "LOADING_DOSE", "Loading dose (weeks 0-4)",
                    "Maintenance dosing (monthly, ongoing)", None, covered=False,
                ),
            },
        ],
        "effectiveDate": "2025-01-01",
        "renewalDate": "2027-01-01",
        "schemaVersion": "1.1",
        "createdAt": "2025-01-01T00:00:00Z",
        "updatedAt": "2026-07-27T00:00:00Z",
    },
]

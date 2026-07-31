"""Plan documents — the benefit design an agent reads to answer coverage and
eligibility questions.

Per the official data model, benefits are embedded directly and coverage is
organized by tier (standard vs. specialty). Cost-share fields (coinsurance /
copay / deductible / outOfPocketMax) are modeled for realism but drive NO
adjudication math in the demo — the MVP demos the prior-authorization *decision*
(covered? eligible? prior auth required?), not claims cost-share.

`treatments[]` is the per-plan list of covered treatments and the protocol steps
the plan pays for (closes the datamodel.txt §3 TODO). A coverage check resolves a
treatment by `drug` + `condition` — matching how the agent names the considered
therapy — and falls back to tier-level coverage when a therapy has no explicit
treatment entry. `treatmentCode` (a J-code) also lines up with `claims.procedureCode`.
"""


def _biologic_steps(loading_label: str, maintenance_label: str, coinsurance):
    """Standard specialty-biologic protocol: screening -> loading -> maintenance."""
    return [
        {"stepCode": "BASELINE_LABS",
         "stepName": "Baseline labs and TB/infection screening",
         "covered": True, "coinsurance": coinsurance, "copay": None},
        {"stepCode": "LOADING_DOSE", "stepName": loading_label,
         "covered": True, "coinsurance": coinsurance, "copay": None},
        {"stepCode": "MAINTENANCE_DOSE", "stepName": maintenance_label,
         "covered": True, "coinsurance": coinsurance, "copay": None},
    ]


def _treatment(*, code, name, drug, rxnorm, condition, covered, coinsurance,
               loading, maintenance):
    return {
        "treatmentCode": code,
        "treatmentName": name,
        "drug": drug,
        "rxnorm": rxnorm,
        "condition": condition,
        "tier": "specialty",
        "covered": covered,
        "priorAuthRequired": True,
        # A non-covered treatment carries no funded steps.
        "steps": _biologic_steps(loading, maintenance, coinsurance) if covered else [],
    }


PLANS = [
    {
        "_id": "PLAN-PPO-7731",
        "planName": "PPO Specialty Care 7731",
        "planType": "PPO",
        "network": "in_network_preferred",
        "jurisdiction": "OH",
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
                    "coinsurance": 0.20, "copay": None, "deductible": 500,
                    "outOfPocketMax": 4000,
                },
            },
            "excludedServices": ["cosmetic", "experimental"],
        },
        "treatments": [
            _treatment(
                code="J3590", name="Secukinumab (Cosentyx) therapy",
                drug="secukinumab", rxnorm="1656663", condition="M06.9",
                covered=True, coinsurance=0.20,
                loading="Loading dose (weeks 0-4)",
                maintenance="Maintenance dosing (monthly, ongoing)",
            ),
            _treatment(
                code="J0135", name="Adalimumab (Humira) therapy",
                drug="adalimumab", rxnorm="327361", condition="L40.50",
                covered=True, coinsurance=0.20,
                loading="Loading dose (weeks 0-1)",
                maintenance="Maintenance dosing (biweekly, ongoing)",
            ),
        ],
        "schemaVersion": "1.1",
    },
    {
        "_id": "PLAN-HMO-4420",
        "planName": "HMO Specialty Care 4420",
        "planType": "HMO",
        "network": "in_network_required",
        "jurisdiction": "OH",
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
            _treatment(
                code="J3357", name="Ustekinumab (Stelara) therapy",
                drug="ustekinumab", rxnorm="1364454", condition="K50.90",
                covered=True, coinsurance=0.25,
                loading="Loading dose (week 0, weight-based IV induction)",
                maintenance="Maintenance dosing (every 8 weeks, ongoing)",
            ),
        ],
        "schemaVersion": "1.1",
    },
    # Standard-only plan: specialty tier NOT covered, and the specialty biologic is
    # explicitly listed as covered:false so the benefit denial is data-driven (not
    # merely inferred from the tier flag).
    {
        "_id": "PLAN-HMO-STD-3300",
        "planName": "HMO Standard 3300",
        "planType": "HMO",
        "network": "in_network_required",
        "jurisdiction": "OH",
        "eligibilityRules": {"requiresActiveStatus": True},
        "coverage": {
            "tiers": {
                "standard": {
                    "covered": True, "priorAuthRequired": False,
                    "coinsurance": None, "copay": 30, "deductible": 0,
                    "outOfPocketMax": None,
                },
                "specialty": {
                    "covered": False, "priorAuthRequired": True,
                    "coinsurance": None, "copay": None, "deductible": None,
                    "outOfPocketMax": None,
                },
            },
            "excludedServices": ["cosmetic", "experimental", "specialty_biologics"],
        },
        "treatments": [
            _treatment(
                code="J3590", name="Secukinumab (Cosentyx) therapy",
                drug="secukinumab", rxnorm="1656663", condition="M06.9",
                covered=False, coinsurance=None,
                loading="Loading dose (weeks 0-4)",
                maintenance="Maintenance dosing (monthly, ongoing)",
            ),
        ],
        "schemaVersion": "1.1",
    },
]

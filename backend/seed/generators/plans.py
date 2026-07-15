"""Plan documents — the benefit design an agent reads to answer coverage and
eligibility questions.

No dollar amounts: the MVP demos the prior-authorization *decision* (covered?
eligible? prior auth required?), not claims adjudication / cost-share. So a plan
carries coverage rules and eligibility rules, but no deductibles or copays.

`coverage.tiers` is the key structure: for each tier the plan says whether it is
covered at all and whether prior authorization is required. A biologic classifies
(via the guideline) to the `specialty` tier, so a plan that does not cover
`specialty` cannot cover that therapy — that is a *benefit* denial, distinct from
a medical-necessity denial.
"""

PLANS = [
    {
        "_id": "PLAN-PPO-7731",
        "name": "PPO Specialty Care 7731",
        "type": "PPO",
        "network": "open",
        "eligibility_rules": {"requires_active_status": True},
        "coverage": {
            "tiers": {
                "standard": {"covered": True, "prior_auth_required": False},
                "specialty": {"covered": True, "prior_auth_required": True},
            },
            "excluded_services": [],
        },
    },
    {
        "_id": "PLAN-HMO-4420",
        "name": "HMO Specialty Care 4420",
        "type": "HMO",
        "network": "in_network_required",
        "eligibility_rules": {"requires_active_status": True},
        "coverage": {
            "tiers": {
                "standard": {"covered": True, "prior_auth_required": False},
                "specialty": {"covered": True, "prior_auth_required": True},
            },
            "excluded_services": [],
        },
    },
    # Standard-only plan: specialty tier is NOT covered. A member on this plan who
    # needs a specialty biologic hits a benefit (coverage) denial, regardless of
    # whether their clinical step-therapy criteria are satisfied.
    {
        "_id": "PLAN-HMO-STD-3300",
        "name": "HMO Standard 3300",
        "type": "HMO",
        "network": "in_network_required",
        "eligibility_rules": {"requires_active_status": True},
        "coverage": {
            "tiers": {
                "standard": {"covered": True, "prior_auth_required": False},
                "specialty": {"covered": False, "prior_auth_required": True},
            },
            "excluded_services": [],
        },
    },
]

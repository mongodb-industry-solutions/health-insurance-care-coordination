"""Plan documents. Schema is intentionally light for now (eligibility rules and
coverage tiers) and will grow as coverage logic develops."""

PLANS = [
    {
        "_id": "PLAN-PPO-7731",
        "name": "PPO Specialty Care 7731",
        "type": "PPO",
        "eligibility": {"status": "active", "effective_date": "2025-01-01"},
        "coverage_tiers": ["standard", "specialty"],
    },
    {
        "_id": "PLAN-HMO-4420",
        "name": "HMO Specialty Care 4420",
        "type": "HMO",
        "eligibility": {"status": "active", "effective_date": "2025-01-01"},
        "coverage_tiers": ["standard", "specialty"],
    },
]

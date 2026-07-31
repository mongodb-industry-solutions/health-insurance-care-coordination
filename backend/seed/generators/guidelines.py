"""Guideline documents (taxonomic + procedural memory).

Guidelines are shared reference data: many members point at the same guideline
version. They are defined here as whole documents rather than generated per
member, because they represent plan-level clinical policy, not member facts.
"""

GUIDELINES = [
    {
        "_id": "CMG-RA-2026.3",
        "condition": "M06.9",
        "effective_date": "2026-06-01",
        # TAXONOMIC memory: reason by category, not exact prior match
        "classification": {
            "secukinumab": {
                "class": "biologic",
                "tier": "specialty",
                "prior_auth_required": True,
            }
        },
        # PROCEDURAL memory: the gates an agent applies at runtime
        "criteria": {
            "step_therapy": {"drug": "Methotrexate", "min_months": 6},
            "coverage_tier": "specialty",
        },
        "confidence_threshold": 0.90,
    },
    {
        "_id": "CMG-PSA-2026.1",
        "condition": "L40.50",
        "effective_date": "2026-01-01",
        "classification": {
            "adalimumab": {
                "class": "biologic",
                "tier": "specialty",
                "prior_auth_required": True,
            }
        },
        "criteria": {
            "step_therapy": {"drug": "Methotrexate", "min_months": 6},
            "coverage_tier": "specialty",
        },
        "confidence_threshold": 0.90,
    },
    {
        "_id": "CMG-IBD-2026.2",
        "condition": "K50.90",
        "effective_date": "2026-03-01",
        "classification": {
            "ustekinumab": {
                "class": "biologic",
                "tier": "specialty",
                "prior_auth_required": True,
            }
        },
        "criteria": {
            "step_therapy": {"drug": "Azathioprine", "min_months": 6},
            "coverage_tier": "specialty",
        },
        "confidence_threshold": 0.92,
    },
]

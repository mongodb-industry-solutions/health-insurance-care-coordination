"""Canonical collection names for the care-coordination data model.

One database (`insurance_hc_agentic_care_layer`), six collections. Keeping the
names here means repositories and seed code never hard-code strings.
"""


class Collections:
    MEMBERS = "members"
    AUTHORIZATIONS = "authorizations"
    CLAIMS = "claims"
    GUIDELINES = "guidelines"
    AUDIT_LOG = "audit_log"
    PLANS = "plans"

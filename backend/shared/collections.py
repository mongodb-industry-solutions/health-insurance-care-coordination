"""Canonical collection names for the care-coordination data model.

One database (`insurance_hc_agentic_care_layer`). The official data model has
five business objects — Member, Policy, Plan, Claim, Audit Log — plus the
member-facing `notifications` collection (outside the formal model) and
`guidelines` reference data.

Keeping the names here means repositories and seed code never hard-code strings.

Note on `AUDIT_LOG`: in the official model the Audit Log IS the regulator-ready
decision trace (decisionType PRIOR_AUTHORIZATION, with a memory-typed `steps[]`
array, an `outcome`, and a `review` block). It replaced the former standalone
`authorizations` collection AND the former append-only per-read event trail —
prior-authorization decisions now live here as trace documents.
"""


class Collections:
    MEMBERS = "members"
    POLICIES = "policies"
    PLANS = "plans"
    CLAIMS = "claims"
    # Decision-trace store (regulator-ready). Prior-authorization decisions are
    # documents here; there is no separate `authorizations` collection.
    AUDIT_LOG = "audit_log"
    GUIDELINES = "guidelines"
    NOTIFICATIONS = "notifications"

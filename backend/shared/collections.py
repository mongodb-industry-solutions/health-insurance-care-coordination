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

The collection is named `audit_log`, matching the object's name in the data model
and the database that holds the seeded traces. It was briefly mapped to
`decision_traces`, which left the backend reading and writing an entirely separate
collection from the one holding the real data — the seeded member traces were
invisible to every endpoint, and runtime writes accumulated somewhere nothing read
from. If a `decision_traces` collection still exists on a cluster, it is that
orphan and holds no canonical data.
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

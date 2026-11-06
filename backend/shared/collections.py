"""Canonical collection names, one class per database.

The data model is split across two databases (see `db/mdb.py`), and which database a
collection lives in is the fact that matters most, so each database has its own class.
Keeping the names here means repositories and seed code never hard-code strings.

`Collections` is the **insurance** database. `ClinicalCollections` is the **clinical**
database. `AUDIT_LOG` is the one object both agents touch: the shared authorization trace,
an envelope held in the insurance database. It carries no step text and no clinical or
insurance detail; the text lives in `ADMIN_REASONING` (insurance) and `CLINICAL_REASONING`
(clinical), referenced from the trace's `steps[].detailRef`.

The collection is named `audit_log`, matching the data model. It was once mapped to
`decision_traces`, which left the backend reading and writing a different collection from
the one holding the real data. If a `decision_traces` collection still exists on a
cluster, it is that orphan and holds no canonical data.
"""


class Collections:
    """The insurance database."""

    MEMBERS = "members"
    POLICIES = "policies"
    PLANS = "plans"
    CLAIMS = "claims"
    AUDIT_LOG = "audit_log"
    ADMIN_REASONING = "admin_reasoning"


class ClinicalCollections:
    """The clinical database."""

    CLINICAL_PROFILES = "clinical_profiles"
    DISPENSE_HISTORY = "dispense_history"
    GUIDELINES = "guidelines"
    CLINICAL_REASONING = "clinical_reasoning"

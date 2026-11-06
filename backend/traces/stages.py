"""The workflow stage machine, as the agents write it onto the trace.

    OPENED -> ADMIN_CLEARED -> (care agent) CLINICAL_RECOMMENDED -> ROUTED -> ESCALATED / CLOSED
       \\__________ administrative denial ___________________________________/ CLOSED

`workflow.stage` and `workflow.nextActor` say whose turn it is. The agents make every
transition up to ESCALATED, each a compare-and-set on the stage; the backend only reads them,
and makes the one transition a person makes (a medical director closing an ESCALATED case).
These names must match the agents' (`trace.py` in each agent package); the cross-agent
test in `tests/` runs the real agent code against them.
"""

STAGE_OPENED = "OPENED"
STAGE_ADMIN_CLEARED = "ADMIN_CLEARED"
STAGE_CLINICAL_RECOMMENDED = "CLINICAL_RECOMMENDED"
STAGE_ROUTED = "ROUTED"
STAGE_ESCALATED = "ESCALATED"
STAGE_CLOSED = "CLOSED"

ACTOR_INSURANCE = "insurance"
ACTOR_CARE = "care_coordination"
ACTOR_DIRECTOR = "medical_director"
ACTOR_NONE = "none"

APPROVAL_DECISIONS = ("approved", "approved_restricted")

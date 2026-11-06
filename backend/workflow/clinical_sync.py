"""The clinical sync: what a case's progress changes on the clinical record.

The Insurance Agent used to flip the member's pending action and write `approved_therapy`
straight into the combined member document. The agent now works in the insurance database
only, so those writes crossed the data boundary and nobody did them. The backend, the one
component allowed to hold both databases, does them here, derived from the trace.

| Trace                                | Clinical database                                       |
|--------------------------------------|---------------------------------------------------------|
| exists                               | action linked to the trace (`linkedAuditTraceId`)       |
| ESCALATED                            | action stays `in_progress` ("awaiting medical director") |
| CLOSED, any decision                 | action `resolved`                                       |
| CLOSED, approved / approved_restricted | `current_care_plan.approved_therapy` set, `considering_therapy` cleared |

Every step is idempotent and keyed on the trace, so a retried turn, a second call after a
director's decision, or two overlapping runs cannot double-apply anything. `sync_case` reads
the trace and brings the clinical record in line with it, so it can be called after any turn.
"""

import logging

from clinical.profiles.service import ProfileService
from traces.stages import APPROVAL_DECISIONS, STAGE_CLOSED

logger = logging.getLogger(__name__)


class ClinicalSync:
    def __init__(self, profiles: ProfileService):
        self.profiles = profiles

    def sync_case(self, trace: dict) -> dict:
        """Bring the clinical record in line with `trace`. Returns what changed."""
        changed = {"linked": False, "approved_therapy": False, "resolved": False}
        if not trace:
            return changed

        member_id = trace.get("subjectRef")
        request = trace.get("request") or {}
        action_id = request.get("actionId")
        if not member_id or not action_id:
            return changed

        trace_id = trace.get("traceId")
        changed["linked"] = self.profiles.link_trace(member_id, action_id, trace_id)

        closed = (trace.get("workflow") or {}).get("stage") == STAGE_CLOSED or bool(
            (trace.get("review") or {}).get("closedBy")
        )
        if not closed:
            return changed

        decision = (trace.get("outcome") or {}).get("decision")
        if decision in APPROVAL_DECISIONS:
            changed["approved_therapy"] = self.profiles.mark_approved_therapy(
                member_id, request.get("requestedService")
            )
        changed["resolved"] = self.profiles.resolve_action(member_id, action_id)
        return changed

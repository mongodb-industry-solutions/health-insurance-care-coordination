"""Traces for people: the envelope with each step's text joined back on.

The shared trace holds only an envelope for each step, and the text lives in the author's own
database, referenced by `detailRef`: the Insurance Agent's in `admin_reasoning`, the
Care-Coordination Agent's in `clinical_reasoning`. Joining them is what a regulator or a
medical director needs to see, and only the backend may do it.
"""

from clinical.reasoning.repository import ClinicalReasoningRepository
from insurance.reasoning.repository import AdminReasoningRepository
from traces.service import TraceService

DOMAIN_ADMINISTRATIVE = "administrative"
DOMAIN_CLINICAL = "clinical"


class TraceView:
    def __init__(
        self,
        traces: TraceService,
        admin_reasoning: AdminReasoningRepository,
        clinical_reasoning: ClinicalReasoningRepository,
    ):
        self.traces = traces
        self.admin_reasoning = admin_reasoning
        self.clinical_reasoning = clinical_reasoning

    def hydrate_many(self, traces: list) -> list:
        """Each trace with `steps[].detail` filled in from the right database, in one
        lookup per database."""
        ids = [t["traceId"] for t in traces]
        admin = self.admin_reasoning.details_for(ids)
        clinical = self.clinical_reasoning.details_for(ids)

        out = []
        for trace in traces:
            trace = dict(trace)
            steps = []
            for step in trace.get("steps") or []:
                step = dict(step)
                key = (trace["traceId"], step.get("stepId"))
                if step.get("domain") == DOMAIN_ADMINISTRATIVE:
                    step["detail"] = admin.get(key)
                elif step.get("domain") == DOMAIN_CLINICAL:
                    step["detail"] = clinical.get(key)
                steps.append(step)
            trace["steps"] = steps
            # Legacy alias, so the frontend's existing presenters keep working.
            trace["requested_service"] = (trace.get("request") or {}).get("requestedService")
            out.append(trace)
        return out

    def get_trace(self, trace_id: str):
        trace = self.traces.get_trace(trace_id)
        return self.hydrate_many([trace])[0] if trace else None

    def get_member_traces(self, member_id: str) -> list:
        return self.hydrate_many(self.traces.get_member_traces(member_id))

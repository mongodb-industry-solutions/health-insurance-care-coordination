"""The medical director's queue and the brief each case carries.

The Insurance Agent cannot write a brief that contains clinical detail, because it cannot see
any, and the Care-Coordination Agent cannot see the insurance facts. So nobody writes one
when a case is escalated: it is assembled here, at read time, from both databases. That also
means a brief is never stale and never says more than the records do.
"""

from typing import Optional

from traces.service import TraceService

from .members import MemberView
from .traces import TraceView

_EMPTY = "not recorded"


def _line(label: str, value) -> str:
    return f"{label}: {value if value not in (None, '') else _EMPTY}"


class ReviewView:
    def __init__(self, traces: TraceService, trace_view: TraceView, members: MemberView):
        self.traces = traces
        self.trace_view = trace_view
        self.members = members

    # ------------------------------------------------------------------------- brief

    def brief(self, trace: dict, member: Optional[dict]) -> dict:
        """The case as a physician needs it to decide without re-reading the record.

        `trace` is a hydrated trace (step text filled in); `member` the composed member.
        Returns `{"text": ..., "facts": {...}}`: the text for display, the facts for code.
        """
        member = member or {}
        request = trace.get("request") or {}
        outcome = trace.get("outcome") or {}
        gates = trace.get("administrativeGates") or {}
        audit = trace.get("audit") or {}
        eligibility = member.get("eligibility") or {}
        plan = member.get("current_care_plan") or {}

        order = next(
            (
                a for a in member.get("pendingActions") or []
                if a.get("actionId") == request.get("actionId")
                or a.get("linkedAuditTraceId") == trace.get("traceId")
            ),
            {},
        )
        provider = (plan.get("managing_provider") or {}).get("name") or order.get("raisedBy")

        facts = {
            "member_name": f"{member.get('firstName', '')} {member.get('lastName', '')}".strip() or None,
            "requested_service": request.get("requestedService"),
            "diagnosis_code": order.get("relatedDiagnosisCode"),
            "referring_physician": provider,
            "eligibility": eligibility.get("status"),
            "eligibility_gate": gates.get("eligibility"),
            "coverage_gate": gates.get("coverage"),
            "coverage_restriction": gates.get("coverageRestriction"),
            "recommendation": outcome.get("decision"),
            "confidence": outcome.get("confidence"),
            "confidence_threshold": outcome.get("confidenceThreshold"),
            "guideline_ref": outcome.get("guidelineRef"),
            "escalation_reason": audit.get("reviewRequiredReason"),
        }

        lines = [
            _line("Member", f"{facts['member_name']} ({trace.get('subjectRef')})"),
            _line("Requested treatment", facts["requested_service"]),
            _line("Diagnosis", facts["diagnosis_code"]),
            _line("Referring physician", facts["referring_physician"]),
            _line("Eligibility", f"{facts['eligibility']} (gate: {facts['eligibility_gate'] or _EMPTY})"),
            _line(
                "Coverage",
                f"{facts['coverage_gate'] or _EMPTY}, restriction {facts['coverage_restriction'] or _EMPTY}",
            ),
            "",
            "Reasoning on the record:",
        ]
        for step in trace.get("steps") or []:
            who = "insurance" if step.get("domain") == "administrative" else "clinical"
            text = step.get("detail") or "(no text on file)"
            lines.append(f"  [{who}] {step.get('name')}: {text}")
        lines += [
            "",
            _line(
                "Recommendation",
                f"{facts['recommendation']} (confidence {facts['confidence']}, "
                f"guideline threshold {facts['confidence_threshold']})",
            ),
            _line("Rationale", outcome.get("rationale")),
            _line("Why this needs you", facts["escalation_reason"]),
        ]
        return {"text": "\n".join(lines), "facts": facts}

    # ------------------------------------------------------------------------- queue

    def pending_review(self) -> dict:
        """Every case waiting on a medical director, with its assembled brief."""
        traces = self.trace_view.hydrate_many(self.traces.pending_human_review())
        queue = []
        for trace in traces:
            member = self.members.compose(trace.get("subjectRef"))
            brief = self.brief(trace, member)
            outcome = trace.get("outcome") or {}
            queue.append(
                {
                    "trace_id": trace.get("traceId"),
                    "member_id": trace.get("subjectRef"),
                    "member_name": brief["facts"]["member_name"],
                    "requested_service": (trace.get("request") or {}).get("requestedService"),
                    "agent_recommendation": outcome.get("decision"),
                    "agent_confidence": outcome.get("confidence"),
                    "escalation_reason": (trace.get("audit") or {}).get("reviewRequiredReason"),
                    # Assembled here, not stored on the trace.
                    "case_brief": brief["text"],
                    "brief": brief["facts"],
                    "coverage_restriction": brief["facts"]["coverage_restriction"],
                    "escalated_at": trace.get("updatedAt"),
                }
            )
        return {"count": len(queue), "cases": queue}

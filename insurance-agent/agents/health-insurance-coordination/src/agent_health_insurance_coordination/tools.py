"""Tool definitions for the health-insurance-coordination agent.

The catalog implements the Insurance Agent's half of the prior-authorization
process — Steps 0-2 (open the case, verify eligibility, check treatment coverage)
and Steps 8-9 (route the decision, close the case) — plus the bulk-retrieval
tools that back operational queues and dashboards. Steps 3-7 are clinical and
belong to the care-coordination agent; this agent reads their recommendation back
off the trace with `get_audit_trace`.

Data access is in-process: the tools call the vendored services in `data/` through
`data_access`, which holds the service instances and reproduces the response
shaping FastAPI's `response_model` used to do. Where a former route did more than
dispatch — wrapping a list, converting "" to None, translating a refusal — that
work is inlined here and noted, because deleting `routes.py` would otherwise have
dropped it silently.

The services signal a missing subject with `LookupError` and a *refused* request
with `ValueError`; the routes mapped these to 404 and 400. That second case is
load-bearing for this agent: the closure and claim-status guardrails express
bounded authority by refusing, so a refusal is a correct answer to be escalated,
never a transient failure to retry.
"""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from magenta_sdklanggraph import App
from pymongo.errors import PyMongoError

from . import data_access as da
from .data.audit.models import AuditTrace, RoutingDecisionResponse, TracesListResponse
from .data.claims.models import Claim, ClaimsList
from .data.members.models import (
    Member,
    MemberList,
    MemberSummaryResponse,
    PendingActionUpdateResponse,
    PendingAuthorizationsResponse,
)
from .data.plans.models import CoverageCheckResponse, Plan, PlansListResponse
from .data.policies.models import EligibilityCheckResponse, PoliciesListResponse, Policy

# Who this agent is on the audit trail. Matches `audit.triggeredBy`, so a trace
# attributes its steps in the same vocabulary it attributes its creation.
AGENT_IDENTITY = "system:insurance_agent"


def register(app: App) -> None:
    # =========================================================================
    # Scaffold / platform tools
    # =========================================================================

    @app.tool(is_local=False)
    def get_current_date(timezone_name: str = "UTC") -> str:
        """Return today's date in ISO 8601 format for an IANA timezone.

        Eligibility is decided against the date of service, so establish today's
        date here rather than assuming it.

        Args:
            timezone_name: IANA timezone name, e.g. America/New_York.
        """
        try:
            timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            return json.dumps(
                {
                    "error": f"Unknown timezone: {timezone_name}",
                    "hint": "Use an IANA timezone like America/Los_Angeles.",
                }
            )
        return json.dumps({"date": datetime.now(timezone).date().isoformat()})

    @app.tool(is_local=False)
    def save_user_info(info_key: str, info_value: str) -> str:
        """Save a piece of information about the user to long-term memory.

        Args:
            info_key: What the information represents, such as name, role, or preference.
            info_value: The value to store.
        """
        user_id = app.get_current_user_id()
        success = app.memory.save_semantic(
            text=f"User {info_key}: {info_value}",
            label=f"{user_id}_{info_key}",
            source="agent_health_insurance_coordination",
            metadata={"type": "user_info", "info_key": info_key},
            user_id=user_id,  # type: ignore[arg-type]
        )
        if success:
            return json.dumps({"status": "saved", "info_key": info_key})
        return json.dumps({"status": "error", "error": "Memory is not enabled"})

    @app.tool(is_local=False)
    def recall_user_info() -> str:
        """Recall stored information about the current user from long-term memory."""
        user_id = app.get_current_user_id()
        memory_context = app.memory.build_context(
            query=f"user profile and information for user {user_id}",
            user_id=user_id,  # type: ignore[arg-type]
        )
        if not memory_context:
            return json.dumps({"found": False, "message": "No stored information found"})
        return json.dumps({"found": True, "profile": memory_context})

    # =========================================================================
    # 1. Single-record lookup
    # =========================================================================

    @app.tool(is_local=False)
    def get_member_by_id(member_id: str) -> str:
        """Retrieve one member's full record by their memberId.

        The Member document is the operational foundation of every case: it
        carries `policyId`, `eligibility`, `clinical_history`,
        `current_care_plan` and `pendingActions[]`. Read `pendingActions[]` to
        pull the `actionId`, `relatedDiagnosisCode`, `proposedTreatment` and
        `raisedBy` that open a case (Step 0), and `policyId` to reach the policy
        the eligibility check runs against.

        Args:
            member_id: Member business key, e.g. MBR-2026-73305.
        """
        try:
            doc = da.members().get_member(member_id)
            if not doc:
                return da.error(f"Member {member_id} not found")
            return da.respond(Member, doc)
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to retrieve member: {str(e)}")

    @app.tool(is_local=False)
    def get_policy_by_id(policy_id: str) -> str:
        """Retrieve one policy by its policyId.

        Args:
            policy_id: Policy business key, e.g. POL-HP-2026-08841.
        """
        try:
            doc = da.policies().get_policy(policy_id)
            if not doc:
                return da.error(f"Policy {policy_id} not found")
            return da.respond(Policy, doc)
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to retrieve policy: {str(e)}")

    @app.tool(is_local=False)
    def get_plan_by_id(plan_id: str) -> str:
        """Retrieve one plan by its planId. This is the record the treatment-coverage check runs against.

        Args:
            plan_id: Plan business key, e.g. PLAN-PPO-SPEC-4471.
        """
        try:
            doc = da.plans().get_plan(plan_id)
            if not doc:
                return da.error(f"Plan {plan_id} not found")
            return da.respond(Plan, doc)
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to retrieve plan: {str(e)}")

    @app.tool(is_local=False)
    def get_audit_trace(trace_id: str) -> str:
        """Retrieve one decision trace by its traceId.

        Use this at Step 8 to read back the care-coordination agent's work before
        routing: `outcome.decision`, `outcome.confidence`, `outcome.rationale`,
        the memory-tagged `steps[]`, `contextSnapshot.guidelineRef`, and the
        current `audit.reviewRequired` / `review.*` state. Never restate a
        recommendation you have not read off the trace.

        Args:
            trace_id: Trace business key, e.g. TRC-2026-PA-00552.
        """
        try:
            doc = da.audit().get_trace(trace_id)
            if not doc:
                return da.error(f"Trace {trace_id} not found")
            return da.respond(AuditTrace, doc)
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to retrieve trace: {str(e)}")

    # =========================================================================
    # 2. Bulk / list retrieval
    #
    # The services return bare lists; the `{count, <name>}` envelope was added by
    # the routes and is part of the shape the model expects.
    # =========================================================================

    @app.tool(is_local=False)
    def list_all_members() -> str:
        """Return every member record in the system.

        A dashboard and roster view, not part of the single-case flow. When you
        are working one member's case, use `get_member_by_id` instead.
        """
        try:
            members = da.members().list_all_members()
            return da.respond(MemberList, {"count": len(members), "members": members})
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to list members: {str(e)}")

    @app.tool(is_local=False)
    def list_all_policies() -> str:
        """Return every policy record in the system.

        Operational visibility across the book of business — use
        `get_policy_by_id` for a single case.
        """
        try:
            policies = da.policies().list_all_policies()
            return da.respond(
                PoliciesListResponse, {"count": len(policies), "policies": policies}
            )
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to list policies: {str(e)}")

    @app.tool(is_local=False)
    def list_all_plans() -> str:
        """Return every plan record in the system, with their treatment catalogs.

        Use this to compare plan designs or answer "which plans cover X". For a
        single case, use `get_plan_by_id`.
        """
        try:
            plans = da.plans().list_all_plans()
            return da.respond(PlansListResponse, {"count": len(plans), "plans": plans})
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to list plans: {str(e)}")

    @app.tool(is_local=False)
    def list_all_claims() -> str:
        """Return every claim record in the system.

        Each claim carries `status`, `billedAmt` / `paidAmt` / `memberOwed`, the
        embedded `provider`, and `linkedAuditTraceId` when prior authorization
        applied. Use it for claim-queue and financial views.
        """
        try:
            claims = da.claims().list_all_claims()
            return da.respond(ClaimsList, {"count": len(claims), "claims": claims})
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to list claims: {str(e)}")

    @app.tool(is_local=False)
    def list_all_audit_traces() -> str:
        """Return every decision trace in the system.

        The compliance-wide view: every decision, its outcome, and whether it was
        agent-closed or routed to a medical director. For one case, use
        `get_audit_trace`.
        """
        try:
            traces = da.audit().list_all_traces()
            return da.respond(TracesListResponse, {"count": len(traces), "traces": traces})
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to list traces: {str(e)}")

    @app.tool(is_local=False)
    def list_pending_authorizations() -> str:
        """Return every member with a pending action still open — the work queue.

        A member appears here while any `pendingActions[]` entry is `pending`
        (never started) or `in_progress` (a case is open, possibly awaiting a
        medical director). Entries that are `resolved` are excluded. Use this to
        answer "what is waiting on us" without scanning every member.
        """
        try:
            members = da.members().list_pending_authorizations()
            return da.respond(
                PendingAuthorizationsResponse, {"count": len(members), "members": members}
            )
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to list pending authorizations: {str(e)}")

    # =========================================================================
    # 3. Eligibility & coverage checks
    # =========================================================================

    @app.tool(is_local=False)
    def verify_eligibility_on_date(policy_id: str, service_date: str = "") -> str:
        """Step 1 — the first administrative gate: was coverage active on the service date?

        Evaluates the policy's `status` together with its `effectivePeriod`
        against the date of service. Returns `{"eligible": bool, "reason": str |
        null, "policyId", "planId", "serviceDate"}`, where `reason` is a code
        such as `eligibility_lapsed` or `policy_cancelled`.

        If `eligible` is false the process STOPS here: no coverage lookup and no
        clinical review. Log the gate, then close the case yourself as an
        administrative eligibility denial.

        Args:
            policy_id: Policy business key, e.g. POL-HP-2026-08841.
            service_date: Date of service as YYYY-MM-DD. Defaults to today on the
                backend when omitted.
        """
        try:
            # An omitted date was previously an absent query param, arriving as None,
            # which the service reads as "today". Forwarding "" instead would be
            # parsed as a date and rejected.
            result = da.policies().verify_eligibility_on_date(
                policy_id, service_date=service_date or None
            )
        except ValueError as e:
            return da.refused(f"Eligibility check rejected: {str(e)}")
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to verify eligibility: {str(e)}")
        if not result:
            return da.error(f"Policy {policy_id} not found")
        return da.respond(EligibilityCheckResponse, result)

    @app.tool(is_local=False)
    def check_treatment_coverage(
        plan_id: str, condition: str, treatment_code: str = "", drug: str = ""
    ) -> str:
        """Step 2 — the second administrative gate: does the plan cover this treatment?

        Resolves the entry in the plan's `treatments[]` matching the treatment and
        `condition`, then evaluates its `steps[]`. Returns
        `{"covered": bool, "restriction": "none" | "partial" | null,
        "coveredSteps": [...], "uncoveredSteps": [...], "priorAuthRequired": bool
        | null, "reason": str | null, "matchedOn": str | null, "detail": str}`.

        Identify the treatment by `treatment_code` when you have it — that match is
        exact. Fall back to `drug` when the pending action names a therapy in prose
        but gives no code. `condition` is required either way: a treatment code is
        listed once per condition it applies to, so it is not unique on its own.

        Read the result exactly as follows:
        - `covered: false` — STOP. Clinical review never runs. Close the case
          yourself as an administrative benefit-exclusion denial.
        - `restriction: "partial"` — some stages are paid for and others are not.
          The case still goes to clinical review, but the eventual outcome must be
          `approved_restricted`, never a plain approval.
        - `covered: true` with `priorAuthRequired: true` — hand off to the
          care-coordination agent for clinical review.
        - `covered: true` with `priorAuthRequired: false` — no clinical review is
          needed; go straight to closure.

        Args:
            plan_id: Plan business key, e.g. PLAN-PPO-SPEC-4471.
            condition: ICD-10 code the treatment is requested for, e.g. M06.9.
            treatment_code: Drug/procedure code, e.g. J3590. Matches
                `Plan.treatments[].treatmentCode` directly. Preferred when known.
            drug: Therapy name, e.g. "secukinumab". Used only when no code is
                available; matched against the plan's treatment names.
        """
        try:
            # Both identifiers must be None when unset: the service picks its match
            # strategy on which one is present, and "" would read as a supplied value
            # that matches nothing.
            result = da.plans().check_treatment_coverage(
                plan_id,
                condition=condition,
                treatment_code=treatment_code or None,
                drug=drug or None,
            )
        except ValueError as e:
            return da.refused(f"Coverage check rejected: {str(e)}")
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to check treatment coverage: {str(e)}")
        if not result:
            return da.error(f"Plan {plan_id} not found")
        return da.respond(CoverageCheckResponse, result)

    # =========================================================================
    # 4. Claim management
    # =========================================================================

    @app.tool(is_local=False)
    def create_claim(
        member_id: str,
        procedure_code: str,
        procedure_desc: str,
        diagnosis_code: str,
        diagnosis_display: str,
        billed_amt: float,
        claim_type: str = "specialty_pharmacy",
        service_date: str = "",
    ) -> str:
        """Step 0 — open a new claim in `pending` status for the requested service.

        The backend fills `policyId` from the member's record and embeds the
        treating provider from `current_care_plan.managing_provider`, so the claim
        is consistent with the record it was raised from. Returns the new Claim
        including its generated `claimId` — keep that for Step 9.

        Nothing is decided here: the claim opens as a shell in `pending`.

        Args:
            member_id: Member business key, e.g. MBR-2026-73305.
            procedure_code: Procedure/service code; must match
                `Plan.treatments[].treatmentCode`, e.g. J3590.
            procedure_desc: Human-readable description of the procedure.
            diagnosis_code: Diagnosis supporting medical necessity; matches
                `Plan.treatments[].condition`, e.g. M06.9.
            diagnosis_display: Human-readable diagnosis description.
            billed_amt: Total amount billed by the provider.
            claim_type: specialty_pharmacy, pharmacy, medical or dental.
            service_date: Date of service as YYYY-MM-DD. Defaults to today.
        """
        try:
            claim = da.claims().create_claim(
                member_id=member_id,
                procedure_code=procedure_code,
                procedure_desc=procedure_desc,
                diagnosis_code=diagnosis_code,
                diagnosis_display=diagnosis_display,
                billed_amt=billed_amt,
                claim_type=claim_type,
                service_date=service_date or None,
            )
            return da.respond(Claim, claim)
        except LookupError:
            return da.error(f"Member {member_id} not found")
        except ValueError as e:
            return da.refused(f"Claim not created: {str(e)}")
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to create claim: {str(e)}")

    @app.tool(is_local=False)
    def update_claim_status(
        claim_id: str,
        status: str,
        paid_amt: float = 0.0,
        member_owed: float = 0.0,
        denial_reason: str = "",
        linked_audit_trace_id: str = "",
    ) -> str:
        """Step 9 — apply a reached decision to its claim.

        The backend refuses to mark a claim `approved`, `approved_restricted` or
        `paid` while its linked trace records a denial or is still pending: the
        claim and the trace must always tell the same story. A `400` here means
        that guardrail fired — resolve the trace first rather than retrying.

        Args:
            claim_id: Claim business key, e.g. CLM-IL-2026-00931.
            status: paid, approved, approved_restricted, denied or pending.
            paid_amt: Amount paid by the insurer.
            member_owed: Amount owed by the member — on a restricted approval this
                is the member's share of the uncovered stages.
            denial_reason: Reason code for a denial, e.g. eligibility_lapsed,
                benefit_exclusion_specialty_tier_not_covered, step_therapy_not_met.
            linked_audit_trace_id: Trace that decided this claim.
        """
        try:
            claim = da.claims().update_claim_status(
                claim_id=claim_id,
                status=status,
                paid_amt=paid_amt,
                member_owed=member_owed,
                denial_reason=denial_reason or None,
                linked_audit_trace_id=linked_audit_trace_id or None,
            )
            return da.respond(Claim, claim)
        except LookupError:
            return da.error(f"Claim {claim_id} not found")
        # The claim/trace consistency guardrail. A refusal is the correct answer:
        # resolve the trace, do not retry the status change.
        except ValueError as e:
            return da.refused(f"Claim update blocked: {str(e)}")
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to update claim: {str(e)}")

    # =========================================================================
    # 5. Audit trace management
    # =========================================================================

    @app.tool(is_local=False)
    def create_audit_trace(
        subject_ref: str,
        decision_type: str = "PRIOR_AUTHORIZATION",
        subject_type: str = "MEMBER",
        triggered_by: str = "system:insurance_agent",
        guideline_ref: str = "",
        input_facts: str = "",
    ) -> str:
        """Step 0 — open a new, empty decision trace for the case.

        Every decision leaves one, whether it ends in an approval, a denial or an
        escalation. The trace opens with an empty `steps[]`, ready to receive
        reasoning steps from this agent (Steps 1-2) and from the
        care-coordination agent (Steps 3-7). Returns the new trace including its
        generated `traceId` — attach that to the member's pending action with
        `update_pending_action`, and to the claim at Step 9.

        Args:
            subject_ref: The memberId (or claimId) this decision concerns.
            decision_type: PRIOR_AUTHORIZATION or CLAIM_ADJUDICATION.
            subject_type: MEMBER or CLAIM — must match what `subject_ref` holds.
            triggered_by: System or user that initiated the decision.
            guideline_ref: Clinical Guideline `_id` the case will be decided
                under, e.g. CMG-RA-2026.3. Leave empty if not yet known.
            input_facts: Short factual inputs assembled before reasoning began,
                separated by ";" — e.g. "policy ACTIVE on 2026-07-20;J3590 covered
                under specialty tier".
        """
        try:
            trace = da.audit().create_trace(
                subject_ref=subject_ref,
                decision_type=decision_type,
                subject_type=subject_type,
                triggered_by=triggered_by,
                guideline_ref=guideline_ref or None,
                input_facts=input_facts or None,
                # The route always passed this through; the tool has never exposed it.
                requested_service=None,
            )
            return da.respond(AuditTrace, trace)
        except LookupError:
            return da.error(f"Subject {subject_ref} not found")
        except ValueError as e:
            return da.refused(f"Trace not created: {str(e)}")
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to create trace: {str(e)}")

    @app.tool(is_local=False)
    def append_reasoning_step(
        trace_id: str,
        memory_type: str,
        name: str,
        detail: str,
        confidence: float,
        step_input: str = "",
        step_output: str = "",
    ) -> str:
        """Add one reasoning step to a trace's `steps[]`, tagged by memory type.

        Use this to log your own administrative checks: the eligibility gate
        (Step 1) and the coverage gate (Step 2), both of which are `semantic`
        recall of facts already on the record, or `taxonomic` when the finding
        turns on the plan's tier structure. Do NOT log clinical reasoning here —
        `episodic` and `procedural` steps belong to the care-coordination agent,
        and their presence on a trace is what marks a determination as clinical.

        `memory_type` is mandatory, and `detail` must be a plain-language sentence
        an auditor can read on its own — not a score.

        Args:
            trace_id: Trace business key.
            memory_type: semantic, taxonomic, episodic or procedural.
            name: Short label for the step, e.g. "eligibility_gate".
            detail: Plain-language explanation of the step's reasoning.
            confidence: Step-level confidence between 0 and 1.
            step_input: What the step consumed — a JSON object or short prose.
            step_output: What the step produced — a JSON object or short prose.
        """
        try:
            trace = da.audit().append_step(
                trace_id=trace_id,
                memory_type=memory_type,
                name=name,
                detail=detail,
                confidence=confidence,
                step_input=step_input or None,
                step_output=step_output or None,
                # Stamped here, not asked of the model: two agents write to one trace, and
                # the record has to be able to attribute every step. A value the LLM chose
                # would be a value it could get wrong.
                recorded_by=AGENT_IDENTITY,
            )
            return da.respond(AuditTrace, trace)
        except LookupError:
            return da.error(f"Trace {trace_id} not found")
        except ValueError as e:
            return da.refused(f"Step not appended: {str(e)}")
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to append reasoning step: {str(e)}")

    # =========================================================================
    # 6. Case routing & closure
    #
    # Every `ValueError` below is a bounded-authority refusal, not a malformed
    # request. Keeping the messages distinct is what stops the agent reading a
    # refusal as a transient failure and retrying a closure it may not make.
    # =========================================================================

    @app.tool(is_local=False)
    def route_decision(trace_id: str) -> str:
        """Step 8 — the bounded-authority checkpoint. Call this before any closure.

        The backend applies a fixed rule to the recommendation already on the
        trace, and returns `{"mayAgentClose": bool, "mustEscalate": bool,
        "escalationReason": str | null, "decision": str, "confidence": float,
        "confidenceThreshold": float, "clinicalReasoningPresent": bool}`:

        - a denial reached on clinical grounds must go to a medical director,
          at any confidence — this rule is absolute and has no exceptions;
        - any recommendation whose confidence is below the guideline's threshold
          must go to a medical director, whichever way it leans;
        - everything else the agent may close itself.

        The determination is the backend's, not yours. Never route a case on your
        own reading of the recommendation, and never close one this tool told you
        to escalate.

        Args:
            trace_id: Trace business key carrying the recommendation to route.
        """
        try:
            result = da.audit().route_decision(trace_id)
            return da.respond(RoutingDecisionResponse, result)
        except LookupError:
            return da.error(f"Trace {trace_id} not found")
        except ValueError as e:
            return da.refused(f"Cannot route this trace: {str(e)}")
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to route decision: {str(e)}")

    @app.tool(is_local=False)
    def close_administrative_determination(
        trace_id: str,
        reason: str,
        closed_by: str = "system:insurance_agent",
    ) -> str:
        """Close a case yourself when the outcome is factual and non-clinical.

        Only two reasons qualify, and both are gates that fired before clinical
        review ever ran:
        - `eligibility_lapsed` — the policy was not active on the date of service
        - `benefit_exclusion` — the plan does not cover the treatment or its tier

        The backend refuses this call if the trace carries clinical reasoning
        (any `episodic` or `procedural` step), or if the case has already been
        routed to a human. That refusal is the literal implementation of bounded
        authority — treat a `400` as a correct answer, not an obstacle, and
        escalate instead.

        Args:
            trace_id: Trace business key.
            reason: eligibility_lapsed or benefit_exclusion.
            closed_by: System identity closing the case.
        """
        try:
            trace = da.audit().close_administrative(
                trace_id=trace_id, reason=reason, closed_by=closed_by
            )
            return da.respond(AuditTrace, trace)
        except LookupError:
            return da.error(f"Trace {trace_id} not found")
        except ValueError as e:
            return da.refused(f"Closure refused: {str(e)}")
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to close case: {str(e)}")

    @app.tool(is_local=False)
    def close_authorization(
        trace_id: str,
        closed_by: str = "system:insurance_agent",
    ) -> str:
        """Close a case yourself when it is a clinically-supported approval.

        Valid only when the recommendation is `approved` or
        `approved_restricted` AND its confidence meets the guideline's
        `confidence_threshold` — exactly the cases `route_decision` reports as
        `mayAgentClose: true`. The backend re-checks both conditions and refuses
        the call otherwise; it will never let you close a denial through this
        path.

        Args:
            trace_id: Trace business key.
            closed_by: System identity closing the case.
        """
        try:
            trace = da.audit().close_authorization(trace_id=trace_id, closed_by=closed_by)
            return da.respond(AuditTrace, trace)
        except LookupError:
            return da.error(f"Trace {trace_id} not found")
        except ValueError as e:
            return da.refused(f"Closure refused: {str(e)}")
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to close authorization: {str(e)}")

    @app.tool(is_local=False)
    def escalate_to_human(
        trace_id: str,
        reason: str,
        case_brief: str = "",
        final_decision_maker: str = "medical_director",
    ) -> str:
        """Route a case to a medical director and mark it awaiting human closure.

        Call this — not optionally — whenever `route_decision` reports
        `mustEscalate: true`: a clinical denial at any confidence, or any
        recommendation below the guideline's threshold. Sets
        `audit.reviewRequired`, `review.routedToHuman` and
        `review.finalDecisionMaker`, and leaves `review.closedBy` null until a
        human closes it.

        The case does not end here — it pauses. The member's pending action stays
        `in_progress`, never `resolved`, so the frontend shows "awaiting medical
        director" rather than "not started".

        Args:
            trace_id: Trace business key.
            reason: Why review is required, e.g.
                clinical_denial_requires_physician_closure or
                confidence_below_guideline_threshold.
            case_brief: A brief complete enough for a physician to decide without
                re-reading the record: the member and requested treatment, the
                eligibility and coverage findings, the criteria applied, what the
                documented trial shows, and the recommendation with its confidence.
            final_decision_maker: Role responsible for closing the case.
        """
        try:
            trace = da.audit().escalate(
                trace_id=trace_id,
                reason=reason,
                case_brief=case_brief or None,
                final_decision_maker=final_decision_maker,
            )
            return da.respond(AuditTrace, trace)
        except LookupError:
            return da.error(f"Trace {trace_id} not found")
        except ValueError as e:
            return da.refused(f"Escalation rejected: {str(e)}")
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to escalate case: {str(e)}")

    # =========================================================================
    # 7. Member state updates
    # =========================================================================

    @app.tool(is_local=False)
    def update_pending_action(
        member_id: str,
        action_id: str,
        status: str,
        linked_audit_trace_id: str = "",
    ) -> str:
        """Advance a member's `pendingActions[]` entry through its lifecycle.

        This is what drives the "Start Process" trigger the member sees and its
        eventual resolution:
        - flip to `in_progress` at the very start of a case, before any reasoning
        - attach `linked_audit_trace_id` as soon as the trace exists
        - flip to `resolved` only once the case has actually closed

        An escalated case stays `in_progress` with its trace attached — never
        mark it `resolved` while a medical director still owes a decision.

        Args:
            member_id: Member business key.
            action_id: Pending-action business key, e.g. ACT-73305-01.
            status: pending, in_progress or resolved.
            linked_audit_trace_id: Trace opened for this action.
        """
        try:
            result = da.members().update_pending_action(
                member_id=member_id,
                action_id=action_id,
                status=status,
                linked_audit_trace_id=linked_audit_trace_id or None,
            )
            return da.respond(PendingActionUpdateResponse, result)
        except LookupError as e:
            return da.error(f"Pending action not found: {str(e)}")
        except ValueError as e:
            return da.refused(f"Pending action not updated: {str(e)}")
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to update pending action: {str(e)}")

    @app.tool(is_local=False)
    def update_member_summary(
        member_id: str,
        last_authorization_status: str,
        open_authorization_delta: int = 0,
    ) -> str:
        """Refresh a member's rolling `summary` once a case closes.

        Updates `summary.open_authorization_count`,
        `summary.last_authorization_status` and `summary.updated_at`, so the next
        request for this member starts from an already-informed record. Run it at
        the end of every closed decision — never leave the summary stale.

        Args:
            member_id: Member business key.
            last_authorization_status: Status of the decision just recorded —
                approved, approved_restricted, denied or pending.
            open_authorization_delta: +1 when a case opens, -1 when one closes.
        """
        try:
            # `open_authorization_delta` is accepted and deliberately ignored: the
            # counts are derived from the member's decision traces, not incremented.
            # Two code paths write these fields, and a delta assumes a single writer.
            result = da.members().recompute_summary(
                member_id, last_authorization_status=last_authorization_status
            )
            if not result:
                return da.error(f"Member {member_id} not found")
            return da.respond(MemberSummaryResponse, result)
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to update member summary: {str(e)}")

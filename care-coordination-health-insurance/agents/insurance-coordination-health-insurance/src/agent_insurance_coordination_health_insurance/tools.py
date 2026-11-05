"""Tool definitions for Insurance Coordination - Health Insurance.

The catalog implements the Insurance Agent's half of the prior-authorization process:
Steps 0-2 (open the case, verify eligibility, check treatment coverage, clear the gates)
and Steps 8-9 (route the decision, close or escalate it), plus the bulk-retrieval tools
behind operational queues. Steps 3-7 are clinical and belong to the care-coordination
agent; this agent reads its recommendation back off the trace.

This agent has no access to clinical data and works in one database. The only object it
shares with the care agent is the authorization trace.

The services signal a missing subject with `LookupError` and a *refused* request with
`ValueError`. The second is load-bearing: closure, escalation and claim-status express
bounded authority by refusing, so a refusal is a correct answer to report, never a
transient failure to retry.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pymongo.errors import PyMongoError

from . import data_access as da
from .data.models import (
    AuditTrace,
    Claim,
    ClaimsList,
    CoverageCheckResponse,
    EligibilityCheckResponse,
    Member,
    MemberList,
    MemberSummaryResponse,
    OpenCaseResponse,
    Plan,
    PlansListResponse,
    PoliciesListResponse,
    Policy,
    RoutingDecisionResponse,
    TracesListResponse,
)
from .data.trace import AGENT_IDENTITY

if TYPE_CHECKING:
    from agent_engine_sdk_langgraph import App


def register(app: App) -> None:
    # =========================================================================
    # Scaffold / platform tools
    # =========================================================================

    @app.tool()
    def get_current_date(timezone_name: str = "UTC") -> str:
        """Return today's date in ISO 8601 format for an IANA timezone."""
        try:
            timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            return json.dumps(
                {
                    "error": f"Unknown timezone: {timezone_name}",
                    "hint": "Use an IANA timezone like America/Los_Angeles.",
                }
            )
        return datetime.now(timezone).date().isoformat()

    @app.tool()
    def save_user_info(info_key: str, info_value: str) -> str:
        """Save a piece of information about the user to long-term memory.

        Args:
            info_key: What the information represents, such as name, location, or interests.
            info_value: The value to store.
        """
        user_id = app.get_current_user_id()
        result = app.memory.save_semantic(
            text=f"User {info_key}: {info_value}",
            label=f"{user_id}_{info_key}",
            source="agent_insurance_coordination_health_insurance",
            metadata={"type": "user_info", "info_key": info_key},
            user_id=user_id,
        )
        if getattr(result, "acknowledged", result):
            return json.dumps({"status": "saved", "info_key": info_key})
        return json.dumps({"status": "error", "error": "Memory is not enabled"})

    @app.tool()
    def recall_user_info() -> str:
        """Recall stored information about the current user from long-term memory."""
        user_id = app.get_current_user_id()
        context = app.memory.build_context(
            query=f"user profile and information for user {user_id}",
            user_id=user_id,
        )
        formatted = getattr(context, "formatted_context", context)
        memory_context = formatted if isinstance(formatted, str) else ""
        if not memory_context:
            return json.dumps({"found": False, "message": "No stored information found"})
        return json.dumps({"found": True, "profile": memory_context})

    # =========================================================================
    # 1. Single-record lookup
    # =========================================================================

    @app.tool()
    def get_member_by_id(member_id: str) -> str:
        """Retrieve one member's insurance record by their memberId.

        Returns identity, `policyId`, `eligibility` and the two-field `summary`
        (`open_authorization_count`, `last_authorization_status`). It holds no clinical
        information: history, notes, care plan and physician orders are not available to
        this agent. Read `policyId` to reach the policy the eligibility check runs against.

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

    @app.tool()
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

    @app.tool()
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

    @app.tool()
    def get_audit_trace(trace_id: str) -> str:
        """Retrieve one decision trace by its traceId.

        Use this at Step 8 to read back the care-coordination agent's work before
        routing: `workflow.stage`, `administrativeGates`, `outcome.decision`,
        `outcome.confidence`, `outcome.confidenceThreshold`, `outcome.rationale` and the
        `review.*` state. The trace is an envelope: the full text of YOUR steps is filled
        in on `steps[].detail`; the care agent's steps show only their name, memory type and
        confidence. Never restate a recommendation you have not read off the trace.

        Args:
            trace_id: Trace business key, e.g. TRC-2026-PA-00552.
        """
        try:
            trace = da.traces().get_trace(trace_id)
            if not trace:
                return da.error(f"Trace {trace_id} not found")
            return da.respond(AuditTrace, trace)
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to retrieve trace: {str(e)}")

    @app.tool()
    def find_open_case(member_id: str) -> str:
        """Find the member's open authorization case. Call this FIRST when resuming.

        The routing message carries only a member id, so this is how a later session finds
        the case: its `trace_id`, `stage`, `next_actor`, the `claim_id` opened for it and
        `next_step`, which says what to do at that stage. Use it before Phase B.

        If `has_open_case` is false there is nothing to resume: say so rather than
        inventing a case.

        Args:
            member_id: Member business key, e.g. MBR-2026-73305.
        """
        try:
            result = da.traces().find_open_case(member_id)
            if result is None:
                return da.error(f"Member {member_id} not found")
            return da.respond(OpenCaseResponse, result)
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to find open case: {str(e)}")

    # =========================================================================
    # 2. Bulk / list retrieval
    #
    # The services return bare lists; the `{count, <name>}` envelope is part of the shape
    # the model expects.
    # =========================================================================

    @app.tool()
    def list_all_members() -> str:
        """Return every member's insurance record.

        A dashboard and roster view, not part of the single-case flow. When you are working
        one member's case, use `get_member_by_id` instead.
        """
        try:
            members = da.members().list_all_members()
            return da.respond(MemberList, {"count": len(members), "members": members})
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to list members: {str(e)}")

    @app.tool()
    def list_all_policies() -> str:
        """Return every policy record in the system.

        Operational visibility across the book of business: use `get_policy_by_id` for a
        single case.
        """
        try:
            policies = da.policies().list_all_policies()
            return da.respond(PoliciesListResponse, {"count": len(policies), "policies": policies})
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to list policies: {str(e)}")

    @app.tool()
    def list_all_plans() -> str:
        """Return every plan record in the system, with their treatment catalogs.

        Use this to compare plan designs or answer "which plans cover X". For a single
        case, use `get_plan_by_id`.
        """
        try:
            plans = da.plans().list_all_plans()
            return da.respond(PlansListResponse, {"count": len(plans), "plans": plans})
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to list plans: {str(e)}")

    @app.tool()
    def list_all_claims() -> str:
        """Return every claim record in the system.

        Each claim carries `status`, `billedAmt` / `paidAmt` / `memberOwed`, the embedded
        `provider`, and `linkedAuditTraceId` when prior authorization applied. Use it for
        claim-queue and financial views.
        """
        try:
            claims = da.claims().list_all_claims()
            return da.respond(ClaimsList, {"count": len(claims), "claims": claims})
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to list claims: {str(e)}")

    @app.tool()
    def list_all_audit_traces() -> str:
        """Return every decision trace in the system, newest first.

        The compliance-wide view: every decision, its stage and outcome, and whether it was
        agent-closed or routed to a medical director. For one case, use `get_audit_trace`.
        """
        try:
            traces = da.traces().list_all_traces()
            return da.respond(TracesListResponse, {"count": len(traces), "traces": traces})
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to list traces: {str(e)}")

    # =========================================================================
    # 3. Eligibility & coverage checks
    # =========================================================================

    @app.tool()
    def verify_eligibility_on_date(policy_id: str, service_date: str = "") -> str:
        """Step 1: the first administrative gate. Was coverage active on the service date?

        Evaluates the policy's `status` together with its `effectivePeriod` against the
        date of service. Returns `{"eligible": bool, "reason": str | null, "policyId",
        "planId", "serviceDate", "confidence", "detail"}`, where `reason` is a code such as
        `eligibility_lapsed` or `policy_cancelled`.

        If `eligible` is false the process STOPS here: no coverage lookup and no clinical
        review. Log the gate, then close the case yourself as an administrative
        eligibility denial.

        Args:
            policy_id: Policy business key, e.g. POL-HP-2026-08841.
            service_date: Date of service as YYYY-MM-DD, from the opening message.
                Defaults to today when omitted.
        """
        try:
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

    @app.tool()
    def check_treatment_coverage(
        plan_id: str, condition: str, treatment_code: str = "", drug: str = ""
    ) -> str:
        """Step 2: the second administrative gate. Does the plan cover this treatment?

        Resolves the entry in the plan's `treatments[]` matching the treatment and
        `condition`, then evaluates its `steps[]`. Returns `{"covered": bool,
        "restriction": "none" | "partial" | null, "coveredSteps": [...], "uncoveredSteps":
        [...], "priorAuthRequired": bool | null, "reason": str | null, "matchedOn": str |
        null, "confidence", "detail"}`.

        `condition` is the diagnosis code from the opening message, exactly as given. It is
        required: a treatment is listed once per condition, so a wrong code can read a
        covered treatment as excluded or the other way round.

        Identify the treatment by `treatment_code` when you have it (an exact match). Fall
        back to `drug` when the message names a therapy but no code.

        Read the result exactly as follows:
        - `covered: false`: STOP. Clinical review never runs. Close the case yourself as an
          administrative benefit-exclusion denial.
        - `covered: true`: the case goes to clinical review, whatever `priorAuthRequired`
          says. With `restriction: "partial"` some stages are paid for and others are not,
          and `clear_administrative_gates` records that so the care agent knows the
          eventual outcome must be `approved_restricted`.

        Args:
            plan_id: Plan business key, e.g. PLAN-PPO-SPEC-4471.
            condition: ICD-10 diagnosis code from the opening message, e.g. M06.9.
            treatment_code: Drug/procedure code, e.g. J3590. Preferred when known.
            drug: Therapy name, e.g. "secukinumab". Used only when no code is available.
        """
        try:
            # Both identifiers must be None when unset: the service picks its match
            # strategy on which one is present, and "" would read as a supplied value.
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

    @app.tool()
    def create_claim(
        member_id: str,
        procedure_desc: str,
        diagnosis_code: str,
        diagnosis_display: str,
        billed_amt: float,
        provider_id: str,
        provider_name: str,
        provider_specialty: str = "",
        procedure_code: str = "",
        claim_type: str = "specialty_pharmacy",
        service_date: str = "",
        linked_audit_trace_id: str = "",
    ) -> str:
        """Open a new claim in `pending` status for the requested service.

        Take the diagnosis, treating provider, service date and amount from the opening
        message, exactly as given. This agent cannot look any of them up, and must never
        invent one. The backend fills `policyId` from the member's record. Pass
        `linked_audit_trace_id` so the claim is tied to its case from the start. Returns
        the new Claim including its generated `claimId`.

        Nothing is decided here: the claim opens as a shell in `pending`.

        Args:
            member_id: Member business key, e.g. MBR-2026-73305.
            procedure_desc: Human-readable description of the procedure.
            diagnosis_code: ICD-10 code supporting medical necessity, e.g. M06.9.
            diagnosis_display: Human-readable diagnosis description.
            billed_amt: Total amount billed. Use the amount in the opening message; if it
                gives none, pass 0 and say so in your reply.
            provider_id: The referring/treating provider's id, from the opening message.
            provider_name: The provider's name, from the opening message.
            provider_specialty: The provider's specialty, if the message gives one.
            procedure_code: Procedure/service code, e.g. J3590. Take it from the coverage
                check's `treatmentCode`. Leave empty when the case stopped at the
                eligibility gate and coverage was never checked.
            claim_type: specialty_pharmacy, pharmacy, medical or dental.
            service_date: Date of service as YYYY-MM-DD. Defaults to today.
            linked_audit_trace_id: The trace opened for this case.
        """
        try:
            claim = da.claims().create_claim(
                member_id=member_id,
                procedure_code=procedure_code or None,
                procedure_desc=procedure_desc,
                diagnosis_code=diagnosis_code,
                diagnosis_display=diagnosis_display,
                billed_amt=billed_amt,
                provider_id=provider_id,
                provider_name=provider_name,
                provider_specialty=provider_specialty or None,
                claim_type=claim_type,
                service_date=service_date or None,
                linked_audit_trace_id=linked_audit_trace_id or None,
            )
            return da.respond(Claim, claim)
        except LookupError:
            return da.error(f"Member {member_id} not found")
        except ValueError as e:
            return da.refused(f"Claim not created: {str(e)}")
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to create claim: {str(e)}")

    @app.tool()
    def update_claim_status(
        claim_id: str,
        status: str,
        paid_amt: float = 0.0,
        member_owed: float = 0.0,
        denial_reason: str = "",
        linked_audit_trace_id: str = "",
    ) -> str:
        """Step 9: apply a reached decision to its claim.

        The backend refuses to move a claim off `pending` until its linked trace is CLOSED
        and records the same decision: `approved`, `approved_restricted` or `paid` need an
        approval on the trace, `denied` needs a denial. A refusal here means that guardrail
        fired: close or escalate the trace first, do not retry.

        Args:
            claim_id: Claim business key, e.g. CLM-IL-2026-00931.
            status: paid, approved, approved_restricted, denied or pending.
            paid_amt: Amount paid by the insurer.
            member_owed: Amount owed by the member. On a restricted approval this is the
                member's share of the uncovered stages.
            denial_reason: Reason code for a denial, e.g. eligibility_lapsed,
                benefit_exclusion.
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
        except ValueError as e:
            return da.refused(f"Claim update blocked: {str(e)}")
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to update claim: {str(e)}")

    # =========================================================================
    # 5. Audit trace management
    # =========================================================================

    @app.tool()
    def create_audit_trace(
        subject_ref: str,
        requested_service: str,
        action_id: str,
        triggered_by: str = AGENT_IDENTITY,
    ) -> str:
        """Step 0: open a new decision trace for the case, at stage OPENED.

        Every decision leaves one, whether it ends in an approval, a denial or an
        escalation. The trace opens with an empty `steps[]` and the next actor set to you.
        It records the therapy and the action id only: no diagnosis code goes on the trace.
        Returns the new trace including its generated `traceId`: keep it for every later
        call and pass it to `create_claim`.

        A member who already has an open case for the same action is refused: use that
        trace instead of opening another.

        Args:
            subject_ref: The memberId this decision concerns.
            requested_service: The therapy named in the opening message, e.g. secukinumab.
            action_id: The action id named in the opening message, e.g. ACT-44109-01.
            triggered_by: System identity that initiated the decision.
        """
        try:
            trace = da.traces().create_trace(
                subject_ref=subject_ref,
                requested_service=requested_service,
                action_id=action_id,
                triggered_by=triggered_by,
            )
            return da.respond(AuditTrace, trace)
        except LookupError:
            return da.error(f"Member {subject_ref} not found")
        except ValueError as e:
            return da.refused(f"Trace not created: {str(e)}")
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to create trace: {str(e)}")

    @app.tool()
    def append_reasoning_step(
        trace_id: str,
        memory_type: str,
        name: str,
        detail: str,
        confidence: float,
        input_facts: str = "",
    ) -> str:
        """Record one administrative reasoning step on the trace.

        Use this to log your own two gates: `eligibility_gate` (Step 1, `semantic`) and
        `coverage_gate` (Step 2, `taxonomic`). Both are required before
        `clear_administrative_gates` or `close_administrative_determination` will proceed.
        `episodic` and `procedural` steps are clinical and belong to the care-coordination
        agent; they are refused here.

        `detail` must be a plain-language sentence an auditor can read on its own, not a
        score. It is stored in the insurance reasoning log and referenced from the trace.
        Allowed only while the case is at stage OPENED.

        Args:
            trace_id: Trace business key.
            memory_type: semantic or taxonomic.
            name: Short label for the step: "eligibility_gate" or "coverage_gate".
            detail: Plain-language explanation of the step's reasoning.
            confidence: Step-level confidence between 0 and 1, from the check.
            input_facts: Optional short facts the step used, separated by ";".
        """
        try:
            trace = da.traces().append_step(
                trace_id=trace_id,
                memory_type=memory_type,
                name=name,
                detail=detail,
                confidence=confidence,
                input_facts=input_facts or None,
                # Stamped here, not asked of the model: two agents write to one trace, and
                # the record has to be able to attribute every step.
                recorded_by=AGENT_IDENTITY,
            )
            return da.respond(AuditTrace, trace)
        except LookupError:
            return da.error(f"Trace {trace_id} not found")
        except ValueError as e:
            return da.refused(f"Step not appended: {str(e)}")
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to append reasoning step: {str(e)}")

    @app.tool()
    def clear_administrative_gates(
        trace_id: str,
        policy_id: str,
        plan_id: str,
        condition: str,
        treatment_code: str = "",
        drug: str = "",
        service_date: str = "",
    ) -> str:
        """End of Phase A: hand the case to the care-coordination agent.

        Call this once BOTH gate steps are recorded and both gates passed. It re-checks
        eligibility and coverage itself against the records, so pass the same policy, plan,
        diagnosis code, treatment and service date you used for the gates. If everything
        passes, the trace moves from OPENED to ADMIN_CLEARED with the care agent as next
        actor, and `administrativeGates` records what was found, including
        `coverageRestriction` (`none` or `partial`). Use `partial` as the signal that the
        eventual outcome must be `approved_restricted`.

        It refuses if a gate step is missing or either check fails. A refusal because a
        gate failed means close the case instead with
        `close_administrative_determination`; do not retry.

        Args:
            trace_id: Trace business key.
            policy_id: The member's policyId.
            plan_id: The policy's planId.
            condition: ICD-10 diagnosis code from the opening message.
            treatment_code: Drug/procedure code, if known.
            drug: Therapy name, used only when no code is available.
            service_date: Date of service as YYYY-MM-DD. Defaults to today.
        """
        try:
            trace = da.traces().clear_administrative_gates(
                trace_id=trace_id,
                policy_id=policy_id,
                plan_id=plan_id,
                condition=condition,
                treatment_code=treatment_code or None,
                drug=drug or None,
                service_date=service_date or None,
            )
            return da.respond(AuditTrace, trace)
        except LookupError:
            return da.error(f"Trace {trace_id} not found")
        except ValueError as e:
            return da.refused(f"Gates not cleared: {str(e)}")
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to clear administrative gates: {str(e)}")

    # =========================================================================
    # 6. Case routing & closure
    #
    # Every `ValueError` below is a bounded-authority refusal, not a malformed request.
    # Keeping the messages distinct is what stops the agent reading a refusal as a
    # transient failure and retrying a closure it may not make.
    # =========================================================================

    @app.tool()
    def route_decision(trace_id: str) -> str:
        """Step 8: the bounded-authority checkpoint. Call this before any closure.

        Allowed only at stage CLINICAL_RECOMMENDED. The backend applies a fixed rule to the
        recommendation on the trace and returns `{"mayAgentClose": bool, "mustEscalate":
        bool, "escalationReason": str | null, "decision", "confidence",
        "confidenceThreshold", "thresholdSource", "detail"}`:

        - a denial must go to a medical director, at any confidence. This rule is absolute;
        - a `pending` recommendation must go to a medical director;
        - any recommendation below `outcome.confidenceThreshold` must go to a medical
          director, whichever way it leans, and so must one with no threshold;
        - everything else the agent may close itself.

        The determination is the backend's, not yours. Never route a case on your own
        reading of the recommendation, and never close one this tool told you to escalate.

        Args:
            trace_id: Trace business key carrying the recommendation to route.
        """
        try:
            result = da.traces().route_decision(trace_id)
            return da.respond(RoutingDecisionResponse, result)
        except LookupError:
            return da.error(f"Trace {trace_id} not found")
        except ValueError as e:
            return da.refused(f"Cannot route this trace: {str(e)}")
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to route decision: {str(e)}")

    @app.tool()
    def close_administrative_determination(
        trace_id: str,
        reason: str,
        closed_by: str = AGENT_IDENTITY,
    ) -> str:
        """Close a case yourself when the outcome is factual and non-clinical.

        Allowed only at stage OPENED, and only two reasons qualify. Both are gates that
        fired before clinical review ever ran:
        - `eligibility_lapsed`: the policy was not active on the date of service
        - `benefit_exclusion`: the plan does not cover the treatment or its tier

        The gate step that found it (`eligibility_gate` or `coverage_gate`) must already be
        recorded on the trace. The backend refuses if the trace carries clinical reasoning
        or has already moved on. That refusal is the literal implementation of bounded
        authority: treat it as a correct answer, not an obstacle.

        Args:
            trace_id: Trace business key.
            reason: eligibility_lapsed or benefit_exclusion.
            closed_by: System identity closing the case.
        """
        try:
            trace = da.traces().close_administrative(
                trace_id=trace_id, reason=reason, closed_by=closed_by
            )
            return da.respond(AuditTrace, trace)
        except LookupError:
            return da.error(f"Trace {trace_id} not found")
        except ValueError as e:
            return da.refused(f"Closure refused: {str(e)}")
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to close case: {str(e)}")

    @app.tool()
    def close_authorization(
        trace_id: str,
        closed_by: str = AGENT_IDENTITY,
    ) -> str:
        """Close a case yourself when it is a clinically-supported approval.

        Allowed only at stage ROUTED, and only when the recommendation is `approved` or
        `approved_restricted` AND its confidence meets `outcome.confidenceThreshold`:
        exactly the cases `route_decision` reports as `mayAgentClose: true`. The backend
        re-checks both conditions and refuses the call otherwise; it will never let you
        close a denial through this path.

        Args:
            trace_id: Trace business key.
            closed_by: System identity closing the case.
        """
        try:
            trace = da.traces().close_authorization(trace_id=trace_id, closed_by=closed_by)
            return da.respond(AuditTrace, trace)
        except LookupError:
            return da.error(f"Trace {trace_id} not found")
        except ValueError as e:
            return da.refused(f"Closure refused: {str(e)}")
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to close authorization: {str(e)}")

    @app.tool()
    def escalate_to_human(trace_id: str, reason: str) -> str:
        """Route a case to a medical director and mark it awaiting human closure.

        Call this, not optionally, whenever `route_decision` reports `mustEscalate: true`.
        Allowed only at stage ROUTED. Moves the trace to ESCALATED with the medical
        director as next actor, sets `audit.reviewRequired` and `review.routedToHuman`, and
        leaves `review.closedBy` null until a human closes it. It records the reason only:
        the director's brief is assembled by the backend, so do not write one.

        The case does not end here, it pauses.

        Args:
            trace_id: Trace business key.
            reason: Why review is required: the `escalationReason` route_decision gave you,
                e.g. clinical_denial_requires_physician_closure or
                confidence_below_guideline_threshold.
        """
        try:
            trace = da.traces().escalate(trace_id=trace_id, reason=reason)
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

    @app.tool()
    def update_member_summary(member_id: str, last_authorization_status: str = "") -> str:
        """Refresh a member's rolling `summary` once a case closes.

        Updates `summary.open_authorization_count` and `summary.last_authorization_status`
        (and `summary.updated_at`) and nothing else, so the next request for this member
        starts from an already-informed record. Both are derived from the member's decision
        traces, so this is safe to run twice. Run it at the end of every closed decision.

        Args:
            member_id: Member business key.
            last_authorization_status: Optional override for the status of the decision just
                recorded: approved, approved_restricted, denied or pending. Normally omit it
                and let it be derived from the trace.
        """
        try:
            result = da.members().recompute_summary(
                member_id, last_authorization_status=last_authorization_status or None
            )
            if not result:
                return da.error(f"Member {member_id} not found")
            return da.respond(MemberSummaryResponse, result)
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to update member summary: {str(e)}")

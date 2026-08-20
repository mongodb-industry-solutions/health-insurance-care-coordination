"""Tool definitions for care coordination agent."""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from magenta_sdklanggraph import App
from pymongo.errors import PyMongoError

from . import data_access as da
from .data.audit.models import AuditTrace, MemberTracesResponse
from .data.claims.models import RefillGapsResponse
from .data.guidelines.models import (
    ClassificationResponse,
    GuidelineResponse,
    RecommendationResponse,
    StepTherapyResponse,
)
from .data.members.models import (
    ConceptMatchResponse,
    Member,
    MemberClinicalContext,
    OpenCaseResponse,
    TrialHistoryResponse,
)


# Who this agent is on the audit trail. Matches the `system:` vocabulary the trace
# already uses for `audit.triggeredBy` and `review.closedBy`.
AGENT_IDENTITY = "system:care_coordination_agent"


def register(app: App) -> None:
    @app.tool(is_local=False)
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
        return json.dumps({"date": datetime.now(timezone).date().isoformat()})

    @app.tool(is_local=False)
    def save_user_info(info_key: str, info_value: str) -> str:
        """Save a piece of information about the user to long-term memory.

        Args:
            info_key: What the information represents, such as name, location, or interests.
            info_value: The value to store.
        """
        user_id = app.get_current_user_id()
        success = app.memory.save_semantic(
            text=f"User {info_key}: {info_value}",
            label=f"{user_id}_{info_key}",
            source="agent_care_coordination",
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

    # --- Care Coordination Domain Tools ---
    #
    # These read and write MongoDB in-process through `data_access`, which holds the
    # service instances and reproduces the response shaping FastAPI's `response_model`
    # used to do. Where a former route did more than dispatch — reshaping a payload,
    # parsing an argument, applying a default — that work is inlined here and noted,
    # because deleting `routes.py` would otherwise have dropped it silently.

    @app.tool(is_local=False)
    def get_member_clinical_context(member_id: str) -> str:
        """Retrieve a member's clinical history and eligibility status.

        Returns diagnosis codes, active medications, treatment responses,
        and eligibility tier. This is the foundational context for authorization
        decisions.

        Args:
            member_id: The member's unique ID (e.g., MBR-2026-44109).
        """
        try:
            context = da.members().get_clinical_context(member_id)
            if not context:
                return da.error(f"Member {member_id} not found")
            return da.respond(MemberClinicalContext, context)
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to retrieve member context: {str(e)}")

    @app.tool(is_local=False)
    def get_open_case(member_id: str) -> str:
        """Read the member's open case — call this FIRST for any authorization request.

        The insurance agent opens a case by flipping the member's pending action to
        `in_progress` and attaching a trace id; it does not message this agent. This
        is how you pick that case up given nothing but a member id. Returns the
        therapy the referring physician proposed and the `trace_id` your reasoning
        steps belong on.

        Use `proposed_treatment` as the input to `match_clinical_concept`. Do NOT
        use `related_diagnosis_code` as though the diagnosis were established — it is
        the physician's own claim about which condition the drug treats, and
        confirming it independently is exactly what Step 3 is for. Compare the two
        afterwards if you like; a disagreement is worth reporting.

        If `has_open_case` is false there is nothing to process: say so rather than
        inventing a request.

        Args:
            member_id: The member's unique ID (e.g., MBR-2026-44109).
        """
        try:
            result = da.members().get_open_case(member_id)
            if result is None:
                return da.error(f"Member {member_id} not found")
            return da.respond(OpenCaseResponse, result)
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to retrieve open case: {str(e)}")

    @app.tool(is_local=False)
    def match_clinical_concept(member_id: str, requested_treatment: str) -> str:
        """Step 3 (semantic memory): confirm the requested therapy corresponds to a
        condition already documented on the member's record.

        The referring physician names a drug; the record carries ICD-10 codes.
        This bridges the two through the clinical guideline that classifies the
        drug, and returns a confidence-scored match plus the diagnosis code to
        carry into Step 4.

        Call this before `get_applicable_guideline` — this is what tells you which
        condition code to look the guideline up by. A `matched: false` result means
        the concept is unconfirmed: do not proceed as though the diagnosis is
        established, and let the low confidence carry through to Step 7.

        Args:
            member_id: The member's unique ID (e.g., MBR-2026-44109).
            requested_treatment: The therapy being requested. The bare drug name
                (e.g. "secukinumab") or the canonical service string
                (e.g. "biologic therapy - secukinumab") both work.
        """
        try:
            result = da.members().match_clinical_concept(
                member_id=member_id, requested_treatment=requested_treatment
            )
            if result is None:
                return da.error(f"Member {member_id} not found")
            return da.respond(ConceptMatchResponse, result)
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to match clinical concept: {str(e)}")

    @app.tool(is_local=False)
    def get_applicable_guideline(condition_code: str, member_id: str) -> str:
        """Retrieve the latest clinical guideline for a condition.

        Returns taxonomic classification and procedural criteria (step therapy
        requirements, coverage tier, confidence thresholds) that an agent uses
        to evaluate medical necessity.

        Args:
            condition_code: ICD-10 diagnosis code (e.g., M06.9 for rheumatoid arthritis).
            member_id: The member whose case this read is part of. Kept for call
                consistency across the pathway tools; the guideline read is not
                separately audited — the exact version consulted is recorded on the
                decision trace's contextSnapshot.guidelineRef when the case is processed.
        """
        try:
            guideline = da.guidelines().get_guideline_for_condition(condition_code)
            if not guideline:
                return da.error(f"No guideline found for condition {condition_code}")
            # The former route projected the stored document onto the response shape,
            # renaming `_id` to `guideline_id`. Returning the raw document instead
            # would hand the model an `_id` and no `guideline_id`.
            return da.respond(
                GuidelineResponse,
                {
                    "guideline_id": guideline.get("_id"),
                    "condition": guideline.get("condition"),
                    "effective_date": guideline.get("effective_date"),
                    "classification": guideline.get("classification"),
                    "criteria": guideline.get("criteria"),
                    "confidence_threshold": guideline.get("confidence_threshold"),
                },
            )
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to retrieve guideline: {str(e)}")

    @app.tool(is_local=False)
    def classify_treatment(condition_code: str, requested_treatment: str) -> str:
        """Step 4 (taxonomic memory): classify the requested treatment by category.

        Returns the treatment's class (e.g. biologic), coverage tier, whether prior
        authorization is required, and whether step-therapy criteria apply — plus the
        guideline's confidence threshold, which Step 7 is measured against.

        Call this after `match_clinical_concept`, using the diagnosis code it
        confirmed. A drug the guideline never enumerated is still classified from its
        category, but comes back with `inferred: true` and lower confidence — when
        that happens, say so in your assessment rather than presenting the tier as an
        established fact, and carry the reduced confidence into Step 7.

        Args:
            condition_code: ICD-10 diagnosis code confirmed in Step 3 (e.g. "M06.9").
            requested_treatment: The therapy being classified. The bare drug name
                ("secukinumab") or the canonical service string
                ("biologic therapy - secukinumab") both work.
        """
        try:
            result = da.guidelines().classify_treatment(
                condition_code=condition_code, requested_treatment=requested_treatment
            )
            if result is None:
                return da.error(f"No guideline found for condition {condition_code}")
            return da.respond(ClassificationResponse, result)
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to classify treatment: {str(e)}")

    @app.tool(is_local=False)
    def evaluate_step_therapy(
        condition_code: str, documented_drug: str, effective_trial_months: float
    ) -> str:
        """Step 6 (procedural memory): apply the guideline's step-therapy criteria.

        Answers the one question Step 6 exists to answer: does the trial on file meet
        the minimum the guideline requires? Returns `satisfied` true or false, and
        distinguishes a trial that is too short from one that is of the wrong drug.

        Pass `effective_trial_months` straight through from Step 5. It is the only
        duration this step accepts — not `documented_months`, which can lag a trial
        still being refilled, and not `longest_continuous_months`, which is correct
        only when a gap was left unexplained.

        A `satisfied: false` result does NOT end the process. Continue to Step 7: the
        recommendation still has to go through confidence aggregation and the
        escalation check, and you have no authority to close a clinical denial.

        Args:
            condition_code: ICD-10 diagnosis code confirmed in Step 3 (e.g. "M06.9").
            documented_drug: The prior therapy reviewed in Step 5 (e.g. "Methotrexate").
            effective_trial_months: `effective_trial_months` from review_trial_history.
        """
        try:
            result = da.guidelines().evaluate_step_therapy(
                condition_code=condition_code,
                documented_drug=documented_drug,
                # The service keeps its original parameter name; only the tool-facing
                # argument is renamed, to stop the model reaching for the record's
                # documented figure instead of the effective one.
                documented_months=effective_trial_months,
            )
            if result is None:
                return da.error(f"No guideline found for condition {condition_code}")
            return da.respond(StepTherapyResponse, result)
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to evaluate step therapy: {str(e)}")

    @app.tool(is_local=False)
    def review_trial_history(member_id: str, drug: str) -> str:
        """Step 5 (episodic memory): review the member's trial of the required therapy.

        Derives the effective trial duration from the member's actual pharmacy fills,
        flags any interruption in refill cadence, and reports whether a clinical note
        explains it.

        `effective_trial_months` is the answer, and the only figure Step 6 evaluates.
        The other durations are context, and each means something specific:

        * `documented_months` — what a clinician wrote on the record. An interim note
          goes stale while the member keeps refilling, so this is often SHORTER than
          the effective figure. Report both when they differ: a record understating a
          trial is how an adequate trial gets wrongly rejected. A `gap_reviewed` entry
          is excluded from it, so this agent's own writes never inflate it.
        * `longest_continuous_months` — the longest uninterrupted run of fills. This
          is credited INSTEAD of the full span only when a gap is unexplained. When
          the gap is explained it is not the trial duration, and reporting it as one
          understates the trial.
        * `observed_span_months` — first fill to last, gaps included.

        `gap_days` measures the interval between consecutive fills, NOT days the
        member was off the drug: one missed monthly refill shows up as a ~60-day
        interval. Read `approx_missed_fills` alongside it, and never describe a gap as
        time without medication.

        If `anomaly_detected` is true and `anomaly_explained` is false, only
        `longest_continuous_months` was credited and confidence is reduced — report
        that plainly and lean toward human review rather than crediting the full span.

        Args:
            member_id: The member's unique ID (e.g., MBR-2026-44109).
            drug: The required prior therapy to review, from Step 4's
                step_therapy_drug (e.g. "Methotrexate").
        """
        try:
            # `cadence_days` and `gap_factor` were route-level defaults, not service
            # defaults, and the tool never exposed them. Passing them explicitly keeps
            # the derived durations identical to what the HTTP path produced.
            result = da.members().review_trial_history(
                member_id=member_id, drug=drug, cadence_days=30, gap_factor=1.5
            )
            if result is None:
                return da.error(f"Member {member_id} not found")
            return da.respond(TrialHistoryResponse, result)
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to review trial history: {str(e)}")

    @app.tool(is_local=False)
    def detect_refill_gaps(member_id: str, drug: str = "") -> str:
        """Scan a member's refill cadence across drugs. Rarely needed in Step 5b.

        Returns any interval between consecutive fills that is longer than expected.
        `review_trial_history` already returns exactly this for the drug under review,
        in its `gaps` field — so during a case, read that instead. Reach for this only
        to look at a DIFFERENT drug, or with no drug filter to scan them all.

        `gap_days` is the interval between fills, NOT days the member was off the
        drug: one missed monthly refill reads as roughly 60 days. Report it together
        with `approx_missed_fills`, and never call it time without medication.

        Args:
            member_id: The member's unique ID.
            drug: Optional drug display name (e.g. "Methotrexate") to scope the check.
        """
        try:
            # An omitted drug was previously an absent query param, which arrived as
            # None. Forwarding "" instead would filter on the empty string and match
            # nothing.
            result = da.claims().detect_refill_gaps(member_id, drug=drug or None)
            return da.respond(RefillGapsResponse, result)
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to detect refill gaps: {str(e)}")

    @app.tool(is_local=False)
    def resolve_refill_gap(
        member_id: str,
        drug: str,
        effective_trial_months: float,
        conclusion: str,
        related_note: str = "",
    ) -> str:
        """Step 5b: record that a documented note explains a refill gap.

        Call this ONLY when you found a clinical note that genuinely accounts for the
        gap — a documented medication hold, not a discontinuation. Your `conclusion`
        is stored as a treatment_response on the member's record, which is what makes
        the full trial stand for this and any later case.

        Do NOT call it for an unexplained gap. There is nothing to record: only the
        longest uninterrupted run is credited, and the case leans to human review.
        Calling it anyway asserts an explanation you do not have.

        Call it once per drug. A second call for the same drug replaces the first
        entry rather than adding another, so repeating it changes nothing.

        Args:
            member_id: The member's unique ID.
            drug: The drug whose trial had the gap (e.g. "Methotrexate").
            effective_trial_months: `effective_trial_months` from review_trial_history —
                the duration that stands once the gap is explained. Pass it through
                exactly as returned, including a fractional month; do not round it.
            conclusion: Your own reasoning for why the gap does not invalidate the
                trial. Write it yourself; the system only stores it.
            related_note: The note_id of the clinical note that explains the gap
                (e.g. "NOTE-44109-hold"). Never invent one.
        """
        try:
            member = da.members().resolve_refill_gap(
                member_id=member_id,
                drug=drug,
                effective_trial_months=effective_trial_months,
                conclusion=conclusion,
                # An omitted note must be None, not "": the service distinguishes
                # "no note given" from a note whose id is blank.
                related_note=related_note or None,
            )
            if not member:
                return da.error(f"Member {member_id} not found")
            return da.respond(Member, member)
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to resolve refill gap: {str(e)}")

    @app.tool(is_local=False)
    def compute_recommendation(
        condition_code: str,
        step_confidences: str,
        criteria_satisfied: bool,
        coverage_restriction: str = "none",
    ) -> str:
        """Step 7: aggregate the reasoning steps and propose a decision.

        Do NOT compute this yourself. The aggregation is deterministic and documented
        because the bounded-authority gate keys off the number — inventing it would make
        the audit trail indefensible.

        Returns the proposed decision (approved / approved_restricted / denied), the
        aggregate confidence, and whether it clears the guideline's threshold.

        This is a RECOMMENDATION ONLY. You do not close the case, and you must not
        describe the outcome as final. A denial in particular can only be closed by a
        medical director.

        Args:
            condition_code: ICD-10 diagnosis code confirmed in Step 3 (e.g. "M06.9").
            step_confidences: Comma-separated confidences from the prior steps, in
                order — Step 3 match, Step 4 classification, Step 5 trial review,
                Step 6 step therapy. E.g. "0.98,0.97,0.95,0.90".
            criteria_satisfied: The `satisfied` value from Step 6.
            coverage_restriction: "partial" if Step 2 flagged partial coverage,
                otherwise "none".
        """
        # The service takes a list of floats; the comma-separated string is the
        # tool-facing contract the docstring documents. The former route did this
        # parse and answered a malformed list with a 422 rather than a stack trace.
        try:
            parsed = [float(part) for part in step_confidences.split(",") if part.strip()]
        except ValueError:
            return da.error(
                "step_confidences must be a comma-separated list of numbers, "
                "e.g. '0.98,0.97,0.95,0.90'"
            )

        try:
            result = da.guidelines().compute_recommendation(
                condition_code=condition_code,
                step_confidences=parsed,
                criteria_satisfied=criteria_satisfied,
                coverage_restriction=coverage_restriction,
            )
            if result is None:
                return da.error(f"No guideline found for condition {condition_code}")
            return da.respond(RecommendationResponse, result)
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to compute recommendation: {str(e)}")

    @app.tool(is_local=False)
    def record_reasoning_step(
        trace_id: str,
        memory_type: str,
        name: str,
        detail: str,
        confidence: float,
    ) -> str:
        """Record one reasoning step on the case's audit trace.

        Call this immediately after each of Steps 3, 4, 5 and 6, using the `detail`
        and `confidence` that step's tool returned — copy them exactly, never
        paraphrase the detail or round the number. This is what turns your reasoning
        into an auditable record instead of chat output, and it is what a second agent
        reads to know a clinical judgement was made.

        Tagging a step `episodic` or `procedural` marks the whole determination as
        clinical, which removes any agent's authority to close it. That is correct for
        Steps 5 and 6 and must not be softened to avoid an escalation.

        Args:
            trace_id: From get_open_case at case pickup. If it is null, Step 0 has not
                run and there is nothing to write to — say so rather than proceeding.
            memory_type: semantic (Step 3), taxonomic (Step 4), episodic (Step 5),
                procedural (Step 6).
            name: Short label, e.g. "concept_match", "trial_review".
            detail: The `detail` string the step's tool returned, verbatim.
            confidence: The `confidence` the step's tool returned.
        """
        try:
            trace = da.audit().append_step(
                trace_id=trace_id,
                memory_type=memory_type,
                name=name,
                detail=detail,
                confidence=confidence,
                # Stamped here, not asked of the model: two agents write to one
                # trace, and the record has to be able to attribute every step. A
                # value the LLM chose would be a value it could get wrong.
                recorded_by=AGENT_IDENTITY,
            )
            return da.respond(AuditTrace, trace)
        # The service signals a missing trace and an invalid step by exception, which
        # the former route mapped to 404 and 400. Both must stay distinguishable: one
        # means Step 0 never ran, the other that the step itself was rejected.
        except LookupError:
            return da.error(f"Trace {trace_id} not found")
        except ValueError as e:
            return da.error(f"Step not recorded: {str(e)}")
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to record reasoning step: {str(e)}")

    @app.tool(is_local=False)
    def record_recommendation(
        trace_id: str, decision: str, rationale: str, confidence: float
    ) -> str:
        """Record the proposed outcome on the trace — the last thing you do in Step 7.

        Pass the `recommendation`, `rationale` and `confidence` exactly as
        `compute_recommendation` returned them. Do not substitute your own judgement
        for the computed decision, and do not adjust the confidence.

        This records a RECOMMENDATION. It does not close the case and does not decide
        who may: that is a separate bounded-authority check the insurance agent runs
        against this outcome. Never describe the case as approved, denied or finished
        after calling this — it is now awaiting routing.

        Args:
            trace_id: From get_open_case at case pickup.
            decision: approved, approved_restricted, denied or pending.
            rationale: The plain-language rationale from compute_recommendation.
            confidence: The aggregate confidence from compute_recommendation.
        """
        try:
            trace = da.audit().record_recommendation(
                trace_id=trace_id,
                decision=decision,
                rationale=rationale,
                confidence=confidence,
            )
            return da.respond(AuditTrace, trace)
        except LookupError:
            return da.error(f"Trace {trace_id} not found")
        except ValueError as e:
            return da.error(f"Recommendation not recorded: {str(e)}")
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to record recommendation: {str(e)}")

    @app.tool(is_local=False)
    def get_member_authorizations(member_id: str) -> str:
        """Retrieve all prior-authorization decision traces (past and pending) for a member.

        Returns each trace's status, memory-typed reasoning steps, outcome, and
        review block (whether routed to a medical director, whether closed, who
        closed it). Prior authorizations are decision-trace documents in the Audit Log.

        Args:
            member_id: The member's unique ID.
        """
        try:
            # The service returns a bare list; the count and member_id wrapper were
            # added by the route and are part of the shape the model expects.
            traces = da.audit().get_member_traces(member_id)
            return da.respond(
                MemberTracesResponse,
                {"member_id": member_id, "trace_count": len(traces), "traces": traces},
            )
        except (PyMongoError, RuntimeError) as e:
            return da.error(f"Failed to retrieve authorizations: {str(e)}")

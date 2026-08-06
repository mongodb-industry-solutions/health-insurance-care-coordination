"""Tool definitions for care coordination agent."""

from __future__ import annotations

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from magenta_sdklanggraph import App


def _get_backend_url() -> str:
    """Get the backend service URL. Configurable via env var, defaults to Kubernetes DNS."""
    return os.environ.get("BACKEND_URL", "http://backend-service:8000")


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
            backend_url = _get_backend_url()
            response = requests.get(
                f"{backend_url}/api/members/{member_id}/clinical-context",
                timeout=5,
            )
            if response.status_code == 404:
                return json.dumps({"error": f"Member {member_id} not found"})
            response.raise_for_status()
            return json.dumps(response.json())
        except requests.RequestException as e:
            return json.dumps({"error": f"Failed to retrieve member context: {str(e)}"})

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
            backend_url = _get_backend_url()
            response = requests.get(
                f"{backend_url}/api/members/{member_id}/open-case",
                timeout=5,
            )
            if response.status_code == 404:
                return json.dumps({"error": f"Member {member_id} not found"})
            response.raise_for_status()
            return json.dumps(response.json())
        except requests.RequestException as e:
            return json.dumps({"error": f"Failed to retrieve open case: {str(e)}"})

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
            backend_url = _get_backend_url()
            response = requests.get(
                f"{backend_url}/api/members/{member_id}/concept-match",
                params={"requested_treatment": requested_treatment},
                timeout=5,
            )
            if response.status_code == 404:
                return json.dumps({"error": f"Member {member_id} not found"})
            response.raise_for_status()
            return json.dumps(response.json())
        except requests.RequestException as e:
            return json.dumps({"error": f"Failed to match clinical concept: {str(e)}"})

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
            backend_url = _get_backend_url()
            response = requests.get(
                f"{backend_url}/api/guidelines/condition/{condition_code}",
                timeout=5,
            )
            if response.status_code == 404:
                return json.dumps({"error": f"No guideline found for condition {condition_code}"})
            response.raise_for_status()
            return json.dumps(response.json())
        except requests.RequestException as e:
            return json.dumps({"error": f"Failed to retrieve guideline: {str(e)}"})

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
            backend_url = _get_backend_url()
            response = requests.get(
                f"{backend_url}/api/guidelines/condition/{condition_code}/classify",
                params={"requested_treatment": requested_treatment},
                timeout=5,
            )
            if response.status_code == 404:
                return json.dumps(
                    {"error": f"No guideline found for condition {condition_code}"}
                )
            response.raise_for_status()
            return json.dumps(response.json())
        except requests.RequestException as e:
            return json.dumps({"error": f"Failed to classify treatment: {str(e)}"})

    @app.tool(is_local=False)
    def evaluate_step_therapy(
        condition_code: str, documented_drug: str, documented_months: float
    ) -> str:
        """Step 6 (procedural memory): apply the guideline's step-therapy criteria.

        Answers the one question Step 6 exists to answer: does the trial on file meet
        the minimum the guideline requires? Returns `satisfied` true or false, and
        distinguishes a trial that is too short from one that is of the wrong drug.

        Pass `documented_months` as the `effective_trial_months` from Step 5 — not the
        record's `duration_months`, which understates trials still in progress.

        A `satisfied: false` result does NOT end the process. Continue to Step 7: the
        recommendation still has to go through confidence aggregation and the
        escalation check, and you have no authority to close a clinical denial.

        Args:
            condition_code: ICD-10 diagnosis code confirmed in Step 3 (e.g. "M06.9").
            documented_drug: The prior therapy reviewed in Step 5 (e.g. "Methotrexate").
            documented_months: effective_trial_months from Step 5.
        """
        try:
            backend_url = _get_backend_url()
            response = requests.get(
                f"{backend_url}/api/guidelines/condition/{condition_code}/step-therapy",
                params={
                    "documented_drug": documented_drug,
                    "documented_months": documented_months,
                },
                timeout=5,
            )
            if response.status_code == 404:
                return json.dumps(
                    {"error": f"No guideline found for condition {condition_code}"}
                )
            response.raise_for_status()
            return json.dumps(response.json())
        except requests.RequestException as e:
            return json.dumps({"error": f"Failed to evaluate step therapy: {str(e)}"})

    @app.tool(is_local=False)
    def find_comparable_claims(service: str, diagnosis: str, member_id: str) -> str:
        """Find prior adjudicated claims with the same service and diagnosis.

        Returns comparable cases (episodic memory) showing outcomes of similar
        treatments for similar presentations. Used to inform authorization confidence.

        Args:
            service: The therapy being sought. Prefer the canonical form
                "biologic therapy - <drug>" (e.g. "biologic therapy - secukinumab"),
                but the drug name alone (e.g. "secukinumab") also matches.
                Always name the specific drug — never a generic phrase like
                "biologic therapy" on its own.
            diagnosis: ICD-10 diagnosis code (e.g. "M06.9"), not the display name.
            member_id: The member whose case this is for (excluded from results; audits the read).
        """
        try:
            backend_url = _get_backend_url()
            response = requests.get(
                f"{backend_url}/api/claims/comparable",
                params={
                    "service_name": service,
                    "diagnosis": diagnosis,
                    "member_id": member_id,  # excluded from own results
                },
                timeout=5,
            )
            response.raise_for_status()
            return json.dumps(response.json())
        except requests.RequestException as e:
            return json.dumps({"error": f"Failed to find comparable claims: {str(e)}"})

    @app.tool(is_local=False)
    def review_trial_history(member_id: str, drug: str) -> str:
        """Step 5 (episodic memory): review the member's trial of the required therapy.

        Derives the effective trial duration from the member's actual pharmacy fills,
        flags any interruption in refill cadence, and reports whether a clinical note
        explains it. This is the number Step 6 evaluates — prefer it over
        `duration_months` on the record, which is often stale and understates a trial
        the member is still refilling.

        Read `effective_trial_months` as the answer. If `anomaly_detected` is true and
        `anomaly_explained` is false, only the longest uninterrupted run was credited
        and confidence is reduced — report that plainly and lean toward human review
        rather than crediting the full span.

        Args:
            member_id: The member's unique ID (e.g., MBR-2026-44109).
            drug: The required prior therapy to review, from Step 4's
                step_therapy_drug (e.g. "Methotrexate").
        """
        try:
            backend_url = _get_backend_url()
            response = requests.get(
                f"{backend_url}/api/members/{member_id}/trial-history",
                params={"drug": drug},
                timeout=5,
            )
            if response.status_code == 404:
                return json.dumps({"error": f"Member {member_id} not found"})
            response.raise_for_status()
            return json.dumps(response.json())
        except requests.RequestException as e:
            return json.dumps({"error": f"Failed to review trial history: {str(e)}"})

    @app.tool(is_local=False)
    def detect_refill_gaps(member_id: str, drug: str = "") -> str:
        """Detect breaks in a member's medication refill cadence.

        Analyzes the pharmacy claims timeline and returns any gaps where the
        interval between consecutive fills is longer than expected (a possible
        missed refill). Used by the verification agent to spot a gap before it is
        mistaken for a discontinuation.

        Args:
            member_id: The member's unique ID.
            drug: Optional drug display name (e.g. "Methotrexate") to scope the check.
        """
        try:
            backend_url = _get_backend_url()
            params = {}
            if drug:
                params["drug"] = drug
            response = requests.get(
                f"{backend_url}/api/claims/member/{member_id}/refill-gaps",
                params=params,
                timeout=5,
            )
            response.raise_for_status()
            return json.dumps(response.json())
        except requests.RequestException as e:
            return json.dumps({"error": f"Failed to detect refill gaps: {str(e)}"})

    @app.tool(is_local=False)
    def resolve_refill_gap(
        member_id: str,
        drug: str,
        effective_trial_months: int,
        conclusion: str,
        related_note: str = "",
    ) -> str:
        """Attach a verification conclusion about a refill gap to the member record.

        Call this after you have reviewed a detected refill gap and reasoned about
        whether it is explained (e.g. a documented medication hold, not a
        discontinuation). Your `conclusion` text is recorded as a treatment_response
        so the effective trial stands and the case proceeds.

        Args:
            member_id: The member's unique ID.
            drug: The drug whose trial had the gap (e.g. "Methotrexate").
            effective_trial_months: The effective trial duration after accounting for the gap.
            conclusion: Your reasoning about why the gap does or does not invalidate the trial.
            related_note: The note_id of the clinical note that explains the gap (e.g. "NOTE-44109-hold").
        """
        try:
            backend_url = _get_backend_url()
            params = {
                "drug": drug,
                "effective_trial_months": effective_trial_months,
                "conclusion": conclusion,
            }
            if related_note:
                params["related_note"] = related_note
            response = requests.post(
                f"{backend_url}/api/members/{member_id}/gap-resolution",
                params=params,
                timeout=5,
            )
            if response.status_code == 404:
                try:
                    detail = response.json().get("detail", "not found")
                except ValueError:
                    detail = "route not found (is the backend up to date?)"
                return json.dumps({"error": f"gap-resolution 404: {detail}"})
            response.raise_for_status()
            return json.dumps(response.json())
        except requests.RequestException as e:
            return json.dumps({"error": f"Failed to resolve refill gap: {str(e)}"})

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
        try:
            backend_url = _get_backend_url()
            response = requests.get(
                f"{backend_url}/api/guidelines/condition/{condition_code}/recommendation",
                params={
                    "step_confidences": step_confidences,
                    "criteria_satisfied": criteria_satisfied,
                    "coverage_restriction": coverage_restriction,
                },
                timeout=5,
            )
            if response.status_code == 404:
                return json.dumps(
                    {"error": f"No guideline found for condition {condition_code}"}
                )
            response.raise_for_status()
            return json.dumps(response.json())
        except requests.RequestException as e:
            return json.dumps({"error": f"Failed to compute recommendation: {str(e)}"})

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
            backend_url = _get_backend_url()
            response = requests.get(
                f"{backend_url}/api/audit/member/{member_id}/traces",
                timeout=5,
            )
            response.raise_for_status()
            return json.dumps(response.json())
        except requests.RequestException as e:
            return json.dumps({"error": f"Failed to retrieve authorizations: {str(e)}"})

    @app.tool(is_local=False)
    def file_authorization(member_id: str, requested_service: str) -> str:
        """File a formal prior-authorization request (creates a pending authorization).

        Call this before processing a decision. The request is a confirmation of the
        case already assembled; it does not decide anything.

        Args:
            member_id: The member's unique ID.
            requested_service: The service requested (e.g. "biologic therapy - secukinumab").
        """
        try:
            backend_url = _get_backend_url()
            response = requests.post(
                f"{backend_url}/api/audit/traces/file",
                params={"member_id": member_id, "requested_service": requested_service},
                timeout=5,
            )
            if response.status_code == 404:
                return json.dumps({"error": f"Member {member_id} not found"})
            response.raise_for_status()
            return json.dumps(response.json())
        except requests.RequestException as e:
            return json.dumps({"error": f"Failed to file authorization: {str(e)}"})

    @app.tool(is_local=False)
    def notify_member(member_id: str) -> str:
        """Send the member a plain-language notification about their latest decision.

        Args:
            member_id: The member's unique ID.
        """
        try:
            backend_url = _get_backend_url()
            response = requests.post(
                f"{backend_url}/api/notifications/notify",
                params={"member_id": member_id},
                timeout=5,
            )
            if response.status_code == 400:
                return json.dumps({"error": response.json().get("detail", "Bad request")})
            response.raise_for_status()
            return json.dumps(response.json())
        except requests.RequestException as e:
            return json.dumps({"error": f"Failed to notify member: {str(e)}"})

    @app.tool(is_local=False)
    def process_authorization(member_id: str) -> str:
        """Process the member's pending authorization and return the decision.

        The system computes the decision from the member's current record, the
        applicable guideline, and comparable precedent, applies bounded authority
        (auto-approve only if confidence meets the guideline threshold; denials and
        low-confidence cases route to a medical director), records the decision
        trace, and logs the decision. Call this after the case has been assembled
        and verified, and a formal request has been filed.

        Args:
            member_id: The member's unique ID (must have a pending authorization).
        """
        try:
            backend_url = _get_backend_url()
            response = requests.post(
                f"{backend_url}/api/audit/traces/process",
                params={"member_id": member_id},
                timeout=10,
            )
            if response.status_code == 400:
                return json.dumps({"error": response.json().get("detail", "Bad request")})
            response.raise_for_status()
            return json.dumps(response.json())
        except requests.RequestException as e:
            return json.dumps({"error": f"Failed to process authorization: {str(e)}"})

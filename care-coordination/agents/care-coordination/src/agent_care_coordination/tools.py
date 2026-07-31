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
        return datetime.now(timezone).date().isoformat()

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
    def get_applicable_guideline(condition_code: str, member_id: str) -> str:
        """Retrieve the latest clinical guideline for a condition.

        Returns taxonomic classification and procedural criteria (step therapy
        requirements, coverage tier, confidence thresholds) that an agent uses
        to evaluate medical necessity.

        Args:
            condition_code: ICD-10 diagnosis code (e.g., M06.9 for rheumatoid arthritis).
            member_id: The member whose case this read is part of (for the audit trail).
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
    def find_comparable_claims(service: str, diagnosis: str, member_id: str) -> str:
        """Find prior adjudicated claims with the same service and diagnosis.

        Returns comparable cases (episodic memory) showing outcomes of similar
        treatments for similar presentations. Used to inform authorization confidence.

        Args:
            service: Service description (e.g., "biologic therapy - secukinumab").
            diagnosis: ICD-10 diagnosis code.
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

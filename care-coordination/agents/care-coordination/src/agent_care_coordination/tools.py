"""Tool definitions for care coordination agent."""

from __future__ import annotations

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from magenta_sdklanggraph import App
from pymongo import MongoClient


def _get_care_gaps_collection():
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        return None
    db_name = os.environ.get("MONGODB_DATABASE", "hc_clinical_platform")
    collection_name = os.environ.get("MONGODB_CARE_GAPS_COLLECTION", "patient_360")
    client = MongoClient(uri)
    return client[db_name][collection_name]


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

    @app.tool(is_local=False)
    def get_care_gaps(patient_id: str, status: str = "all") -> str:
        """Retrieve care gaps for a patient from the healthcare database.

        Args:
            patient_id: The unique patient or member ID to look up.
            status: Filter by gap status. Use "open" for unmet gaps, "closed" for
                    completed gaps, or "all" to return every gap. Defaults to "all".
        """
        collection = _get_care_gaps_collection()
        if collection is None:
            return json.dumps({"error": "MONGODB_URI is not configured."})

        db_name = collection.database.name
        collection_name = collection.name
        total_docs = collection.count_documents({})

        patient = collection.find_one(
            {"patient_id": patient_id},
            {"care_gaps": 1, "_id": 0},
        )
        if patient is None:
            return json.dumps({
                "error": f"No patient found with ID: {patient_id}",
                "debug": {
                    "database": db_name,
                    "collection": collection_name,
                    "total_documents_in_collection": total_docs,
                },
            })

        gaps: list = patient.get("care_gaps", [])
        if status != "all":
            gaps = [g for g in gaps if g.get("status") == status]

        return json.dumps({"patient_id": patient_id, "status_filter": status, "care_gaps": gaps})

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
    def get_applicable_guideline(condition_code: str) -> str:
        """Retrieve the latest clinical guideline for a condition.

        Returns taxonomic classification and procedural criteria (step therapy
        requirements, coverage tier, confidence thresholds) that an agent uses
        to evaluate medical necessity.

        Args:
            condition_code: ICD-10 diagnosis code (e.g., M06.9 for rheumatoid arthritis).
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
    def find_comparable_claims(service: str, diagnosis: str) -> str:
        """Find prior adjudicated claims with the same service and diagnosis.

        Returns comparable cases (episodic memory) showing outcomes of similar
        treatments for similar presentations. Used to inform authorization confidence.

        Args:
            service: Service description (e.g., "biologic therapy - secukinumab").
            diagnosis: ICD-10 diagnosis code.
        """
        try:
            backend_url = _get_backend_url()
            response = requests.get(
                f"{backend_url}/api/claims/comparable",
                params={"service_name": service, "diagnosis": diagnosis},
                timeout=5,
            )
            response.raise_for_status()
            return json.dumps(response.json())
        except requests.RequestException as e:
            return json.dumps({"error": f"Failed to find comparable claims: {str(e)}"})

    @app.tool(is_local=False)
    def get_member_authorizations(member_id: str) -> str:
        """Retrieve all authorizations (past and pending) for a member.

        Returns authorization decisions, decision traces (reasoning), and review
        status (whether routed to a medical director, whether closed, who closed it).

        Args:
            member_id: The member's unique ID.
        """
        try:
            backend_url = _get_backend_url()
            response = requests.get(
                f"{backend_url}/api/authorizations/member/{member_id}",
                timeout=5,
            )
            response.raise_for_status()
            return json.dumps(response.json())
        except requests.RequestException as e:
            return json.dumps({"error": f"Failed to retrieve authorizations: {str(e)}"})

    @app.tool(is_local=False)
    def evaluate_authorization(
        member_id: str,
        requested_service: str,
        diagnosis_code: str,
    ) -> str:
        """Evaluate an authorization request and create the authorization decision.

        This is the main orchestration endpoint. It:
        - Assembles member clinical context
        - Looks up applicable guidelines
        - Validates step therapy requirements
        - Retrieves comparable cases (episodic memory)
        - Builds decision trace for CMS compliance
        - Applies bounded authority rules
        - Logs the decision to audit trail

        Args:
            member_id: The member's unique ID.
            requested_service: Service being authorized (e.g., "biologic therapy - secukinumab").
            diagnosis_code: ICD-10 diagnosis code for the condition.
        """
        try:
            backend_url = _get_backend_url()
            response = requests.post(
                f"{backend_url}/api/authorizations/evaluate",
                params={
                    "member_id": member_id,
                    "requested_service": requested_service,
                    "diagnosis_code": diagnosis_code,
                },
                timeout=10,
            )
            if response.status_code == 400:
                return json.dumps({"error": response.json().get("detail", "Bad request")})
            response.raise_for_status()
            return json.dumps(response.json())
        except requests.RequestException as e:
            return json.dumps({"error": f"Failed to evaluate authorization: {str(e)}"})

    @app.tool(is_local=False)
    def log_agent_action(
        member_id: str,
        action: str,
        fields_accessed: list,
        related_authorization: str = "",
    ) -> str:
        """Log an agent's action for the audit trail.

        Every agent interaction with a member record is logged so regulators can
        reconstruct what data was accessed, when, by which agent, and why.

        Args:
            member_id: The member's unique ID.
            action: What the agent did (e.g., "read_clinical_context").
            fields_accessed: List of member document fields accessed (e.g., ["clinical_history.treatment_responses"]).
            related_authorization: Optional authorization ID this action relates to.
        """
        try:
            backend_url = _get_backend_url()
            response = requests.post(
                f"{backend_url}/api/audit/log",
                params={
                    "member_id": member_id,
                    "agent": "pathway_agent",
                    "action": action,
                    "fields_accessed": fields_accessed,
                    "related_authorization": related_authorization if related_authorization else None,
                },
                timeout=5,
            )
            response.raise_for_status()
            return json.dumps(response.json())
        except requests.RequestException as e:
            return json.dumps({"error": f"Failed to log agent action: {str(e)}"})

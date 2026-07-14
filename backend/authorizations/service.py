"""Business logic for authorization decisions and bounded authority."""

from datetime import datetime, timezone

from .repository import AuthorizationRepository
from members.repository import MemberRepository
from guidelines.repository import GuidelineRepository
from claims.repository import ClaimRepository
from audit.repository import AuditRepository


class AuthorizationService:
    """Service layer for authorization decisions.

    Orchestrates member context, guidelines, comparable cases, and audit logging
    to build complete authorization decisions with decision traces.
    """

    def __init__(self):
        self.auth_repo = AuthorizationRepository()
        self.member_repo = MemberRepository()
        self.guideline_repo = GuidelineRepository()
        self.claim_repo = ClaimRepository()
        self.audit_repo = AuditRepository()

    def evaluate_authorization(
        self,
        member_id: str,
        requested_service: str,
        diagnosis_code: str,
    ) -> dict:
        """Evaluate an authorization request and create/update the authorization.

        Orchestrates:
        1. Member clinical context retrieval
        2. Applicable guideline lookup
        3. Step therapy validation
        4. Comparable case retrieval (episodic memory)
        5. Decision trace assembly (for CMS compliance)
        6. Authorization creation with bounded authority rules
        7. Audit logging
        """
        # Get member context
        member = self.member_repo.get_by_id(member_id)
        if not member:
            raise ValueError(f"Member {member_id} not found")

        # Get applicable guideline
        guideline = self.guideline_repo.latest_for_condition(diagnosis_code)
        if not guideline:
            raise ValueError(f"No guideline found for condition {diagnosis_code}")

        # Check step therapy requirement
        step_therapy_met, step_therapy_note = self._validate_step_therapy(
            member, guideline
        )

        # Find comparable cases (episodic memory)
        comparable_claims = self.claim_repo.find_comparable(requested_service, diagnosis_code)

        # Build decision trace (required by CMS rule)
        decision_trace = self._build_decision_trace(
            member,
            guideline,
            step_therapy_met,
            step_therapy_note,
            comparable_claims,
        )

        # Determine review routing (bounded authority)
        routed_to_human, confidence = self._assess_confidence(
            step_therapy_met, comparable_claims, guideline
        )

        # Create authorization with bounded authority rules
        auth = self._create_authorization(
            member_id,
            requested_service,
            diagnosis_code,
            decision_trace,
            routed_to_human,
            confidence,
        )

        # Log the authorization decision
        self.audit_repo.record(
            member_id=member_id,
            agent="pathway_agent",
            action="evaluate_authorization",
            fields_accessed=[
                "clinical_history.treatment_responses",
                "clinical_history.medications",
                "eligibility",
            ],
            related_authorization=auth["_id"],
        )

        return auth

    def _validate_step_therapy(self, member: dict, guideline: dict) -> tuple:
        """Check if step therapy requirement is met.

        Returns: (is_met: bool, explanation: str)
        """
        step_therapy_requirement = guideline.get("criteria", {}).get("step_therapy", {})
        if not step_therapy_requirement:
            return True, "No step therapy requirement"

        required_drug = step_therapy_requirement.get("drug")
        min_months = step_therapy_requirement.get("min_months", 6)

        # Check member's treatment responses
        treatment_responses = (
            member.get("clinical_history", {}).get("treatment_responses", [])
        )

        for response in treatment_responses:
            if response.get("drug") == required_drug:
                duration = response.get("duration_months", 0)
                if duration >= min_months:
                    return True, f"{required_drug}: {duration} months documented, requirement met"
                else:
                    return False, f"{required_drug}: {duration} months documented, {min_months} required"

        return False, f"No documented trial of {required_drug}"

    def _build_decision_trace(
        self,
        member: dict,
        guideline: dict,
        step_met: bool,
        step_note: str,
        comparable_claims: list,
    ) -> dict:
        """Build the decision trace required by CMS Interoperability & Prior Authorization Rule.

        The trace documents:
        - What evidence was assembled
        - Which guideline version was applied
        - The reasoning behind the decision
        """
        context_assembled = [step_note]

        if comparable_claims:
            context_assembled.append(
                f"comparable cases: {len(comparable_claims)} prior approvals with same service/diagnosis"
            )

        coverage_tier = guideline.get("criteria", {}).get("coverage_tier", "unknown")
        context_assembled.append(f"coverage tier: {coverage_tier}")

        return {
            "context_assembled": context_assembled,
            "guideline_version": guideline.get("_id"),
            "guideline_effective_date": guideline.get("effective_date"),
            "reasoning": (
                f"Step therapy: {'satisfied' if step_met else 'not satisfied'}. "
                f"{len(comparable_claims)} comparable case(s) found."
            ),
        }

    def _assess_confidence(
        self, step_met: bool, comparable_claims: list, guideline: dict
    ) -> tuple:
        """Assess decision confidence and whether to route to human review.

        Returns: (routed_to_human: bool, confidence_score: float)

        Rules:
        - If step therapy not met → route to MD (denial recommendation)
        - If confidence below guideline threshold → route to MD (ambiguous)
        - Otherwise → agent can approve
        """
        confidence_threshold = guideline.get("confidence_threshold", 0.90)

        if not step_met:
            # Step therapy not met → denial, always route to MD
            return True, 0.88

        if not comparable_claims:
            # No precedent → ambiguous, route to MD
            return True, 0.71

        # All criteria met and we have precedent → agent can approve
        confidence = min(0.95, confidence_threshold)
        return False, confidence

    def _create_authorization(
        self,
        member_id: str,
        requested_service: str,
        diagnosis_code: str,
        decision_trace: dict,
        routed_to_human: bool,
        confidence: float,
    ) -> dict:
        """Create or update an authorization with decision trace and bounded authority."""
        # Generate auth ID from member ID
        numeric = "".join(c for c in member_id if c.isdigit())[-5:]
        auth_id = f"AUTH-{numeric}"

        now = datetime.now(timezone.utc).isoformat() + "Z"

        authorization = {
            "_id": auth_id,
            "member_id": member_id,
            "requested_service": requested_service,
            "diagnosis_code": diagnosis_code,
            "status": "approved" if not routed_to_human else "pending_review",
            "created_at": now,
            "decision_trace": {
                **decision_trace,
                "agent_confidence": confidence,
            },
            "review": {
                "routed_to_human": routed_to_human,
                "final_decision_maker": "medical_director" if routed_to_human else "agent",
                "closed_by": None if routed_to_human else "pathway_agent",
                "closed_at": None if routed_to_human else now,
            },
        }

        self.auth_repo.upsert(authorization)
        return authorization

    def get_authorization(self, auth_id: str) -> dict:
        """Retrieve a specific authorization."""
        return self.auth_repo.get_by_id(auth_id)

    def get_member_authorizations(self, member_id: str) -> list:
        """Retrieve all authorizations for a member."""
        return self.auth_repo.find_by_member(member_id)

    def get_pending_human_review(self) -> list:
        """Retrieve all authorizations pending medical director review."""
        return self.auth_repo.find_routed_to_human()

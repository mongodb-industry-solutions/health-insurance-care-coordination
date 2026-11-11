"""The composed member: insurance record + clinical profile."""

import logging
from typing import Optional

from clinical.profiles.service import ProfileService
from insurance.members.service import MemberService

logger = logging.getLogger(__name__)

# What a member without a clinical profile looks like. A member with no profile is a data
# problem, but a read should still answer rather than fail the whole dashboard.
_EMPTY_HISTORY = {"diagnoses": [], "medications": [], "treatment_responses": [], "clinical_notes": []}


class MemberView:
    def __init__(self, members: MemberService, profiles: ProfileService):
        self.members = members
        self.profiles = profiles

    def compose(self, member_id: str) -> Optional[dict]:
        """The combined member document, or None when the insurance side has no such member.

        The insurance record is authoritative for identity and eligibility (and wins on the
        demographics both sides hold); the clinical profile supplies history, care plan,
        pending actions and `phi_encrypted`. `summary` is merged: the authorization fields
        from insurance, `active_condition_count` from clinical.
        """
        member = self.members.get_member(member_id)
        if not member:
            return None
        member = {k: v for k, v in member.items() if k != "_id"}

        profile = self.profiles.get_profile(member_id)
        if profile is None:
            logger.warning("member %s has no clinical profile; returning empty clinical data", member_id)
            profile = {}

        insurance_summary = member.get("summary") or {}
        clinical_summary = profile.get("summary") or {}
        member.update(
            {
                "phi_encrypted": profile.get("phi_encrypted"),
                "clinical_history": profile.get("clinical_history") or _EMPTY_HISTORY,
                "current_care_plan": profile.get("current_care_plan") or {},
                "pendingActions": profile.get("pendingActions") or [],
                "summary": {
                    "active_condition_count": clinical_summary.get("active_condition_count", 0),
                    "open_authorization_count": insurance_summary.get("open_authorization_count", 0),
                    "last_authorization_status": insurance_summary.get("last_authorization_status", "none"),
                    "updated_at": max(
                        insurance_summary.get("updated_at") or "",
                        clinical_summary.get("updated_at") or "",
                    ),
                },
            }
        )
        return member

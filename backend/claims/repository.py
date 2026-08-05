import re

from core.repository import Repository
from shared.collections import Collections


class ClaimRepository(Repository):
    """Access to the `claims` collection.

    Claims are the member's adjudicated history and the source of comparable-case
    precedent (episodic memory) an agent retrieves when weighing an approval.
    """

    collection_name = Collections.CLAIMS
    business_key = "claimId"

    def find_by_member(self, member_id):
        return self.find({"memberId": member_id})

    def delete_by_member(self, member_id):
        """Remove all claims for a member (used by demo reset)."""
        return self.delete_by({"memberId": member_id})

    @staticmethod
    def _service_token(service):
        """The most specific part of a service description — normally the drug.

        "biologic therapy - secukinumab" -> "secukinumab"
        "Secukinumab therapy"            -> "Secukinumab"
        "secukinumab"                    -> "secukinumab"
        """
        text = (service or "").strip()
        if " - " in text:
            text = text.rsplit(" - ", 1)[-1].strip()
        for suffix in (" therapy", " treatment"):
            if text.lower().endswith(suffix):
                text = text[: -len(suffix)].strip()
        return text or (service or "")

    def find_comparable(self, service, diagnosis, exclude_member=None, limit=3):
        """Retrieve comparable precedent: other members' APPROVED claims for the
        same service + diagnosis.

        Filters to `outcome: approved`, excludes the querying member (a member is
        not their own precedent), projects only what the agent needs to judge
        similarity, and caps the result.

        Service matching is a case-insensitive substring match on the most
        specific token in the query (normally the drug name), not string
        equality. An agent asked for "comparable cases for secukinumab" should
        find a claim stored as "biologic therapy - secukinumab" — requiring the
        caller to reproduce an exact phrase makes retrieval fail silently, and an
        empty result reads as "no precedent exists" rather than "you phrased it
        differently". See claims/service.py for the Atlas Vector Search upgrade
        path, which replaces this with semantic similarity.
        """
        query = {
            "service": {"$regex": re.escape(self._service_token(service)), "$options": "i"},
            "diagnosis": diagnosis,
            "outcome": "approved",
        }
        if exclude_member:
            query["memberId"] = {"$ne": exclude_member}
        projection = {
            "claimId": 1,
            "service": 1,
            "outcome": 1,
            "presentation_profile": 1,
            "memberId": 1,
        }
        return list(self.collection.find(query, projection).limit(limit))

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

    def exists(self, claim_id):
        """Is this business key already taken?

        Used before minting a new `claimId`. The unique index on `claimId` (see
        db/indexes.py) is the real guarantee — this is the cheap pre-check that
        avoids relying on an exception for the common case.
        """
        return self.collection.count_documents({"claimId": claim_id}, limit=1) > 0

    def insert_claim(self, document):
        """Insert a new claim, letting MongoDB assign `_id`.

        Plain `insert`, not the inherited `upsert`: the final data model leaves
        `_id` as a MongoDB-assigned ObjectId, and `upsert` keys on a caller-supplied
        `_id` it no longer has. Raises `DuplicateKeyError` if `claimId` collides and
        the unique index is in place.
        """
        return self.insert(document)

    def update_fields(self, claim_id, updates):
        """Write specific top-level fields on a claim.

        Field-level `$set` rather than a whole-document replace, so an outcome write
        cannot roll back a concurrent change to an unrelated field. Returns the
        number of documents modified; 0 means no claim matched.
        """
        return self.collection.update_one(
            {"claimId": claim_id}, {"$set": updates}
        ).modified_count

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

        Filters to approved claims, excludes the querying member (a member is not
        their own precedent), projects only what the agent needs to judge
        similarity, and caps the result.

        **Matches on the coded fields the final data model carries** —
        `procedureDesc`, `diagnosisCode` and `status`. The earlier revision's
        `service` / `diagnosis` / `outcome` fields no longer exist on claim
        documents, so querying them matched nothing and every search came back
        empty — which reads as "no precedent exists" rather than "this query is
        looking at fields that are gone", and quietly depressed every confidence
        score that counts precedent.

        Matching is deliberately on `procedureDesc`, not `procedureCode`: callers
        pass a drug name ("biologic therapy - secukinumab"), never a J-code.
        `_service_token` reduces that to `secukinumab`, which case-insensitively
        substring-matches a stored `"Secukinumab therapy"`. Requiring the caller to
        reproduce an exact phrase — or to know a code it never sees — makes
        retrieval fail silently. See claims/service.py for the Atlas Vector Search
        upgrade path, which replaces this with semantic similarity.

        `service` and `outcome` are projected as aliases of `procedureDesc` and
        `status`, so the response shape the agent's prompts already read is
        unchanged even though the underlying fields moved.
        """
        query = {
            "procedureDesc": {
                "$regex": re.escape(self._service_token(service)),
                "$options": "i",
            },
            "diagnosisCode": diagnosis,
            "status": {"$in": ["approved", "approved_restricted", "paid"]},
        }
        if exclude_member:
            query["memberId"] = {"$ne": exclude_member}
        projection = {
            "claimId": 1,
            "memberId": 1,
            "presentation_profile": 1,
            # Keep the response shape stable across the field rename.
            "service": "$procedureDesc",
            "outcome": "$status",
        }
        return list(self.collection.find(query, projection).limit(limit))

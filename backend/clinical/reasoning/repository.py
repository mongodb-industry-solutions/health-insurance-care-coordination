from core.repository import Repository
from shared.collections import ClinicalCollections


class ClinicalReasoningRepository(Repository):
    """The full text of the Care-Coordination Agent's reasoning steps (`clinical_reasoning`).

    The shared trace holds only an envelope for each step; the text lives here, referenced
    from `steps[].detailRef`. The backend reads it to hydrate traces for people.
    """

    collection_name = ClinicalCollections.CLINICAL_REASONING
    business_key = "traceId"

    def details_for(self, trace_ids) -> dict:
        """{(traceId, stepId): detail} for the given traces."""
        if not trace_ids:
            return {}
        rows = self.collection.find({"traceId": {"$in": list(trace_ids)}})
        return {(r["traceId"], r["stepId"]): r.get("detail") for r in rows}

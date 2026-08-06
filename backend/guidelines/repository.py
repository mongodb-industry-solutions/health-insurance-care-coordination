from core.repository import Repository
from shared.collections import Collections


class GuidelineRepository(Repository):
    """Access to the `guidelines` collection.

    Guidelines hold taxonomic classification (reason by category) and procedural
    criteria (the gates applied at runtime), keyed by condition and version.
    """

    collection_name = Collections.GUIDELINES

    def find_by_condition(self, condition):
        """Return guidelines for a diagnosis code, newest effective_date first."""
        return list(
            self.collection.find({"condition": condition}).sort("effective_date", -1)
        )

    def latest_for_condition(self, condition):
        results = self.find_by_condition(condition)
        return results[0] if results else None

    def find_by_classified_drug(self, drug):
        """Return guidelines whose `classification` enumerates this drug.

        The reverse of `find_by_condition`: given a therapy name, find which
        conditions any guideline classifies it under. This is what lets a
        requested drug be resolved to a diagnosis code without the caller
        already knowing the condition. `classification` keys are lowercase
        therapy names, so `drug` is lowercased before the lookup.
        """
        if not drug:
            return []
        return list(
            self.collection.find(
                {f"classification.{drug.lower()}": {"$exists": True}}
            ).sort("effective_date", -1)
        )

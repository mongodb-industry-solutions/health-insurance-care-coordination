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

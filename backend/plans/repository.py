from core.repository import Repository
from shared.collections import Collections


class PlanRepository(Repository):
    """Access to the `plans` collection.

    Plans describe eligibility rules and coverage tiers a member is enrolled in.
    Schema is intentionally light for now and will grow as coverage logic does.
    """

    collection_name = Collections.PLANS

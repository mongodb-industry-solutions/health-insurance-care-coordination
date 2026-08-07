"""Business-key indexes. Run deliberately, never on startup.

Every lookup in this backend resolves on a business key (`memberId`, `policyId`,
`planId`, `claimId`, `traceId`) rather than on `_id`, which is a MongoDB-assigned
ObjectId and not a join key anywhere in the data model. Without these indexes
those lookups are collection scans, and nothing prevents two documents sharing a
business key.

This is a script rather than a startup hook on purpose: creating a UNIQUE index
fails if the collection already contains duplicates. As a lifespan hook that
turns into a boot loop; run manually, it is a readable one-time error you can act
on.

Usage:
    cd backend && python -m db.indexes          # create indexes
    cd backend && python -m db.indexes --check  # report only, create nothing
"""

import sys

from pymongo.errors import DuplicateKeyError, OperationFailure

from db.mdb import get_connector
from shared.collections import Collections

# (collection, field) pairs the repositories resolve lookups on.
UNIQUE_INDEXES = [
    (Collections.MEMBERS, "memberId"),
    (Collections.POLICIES, "policyId"),
    (Collections.PLANS, "planId"),
    (Collections.CLAIMS, "claimId"),
    (Collections.AUDIT_LOG, "traceId"),
]

# Non-unique indexes supporting the multi-document reads. These are the query
# shapes in the repositories: claims/traces by member, policies by plan.
SECONDARY_INDEXES = [
    (Collections.MEMBERS, "policyId"),
    (Collections.POLICIES, "planId"),
    (Collections.CLAIMS, "memberId"),
    (Collections.AUDIT_LOG, "subjectRef"),
    (Collections.NOTIFICATIONS, "memberId"),
    (Collections.GUIDELINES, "condition"),
]


def _duplicates(collection, field):
    """Business-key values appearing on more than one document."""
    pipeline = [
        {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}},
    ]
    return [(g["_id"], g["count"]) for g in collection.aggregate(pipeline)]


def check() -> int:
    """Report duplicate business keys without creating anything.

    Returns the number of collections with duplicates, so this doubles as a
    pre-flight check before a unique-index build.
    """
    connector = get_connector()
    problems = 0
    for name, field in UNIQUE_INDEXES:
        collection = connector.get_collection(name)
        total = collection.count_documents({})
        missing = collection.count_documents({field: {"$exists": False}})
        dupes = _duplicates(collection, field)
        status = "ok"
        if dupes or missing:
            problems += 1
            status = "PROBLEM"
        print(f"[{status:>7}] {name}.{field}: {total} docs, {missing} missing the field, "
              f"{len(dupes)} duplicated value(s)")
        for value, count in dupes:
            print(f"            duplicate {value!r} x{count}")
    return problems


def create() -> None:
    """Create the indexes. Idempotent — an existing identical index is a no-op."""
    connector = get_connector()

    for name, field in UNIQUE_INDEXES:
        collection = connector.get_collection(name)
        try:
            collection.create_index(field, unique=True, name=f"{field}_unique")
            print(f"[ unique] {name}.{field}")
        except (DuplicateKeyError, OperationFailure) as e:
            # Almost always pre-existing duplicates. Report and keep going rather
            # than aborting the whole run partway through.
            print(f"[ FAILED] {name}.{field}: {e}")

    for name, field in SECONDARY_INDEXES:
        collection = connector.get_collection(name)
        try:
            collection.create_index(field, name=f"{field}_idx")
            print(f"[  index] {name}.{field}")
        except OperationFailure as e:
            print(f"[ FAILED] {name}.{field}: {e}")


def main() -> int:
    if "--check" in sys.argv:
        return 1 if check() else 0
    if check():
        print("\nDuplicates or missing business keys found above. Unique-index "
              "creation will fail on those collections — resolve them first, or "
              "re-run and accept the reported failures.\n")
    create()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

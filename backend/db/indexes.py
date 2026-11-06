"""Business-key indexes, per database. Run deliberately, never on startup.

Every lookup in this backend resolves on a business key (`memberId`, `policyId`, `planId`,
`claimId`, `traceId`, `guidelineId`, `fillId`) rather than on `_id`, which is a MongoDB-
assigned ObjectId and not a join key anywhere in the data model. Without these indexes those
lookups are collection scans, and nothing prevents two documents sharing a business key.

The data lives in two databases, so there are two sets. They mirror the index lists in
`data/insurance-data/README.md` and `data/health-data/README.md`. Run this against both with
one command.

This is a script rather than a startup hook on purpose: creating a UNIQUE index fails if the
collection already contains duplicates. As a lifespan hook that turns into a boot loop; run
manually, it is a readable one-time error you can act on.

Usage:
    cd backend && python -m db.indexes          # create indexes
    cd backend && python -m db.indexes --check  # report only, create nothing
"""

import sys

from pymongo.errors import DuplicateKeyError, OperationFailure

from db.mdb import get_clinical_connector, get_insurance_connector
from shared.collections import ClinicalCollections, Collections

# (collection, [(field, direction), ...]) the repositories resolve lookups on.
# `unique` ones are listed first; compound ones keep their order.
INSURANCE_UNIQUE = [
    (Collections.MEMBERS, [("memberId", 1)]),
    (Collections.POLICIES, [("policyId", 1)]),
    (Collections.PLANS, [("planId", 1)]),
    (Collections.CLAIMS, [("claimId", 1)]),
    (Collections.AUDIT_LOG, [("traceId", 1)]),
    (Collections.ADMIN_REASONING, [("traceId", 1), ("stepId", 1)]),
]
INSURANCE_SECONDARY = [
    (Collections.MEMBERS, [("policyId", 1)]),
    (Collections.CLAIMS, [("memberId", 1)]),
    (Collections.AUDIT_LOG, [("subjectRef", 1), ("workflow.nextActor", 1)]),
]

CLINICAL_UNIQUE = [
    (ClinicalCollections.CLINICAL_PROFILES, [("memberId", 1)]),
    (ClinicalCollections.DISPENSE_HISTORY, [("fillId", 1)]),
    (ClinicalCollections.GUIDELINES, [("guidelineId", 1)]),
    (ClinicalCollections.CLINICAL_REASONING, [("traceId", 1), ("stepId", 1)]),
]
CLINICAL_SECONDARY = [
    (ClinicalCollections.DISPENSE_HISTORY, [("memberId", 1), ("drug", 1), ("fillDate", 1)]),
    (ClinicalCollections.GUIDELINES, [("condition", 1), ("effective_date", -1)]),
    (ClinicalCollections.CLINICAL_REASONING, [("memberId", 1)]),
]


def _plan():
    """(label, connector, unique, secondary) for each database."""
    return [
        ("insurance", get_insurance_connector(), INSURANCE_UNIQUE, INSURANCE_SECONDARY),
        ("clinical", get_clinical_connector(), CLINICAL_UNIQUE, CLINICAL_SECONDARY),
    ]


def _duplicates(collection, fields):
    """Key values appearing on more than one document."""
    pipeline = [
        {"$group": {"_id": {f: f"${f}" for f, _ in fields}, "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}},
    ]
    return [(g["_id"], g["count"]) for g in collection.aggregate(pipeline)]


def check() -> int:
    """Report duplicate business keys without creating anything.

    Returns the number of collections with duplicates, so this doubles as a pre-flight check
    before a unique-index build.
    """
    problems = 0
    for label, connector, unique, _secondary in _plan():
        for name, fields in unique:
            collection = connector.get_collection(name)
            total = collection.count_documents({})
            missing = sum(
                collection.count_documents({f: {"$exists": False}}) for f, _ in fields
            )
            dupes = _duplicates(collection, fields)
            status = "ok"
            if dupes or missing:
                problems += 1
                status = "PROBLEM"
            keys = "+".join(f for f, _ in fields)
            print(f"[{status:>7}] {label}.{name}.{keys}: {total} docs, {missing} missing a key "
                  f"field, {len(dupes)} duplicated value(s)")
            for value, count in dupes:
                print(f"            duplicate {value!r} x{count}")
    return problems


def create() -> None:
    """Create the indexes in both databases. Idempotent: an existing identical index is a
    no-op."""
    for label, connector, unique, secondary in _plan():
        for name, fields in unique:
            collection = connector.get_collection(name)
            keys = "+".join(f for f, _ in fields)
            try:
                collection.create_index(fields, unique=True, name=f"{keys}_unique")
                print(f"[ unique] {label}.{name}.{keys}")
            except (DuplicateKeyError, OperationFailure) as e:
                # Almost always pre-existing duplicates. Report and keep going rather than
                # aborting the whole run partway through.
                print(f"[ FAILED] {label}.{name}.{keys}: {e}")

        for name, fields in secondary:
            collection = connector.get_collection(name)
            keys = "+".join(f for f, _ in fields)
            try:
                collection.create_index(fields, name=f"{keys}_idx")
                print(f"[  index] {label}.{name}.{keys}")
            except OperationFailure as e:
                print(f"[ FAILED] {label}.{name}.{keys}: {e}")


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

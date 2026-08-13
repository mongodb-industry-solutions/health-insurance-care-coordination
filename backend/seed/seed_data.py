"""Seed the care-coordination database with synthetic data.

Run as a module from the `backend/` directory:

    python -m seed.seed_data            # upsert all profiles + reference data
    python -m seed.seed_data --reset    # clear collections first, then seed

This is a thin CLI over `AdminService`, which is the same code
`POST /seed` and `POST /reset-demo` run. That is deliberate:
the two used to keep separate lists of repositories to wipe, they drifted, and
`--reset` quietly stopped clearing `notifications`. A shell and an HTTP request
should not be able to leave the database in different states.

Seeding is idempotent (replace-by-_id upserts), so it is safe to re-run. The
`--reset` flag wipes the seeded collections first for a clean slate.

Baseline is pre-decision: policies + members + adjudicated claims history only.
No prior-authorization trace is seeded — the demo (Phase 1-3) files and decides
it, writing the decision trace into the `audit_log` collection at runtime.

Requires a working MongoDB connection via the following env vars
    1. MONGODB_URI,
    2. DATABASE_NAME,
    3. APP_NAME
used by db.mdb.MongoDBConnector.
"""

import argparse

from db.mdb import MongoDBConnector
from admin.service import AdminService
from seed.generators import ALL_PROFILES

# Member names for the output. The service returns ids, not names — it answers an
# HTTP client — but a human watching a terminal wants to see who was seeded.
_NAMES = {profile.member_id: profile.name for profile in ALL_PROFILES}


def seed(reset: bool = False):
    """Seed the demo dataset, optionally wiping it first.

    Unlike the endpoints, output arrives at the end rather than per member: the
    service does the whole run and returns counts. Six members take a second or two.
    """
    # Own connector rather than the cached app singleton — this is a short-lived
    # process, not a request.
    service = AdminService(MongoDBConnector())

    if reset:
        result = service.reset_all()
        for collection, deleted in result["removed"].items():
            print(f"  reset {collection}: removed {deleted} docs")
        seeded = result["seeded"]
    else:
        seeded = service.seed_canonical()

    reference = seeded["reference"]
    print(
        f"seeded {reference['plans']} plans, {reference['guidelines']} guidelines, "
        f"{reference['precedent_claims']} precedent claims"
    )

    for member in seeded["members"]:
        member_id = member["member_id"]
        print(
            f"seeded {member_id} ({_NAMES.get(member_id, '?')}): "
            f"{member['claims']} claims [{member['case_type']}]"
        )

    print("done.")


def main():
    parser = argparse.ArgumentParser(description="Seed care-coordination demo data.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear seeded collections before inserting.",
    )
    args = parser.parse_args()
    seed(reset=args.reset)


if __name__ == "__main__":
    main()

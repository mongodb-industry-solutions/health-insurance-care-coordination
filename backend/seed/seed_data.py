"""Seed the care-coordination database with synthetic data.

Run as a module from the `backend/` directory:

    python -m seed.seed_data            # upsert all profiles + reference data
    python -m seed.seed_data --reset    # clear collections first, then seed

Seeding is idempotent (replace-by-_id upserts), so it is safe to re-run. The
`--reset` flag wipes the seeded collections first for a clean slate.

Requires a working MongoDB connection via the following env vars 
    1. MONGODB_URI,
    2. DATABASE_NAME, 
    3. APP_NAME 
used by db.mdb.MongoDBConnector.
"""

import argparse

from db.mdb import MongoDBConnector
from members import MemberRepository
from authorizations import AuthorizationRepository
from claims import ClaimRepository
from guidelines import GuidelineRepository
from plans import PlanRepository
from audit.repository import AuditRepository
from seed.generators import ALL_PROFILES, GUIDELINES, PLANS, build_bundle


def seed(reset: bool = False):
    connector = MongoDBConnector()

    members = MemberRepository(connector)
    authorizations = AuthorizationRepository(connector)
    claims = ClaimRepository(connector)
    guidelines = GuidelineRepository(connector)
    plans = PlanRepository(connector)
    audit = AuditRepository(connector)

    if reset:
        for repo in (members, authorizations, claims, guidelines, plans, audit):
            deleted = repo.delete_all()
            print(f"  reset {repo.collection_name}: removed {deleted} docs")

    # Reference data (shared across members)
    plans.upsert_many(PLANS)
    guidelines.upsert_many(GUIDELINES)
    print(f"seeded {len(PLANS)} plans, {len(GUIDELINES)} guidelines")

    # Per-member data. Baseline is pre-decision: member + claims history only.
    # No authorization is seeded — the demo (Phase 1-3) files and decides it.
    for profile in ALL_PROFILES:
        bundle = build_bundle(profile)
        members.upsert(bundle["member"])
        claims.upsert_many(bundle["claims"])
        audit.upsert_many(bundle["audit"])
        print(
            f"seeded {profile.member_id} ({profile.name}): "
            f"{len(bundle['claims'])} claims, {len(bundle['audit'])} audit [{profile.case_type}]"
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

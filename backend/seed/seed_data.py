"""Seed the care-coordination database with synthetic data.

Run as a module from the `backend/` directory:

    python -m seed.seed_data            # upsert all profiles + reference data
    python -m seed.seed_data --reset    # clear collections first, then seed

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
from members import MemberRepository
from policies import PolicyRepository
from claims import ClaimRepository
from guidelines import GuidelineRepository
from plans import PlanRepository
from audit.repository import AuditRepository
from notifications.repository import NotificationRepository
from seed.generators import ALL_PROFILES, GUIDELINES, PLANS, PRECEDENT_CLAIMS, build_bundle


def seed(reset: bool = False):
    connector = MongoDBConnector()

    members = MemberRepository(connector)
    policies = PolicyRepository(connector)
    claims = ClaimRepository(connector)
    guidelines = GuidelineRepository(connector)
    plans = PlanRepository(connector)
    audit = AuditRepository(connector)
    notifications = NotificationRepository(connector)

    if reset:
        # Same set as POST /api/admin/reset-demo, so the two paths mean the same thing.
        # Notifications are written at runtime (every closure notifies the member) and
        # are not keyed to a trace, so leaving them behind makes a re-run of the same
        # member show a notification from the previous run.
        for repo in (members, policies, claims, guidelines, plans, audit, notifications):
            deleted = repo.delete_all()
            print(f"  reset {repo.collection_name}: removed {deleted} docs")

    # Reference data (shared across members)
    plans.upsert_many(PLANS)
    guidelines.upsert_many(GUIDELINES)
    # Historical precedent claims (episodic memory for comparable-case retrieval)
    claims.upsert_many(PRECEDENT_CLAIMS)
    print(
        f"seeded {len(PLANS)} plans, {len(GUIDELINES)} guidelines, "
        f"{len(PRECEDENT_CLAIMS)} precedent claims"
    )

    # Per-member data. Baseline is pre-decision: policy + member + claims history.
    for profile in ALL_PROFILES:
        bundle = build_bundle(profile)
        policies.upsert(bundle["policy"])
        members.upsert(bundle["member"])
        claims.upsert_many(bundle["claims"])
        print(
            f"seeded {profile.member_id} ({profile.name}): "
            f"{len(bundle['claims'])} claims [{profile.case_type}]"
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

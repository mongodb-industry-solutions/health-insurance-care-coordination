"""Seed the two care-coordination databases with the synthetic demo data.

Run as a module from the `backend/` directory:

    python -m seed.seed_data            # upsert the fixtures
    python -m seed.seed_data --reset    # clear the seeded collections first, then seed

A thin CLI over `AdminService`, the same code `POST /seed` and `POST /reset-demo` run, so a
shell and an HTTP request cannot leave the databases in different states. Seeding is
idempotent (upserts on business keys), so it is safe to re-run.

Baseline is pre-decision: members, policies, plans and claims in the insurance database;
clinical profiles, fills and guidelines in the clinical one. No trace is seeded: the demo
files and decides it at runtime.

Requires MONGODB_URI, INSURANCE_DATABASE and CLINICAL_DATABASE (see `db/mdb.py`).
"""

import argparse

from admin.service import AdminService
from db.mdb import get_clinical_connector, get_insurance_connector


def seed(reset: bool = False):
    service = AdminService(get_insurance_connector(), get_clinical_connector())

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
        print(
            f"seeded {member['member_id']}: {member['claims']} claims, "
            f"{member['dispense_fills']} fills"
        )
    print("done.")


def main():
    parser = argparse.ArgumentParser(description="Seed care-coordination demo data.")
    parser.add_argument("--reset", action="store_true", help="Clear seeded collections first.")
    seed(reset=parser.parse_args().reset)


if __name__ == "__main__":
    main()

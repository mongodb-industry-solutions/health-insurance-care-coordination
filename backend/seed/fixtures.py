"""Loader for the seed fixtures.

The seed data is the JSON files under `seed/fixtures/`, copies of `data/insurance-data/` and
`data/health-data/`. They live inside `backend/` because the backend image copies only that
directory. `tests/test_seed_fixtures.py` fails when a copy drifts from its source in `data/`,
so the two cannot disagree unnoticed.

Override the location with `SEED_FIXTURES_DIR` (e.g. to point at `data/` checked out beside
the backend).

All files are JSON arrays with ISO-8601 string dates and **no `_id`**: MongoDB assigns an
ObjectId on insert, and every lookup joins on a business key.
"""

import json
import os
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parent / "fixtures"

# fixture name -> (database, collection, business key)
INSURANCE = {
    "members": ("members", "memberId"),
    "policies": ("policies", "policyId"),
    "plans": ("plans", "planId"),
    "claims": ("claims", "claimId"),
}
CLINICAL = {
    "clinical_profiles": ("clinical_profiles", "memberId"),
    "dispense_history": ("dispense_history", "fillId"),
    "guidelines": ("guidelines", "guidelineId"),
}


def fixtures_dir() -> Path:
    return Path(os.getenv("SEED_FIXTURES_DIR") or DEFAULT_DIR)


def load(name: str) -> list:
    """The documents in one fixture file."""
    path = fixtures_dir() / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Seed fixture {path} not found. Set SEED_FIXTURES_DIR to a directory holding "
            "the insurance and clinical seed files."
        )
    return json.loads(path.read_text(encoding="utf-8"))

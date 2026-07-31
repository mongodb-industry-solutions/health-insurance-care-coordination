"""Demo orchestration: seed and reset synthetic data.

This is an *orchestration* layer, not a domain: every operation here spans
multiple domains (policies + members + claims + audit-log traces + reference
data), so it composes the domain repositories rather than belonging to any one of
them. It exists to run the demo — it is deliberately the only place allowed to
delete append-only audit rows, and it should be locked down or removed for
production.

Baseline data is regenerated from the canonical profiles (`seed.generators`),
which are pure and deterministic, so reset means: delete the mutation surface,
then re-derive the baseline. No golden snapshot to maintain.
"""

from db.mdb import get_connector
from members.repository import MemberRepository
from policies.repository import PolicyRepository
from claims.repository import ClaimRepository
from audit.repository import AuditRepository
from guidelines.repository import GuidelineRepository
from plans.repository import PlanRepository
from notifications.repository import NotificationRepository
from seed.generators import ALL_PROFILES, GUIDELINES, PLANS, PRECEDENT_CLAIMS, build_bundle

# Index the canonical profiles by member id so reset can find a member's baseline.
_PROFILES_BY_MEMBER = {profile.member_id: profile for profile in ALL_PROFILES}


class AdminService:
    """Seed and reset the demo dataset by composing domain repositories."""

    def __init__(self, connector=None):
        connector = connector or get_connector()
        self.members = MemberRepository(connector)
        self.policies = PolicyRepository(connector)
        self.claims = ClaimRepository(connector)
        self.audit = AuditRepository(connector)
        self.guidelines = GuidelineRepository(connector)
        self.plans = PlanRepository(connector)
        self.notifications = NotificationRepository(connector)

    # --- reference data ------------------------------------------------------

    def _seed_reference(self):
        self.plans.upsert_many(PLANS)
        self.guidelines.upsert_many(GUIDELINES)
        # Historical precedent claims (other members) — episodic memory for
        # comparable-case retrieval. Not tied to any demo subject, so reset_member
        # leaves them intact.
        self.claims.upsert_many(PRECEDENT_CLAIMS)

    def _seed_member(self, profile) -> dict:
        """Upsert one member's baseline bundle (policy + member + claims).

        Baseline is a pre-decision state, so no prior-auth trace is written — the
        demo generates it. `reset_member` still *deletes* any trace created during
        a run, restoring this clean pre-decision baseline.
        """
        bundle = build_bundle(profile)
        self.policies.upsert(bundle["policy"])
        self.members.upsert(bundle["member"])
        self.claims.upsert_many(bundle["claims"])
        return {
            "member_id": profile.member_id,
            "policy": bundle["policy"]["_id"],
            "claims": len(bundle["claims"]),
            "case_type": profile.case_type,
        }

    # --- public operations ---------------------------------------------------

    def seed_canonical(self) -> dict:
        """Load the canonical profiles without wiping anything (idempotent upsert)."""
        self._seed_reference()
        members = [self._seed_member(p) for p in ALL_PROFILES]
        return {
            "reference": {
                "plans": len(PLANS),
                "guidelines": len(GUIDELINES),
                "precedent_claims": len(PRECEDENT_CLAIMS),
            },
            "members": members,
        }

    def reset_all(self) -> dict:
        """Full wipe of the seeded collections, then reseed the canonical set."""
        removed = {}
        for repo in (self.members, self.policies, self.claims,
                     self.audit, self.guidelines, self.plans, self.notifications):
            removed[repo.collection_name] = repo.delete_all()
        seeded = self.seed_canonical()
        return {"removed": removed, "seeded": seeded}

    def reset_member(self, member_id: str) -> dict:
        """Option B reset: restore one member to baseline without touching others.

        Deletes the member's mutation surface (audit-log traces + notifications, and
        claims to drop any added mid-demo), then re-derives the baseline bundle.
        """
        profile = _PROFILES_BY_MEMBER.get(member_id)
        if profile is None:
            raise ValueError(f"No canonical profile for member {member_id}")

        removed = {
            "audit_log": self.audit.delete_by_member(member_id),
            "claims": self.claims.delete_by_member(member_id),
            "notifications": self.notifications.delete_by_member(member_id),
        }
        restored = self._seed_member(profile)
        return {"member_id": member_id, "removed": removed, "restored": restored}

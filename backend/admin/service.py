"""Demo orchestration: seed and reset synthetic data, across both databases.

This is an *orchestration* layer, not a domain: every operation here spans multiple domains
and both databases (insurance records, the shared trace, the clinical profiles and both
reasoning stores), so it composes the domain repositories rather than belonging to any one of
them. It exists to run the demo: it is deliberately the only place allowed to delete
append-only audit rows, and it should be locked down or removed for production.

Baseline data is the JSON fixtures in `seed/fixtures/`, upserted by business key. Reset means:
delete the mutation surface, then re-upsert the baseline. No golden snapshot to maintain.
"""

from clinical.profiles.repository import ProfileRepository
from clinical.reasoning.repository import ClinicalReasoningRepository
from core.repository import Repository
from db.mdb import MongoDBConnector
from insurance.claims.repository import ClaimRepository
from insurance.members.repository import MemberRepository
from insurance.plans.repository import PlanRepository
from insurance.policies.repository import PolicyRepository
from insurance.reasoning.repository import AdminReasoningRepository
from seed import fixtures
from shared.collections import ClinicalCollections
from traces.repository import TraceRepository


class _DispenseRepository(Repository):
    collection_name = ClinicalCollections.DISPENSE_HISTORY
    business_key = "fillId"


class _GuidelineRepository(Repository):
    collection_name = ClinicalCollections.GUIDELINES
    business_key = "guidelineId"


class AdminService:
    """Seed and reset the demo dataset by composing domain repositories."""

    def __init__(self, insurance: MongoDBConnector, clinical: MongoDBConnector):
        # Insurance database
        self.members = MemberRepository(insurance)
        self.policies = PolicyRepository(insurance)
        self.plans = PlanRepository(insurance)
        self.claims = ClaimRepository(insurance)
        self.traces = TraceRepository(insurance)
        self.admin_reasoning = AdminReasoningRepository(insurance)
        # Clinical database
        self.profiles = ProfileRepository(clinical)
        self.dispense = _DispenseRepository(clinical)
        self.guidelines = _GuidelineRepository(clinical)
        self.clinical_reasoning = ClinicalReasoningRepository(clinical)

    # --- reference data ------------------------------------------------------

    def _seed_reference(self) -> dict:
        plans = fixtures.load("plans")
        guidelines = fixtures.load("guidelines")
        self.plans.upsert_many(plans)
        self.guidelines.upsert_many(guidelines)
        # Other members' anonymised precedent claims (`CLM-PREC-*`). Not tied to any demo
        # subject, so `reset_member` leaves them intact.
        precedent = [c for c in fixtures.load("claims") if str(c.get("claimId", "")).startswith("CLM-PREC-")]
        self.claims.upsert_many(precedent)
        return {"plans": len(plans), "guidelines": len(guidelines), "precedent_claims": len(precedent)}

    def _seed_member(self, member: dict, policies: dict, claims: list, profiles: dict, dispense: list) -> dict:
        """Upsert one member's baseline: insurance record, policy, claims, and clinical
        profile and fills. Baseline is pre-decision, so no trace is written: the demo files
        and decides it."""
        member_id = member["memberId"]
        own_claims = [c for c in claims if c.get("memberId") == member_id]
        own_fills = [d for d in dispense if d.get("memberId") == member_id]

        self.policies.upsert(policies[member["policyId"]])
        self.members.upsert(member)
        self.claims.upsert_many(own_claims)
        if member_id in profiles:
            self.profiles.upsert(profiles[member_id])
        self.dispense.upsert_many(own_fills)
        return {
            "member_id": member_id,
            "policy": member["policyId"],
            "claims": len(own_claims),
            "dispense_fills": len(own_fills),
            "has_clinical_profile": member_id in profiles,
        }

    def _baseline(self):
        members = fixtures.load("members")
        policies = {p["policyId"]: p for p in fixtures.load("policies")}
        claims = fixtures.load("claims")
        profiles = {p["memberId"]: p for p in fixtures.load("clinical_profiles")}
        dispense = fixtures.load("dispense_history")
        return members, policies, claims, profiles, dispense

    # --- public operations ---------------------------------------------------

    def seed_canonical(self) -> dict:
        """Load the canonical members and shared catalog without wiping anything
        (idempotent upsert on business keys)."""
        reference = self._seed_reference()
        members, policies, claims, profiles, dispense = self._baseline()
        return {
            "reference": reference,
            "members": [self._seed_member(m, policies, claims, profiles, dispense) for m in members],
        }

    def reset_all(self) -> dict:
        """Full wipe of the seeded collections in both databases, then reseed."""
        removed = {}
        for repo in (
            self.members, self.policies, self.plans, self.claims,
            self.traces, self.admin_reasoning,
            self.profiles, self.dispense, self.guidelines, self.clinical_reasoning,
        ):
            removed[repo.collection_name] = repo.delete_all()
        return {"removed": removed, "seeded": self.seed_canonical()}

    def reset_member(self, member_id: str) -> dict:
        """Restore one member to baseline without touching others.

        Deletes the member's mutation surface in both databases (traces and the reasoning
        text of those traces on each side, claims added mid-demo) and re-upserts the baseline:
        the insurance record (summary back to `none`, 0 open), the clinical profile
        (`pendingActions` back to `pending` with no trace link, the care plan and any
        `gap_reviewed` entry back to baseline), policy, claims and fills.
        """
        members, policies, claims, profiles, dispense = self._baseline()
        member = next((m for m in members if m["memberId"] == member_id), None)
        if member is None:
            raise ValueError(f"No canonical profile for member {member_id}")

        trace_ids = [t["traceId"] for t in self.traces.find_by_subject(member_id)]
        removed = {
            "audit_log": self.traces.delete_by_member(member_id),
            "admin_reasoning": self.admin_reasoning.delete_by({"traceId": {"$in": trace_ids}}),
            "clinical_reasoning": self.clinical_reasoning.delete_by({"traceId": {"$in": trace_ids}}),
            "claims": self.claims.delete_by_member(member_id),
        }
        restored = self._seed_member(member, policies, claims, profiles, dispense)
        return {"member_id": member_id, "removed": removed, "restored": restored}

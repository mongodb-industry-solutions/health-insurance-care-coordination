"""Business logic for policy operations."""

from datetime import date, datetime
from typing import Optional

from db.mdb import get_connector
from plans.repository import PlanRepository
from .repository import PolicyRepository

# Policy.status values that permit coverage. Compared case-insensitively: the
# data model specifies ACTIVE / LAPSED / CANCELLED in upper case, but a status
# that merely differs in case must not read as "not active".
_ACTIVE_STATUS = "active"


def _parse_date(value: str, label: str) -> Optional[date]:
    """Parse a YYYY-MM-DD date. Returns None for an absent value.

    Raises ValueError (-> HTTP 400) on a malformed one, rather than silently
    treating it as absent — an unparseable expiry date must never be mistaken for
    an open-ended policy term.
    """
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"{label} is not a valid YYYY-MM-DD date: {value!r}")


class PolicyService:
    """Service layer for policy-related operations."""

    def __init__(self, connector=None):
        connector = connector or get_connector()
        self.repository = PolicyRepository(connector)
        self.plan_repo = PlanRepository(connector)

    def get_policy(self, policy_id: str) -> Optional[dict]:
        """Retrieve a policy by its policy number (_id); None if not found."""
        return self.repository.get_by_key(policy_id)

    def list_all_policies(self) -> list:
        return self.repository.find()

    def verify_eligibility_on_date(
        self, policy_id: str, service_date: str = None
    ) -> Optional[dict]:
        """Insurance Agent, step 1: the first administrative gate.

        Coverage is active on the date of service only when the policy's `status`
        is ACTIVE *and* the date falls inside `effectivePeriod`. Both conditions
        are checked independently and reported separately, because they fail for
        different reasons a member can act on: a cancelled policy is a different
        conversation from one that simply lapsed before the requested date.

        An absent `expiryDate` is treated as an open-ended term rather than as an
        expiry in the past — the alternative would deny every open-ended policy.

        Returns None when the policy does not exist (-> HTTP 404). Raises
        ValueError on an unparseable date (-> HTTP 400).
        """
        policy = self.repository.get_by_key(policy_id)
        if not policy:
            return None

        as_of_raw = service_date or date.today().isoformat()
        as_of = _parse_date(as_of_raw, "service_date")

        period = policy.get("effectivePeriod") or {}
        effective = _parse_date(period.get("effectiveDate"), "effectivePeriod.effectiveDate")
        expiry = _parse_date(period.get("expiryDate"), "effectivePeriod.expiryDate")

        status = policy.get("status") or ""
        status_active = status.strip().lower() == _ACTIVE_STATUS

        reason = None
        if effective and as_of < effective:
            reason = "policy_not_yet_effective"
            detail = (
                f"Policy {policy_id} does not take effect until {effective.isoformat()}; "
                f"the requested service date {as_of.isoformat()} precedes it. "
                "Not eligible on the date of service."
            )
        elif expiry and as_of > expiry:
            reason = "eligibility_lapsed"
            detail = (
                f"Policy {policy_id} expired {expiry.isoformat()} and the requested "
                f"service date is {as_of.isoformat()}. Coverage was not in force on the "
                f"date of service (policy status: {status or 'unknown'})."
            )
        elif not status_active:
            # Inside the term but not ACTIVE — cancelled mid-term, or lapsed with
            # no expiry date recorded. Distinguish the two: "cancelled" is a
            # deliberate termination, not a term that ran out.
            cancelled = status.strip().lower() == "cancelled"
            reason = "policy_cancelled" if cancelled else "policy_status_not_active"
            detail = (
                f"Policy {policy_id} has status {status or 'unknown'}, which does not "
                f"provide coverage on {as_of.isoformat()}, even though that date falls "
                "inside the recorded policy term."
            )
        else:
            detail = (
                f"Policy {policy_id} is {status} and in force from "
                f"{effective.isoformat() if effective else 'unspecified'} to "
                f"{expiry.isoformat() if expiry else 'open-ended'}; the service date "
                f"{as_of.isoformat()} falls inside the term. Eligible."
            )

        return {
            "eligible": reason is None,
            "reason": reason,
            "policyId": policy.get("policyId", policy_id),
            "planId": policy.get("planId"),
            "serviceDate": as_of.isoformat(),
            "policyStatus": policy.get("status"),
            "effectivePeriod": period or None,
            # A date-and-status comparison against a record already on file. Not a
            # judgement call, so it is reported as near-certain either way; 1.0 is
            # reserved for nothing, since the record itself could be wrong.
            "confidence": 0.99,
            "detail": detail,
        }

    def get_plan_for_policy(self, policy_id: str) -> Optional[dict]:
        """Resolve the Plan a policy is enrolled in (member -> policy -> plan).

        Returns None when the policy does not exist or its plan is missing.
        """
        policy = self.repository.get_by_key(policy_id)
        if not policy:
            return None
        return self.plan_repo.get_by_key(policy.get("planId"))

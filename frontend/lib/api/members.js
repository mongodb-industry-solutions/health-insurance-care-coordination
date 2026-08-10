import { apiFetch } from "./client";

/** GET /api/members/{memberId} — the full member document. */
export function fetchMember(memberId) {
  return apiFetch(`/api/members/${memberId}`);
}

/** GET /api/members/{memberId}/clinical-context — history + eligibility. */
export function fetchClinicalContext(memberId) {
  return apiFetch(`/api/members/${memberId}/clinical-context`);
}

/**
 * POST /api/members/{memberId}/pending-action — advance an action's lifecycle.
 * The backend takes `action_id` and `status` as query params, not a body.
 *
 * This is the entry point into the agent workflow. It only moves the action to
 * `in_progress`; kicking off the agent run itself is a separate concern that
 * does not have a frontend-facing endpoint yet.
 */
export function startPendingAction(memberId, actionId) {
  const params = new URLSearchParams({
    action_id: actionId,
    status: "in_progress",
  });

  return apiFetch(`/api/members/${memberId}/pending-action?${params}`, {
    method: "POST",
  });
}

/** GET /api/policies/{policyId} — effective period, premium, plan id. */
export function fetchPolicy(policyId) {
  return apiFetch(`/api/policies/${policyId}`);
}

/**
 * GET /api/claims/member/{memberId} — the member's claims.
 *
 * #PLACEHOLDER ENDPOINT - Please update once backend has this endpoint implemented
 * There is no out-of-pocket accumulator field anywhere in the backend (searched
 * for amountMet/accumulator/out_of_pocket across `backend/`), so the amount met
 * is derived by summing `memberOwed` on this year's claims. Replace with a real
 * `outOfPocket` field on the policy/plan response if one is added.
 */
export function fetchMemberClaims(memberId) {
  return apiFetch(`/api/claims/member/${memberId}`);
}

/** GET /api/audit/member/{memberId}/traces — prior-authorization decisions. */
export function fetchMemberTraces(memberId) {
  return apiFetch(`/api/audit/member/${memberId}/traces`);
}

/** GET /api/plans/{planId} — carries `coverage.tiers` for the tier cards. */
export function fetchPlan(planId) {
  return apiFetch(`/api/plans/${planId}`);
}

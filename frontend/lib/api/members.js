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
 * Not the way into the agent workflow — `streamAuthorizationRun` in
 * `lib/api/authorization.js` is, and it moves the action itself. This is only
 * for adjusting an action's status directly.
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

/** GET /api/claims/member/{memberId}/refill-gaps — breaks in refill cadence. */
export function fetchRefillGaps(memberId) {
  return apiFetch(`/api/claims/member/${memberId}/refill-gaps`);
}

/** GET /api/plans — every plan, for side-by-side comparison. */
export function fetchPlans() {
  return apiFetch("/api/plans");
}

/**
 * GET /api/audit/traces/{traceId} — one decision trace.
 *
 * Used to expand a claim: the claim carries `linkedAuditTraceId`, so there is no
 * need for a claim-id lookup endpoint.
 */
export function fetchTrace(traceId) {
  return apiFetch(`/api/audit/traces/${traceId}`);
}

/** GET /api/audit/member/{memberId}/traces — prior-authorization decisions. */
export function fetchMemberTraces(memberId) {
  return apiFetch(`/api/audit/member/${memberId}/traces`);
}

/**
 * GET /api/claims/precedent — anonymous price statistics for a therapy, from other
 * members' approved claims: `{count, billed, paid, member_owed}`, each a
 * `{median, min, max}`. The reference price behind the Cost Estimator; nothing in it
 * identifies a claim or a member.
 */
export function fetchPrecedent({ procedureCode, diagnosisCode, memberId }) {
  const params = new URLSearchParams({ procedure_code: procedureCode });
  if (diagnosisCode) params.set("diagnosis_code", diagnosisCode);
  if (memberId) params.set("member_id", memberId);

  return apiFetch(`/api/claims/precedent?${params}`);
}

/** GET /api/plans/{planId} — carries `coverage.tiers` for the tier cards. */
export function fetchPlan(planId) {
  return apiFetch(`/api/plans/${planId}`);
}

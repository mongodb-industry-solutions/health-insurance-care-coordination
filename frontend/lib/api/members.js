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

/** GET /api/plans/{planId}/coverage — used by the Insurance Information tab. */
export function fetchPlanCoverage(planId) {
  return apiFetch(`/api/plans/${planId}/coverage`);
}

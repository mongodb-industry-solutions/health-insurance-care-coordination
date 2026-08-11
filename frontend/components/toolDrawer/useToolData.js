import { useEffect, useState } from "react";
import {
  fetchMemberClaims,
  fetchPlan,
  fetchPlans,
  fetchPolicy,
  fetchRefillGaps,
} from "@/lib/api/members";

/**
 * Loads whatever a given tool needs.
 *
 * There is no single `/tools/{toolId}` endpoint — each tool maps onto routes that
 * already exist in the backend, so nothing here is a placeholder:
 *   claim-history           → /api/claims/member/{id}
 *   recent-care-gaps        → /api/claims/member/{id}/refill-gaps
 *   premium-calculation     → /api/policies/{policyId} + /api/plans/{planId}
 *   plan-comparison         → /api/plans (+ the member's own plan)
 *   clinical-history-review → already on the member document, no request
 *
 * @param {string|null} toolId
 * @param {object|null} member  The loaded member document.
 */
export function useToolData(toolId, member) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const memberId = member?.memberId ?? member?.member_id;
  const policyId = member?.policyId ?? member?.policy_id;

  useEffect(() => {
    if (!toolId) return;

    let active = true;
    setData(null);
    setError(null);

    async function load() {
      setLoading(true);

      try {
        if (toolId === "claim-history") {
          const response = await fetchMemberClaims(memberId);
          if (active) setData({ claims: response.claims ?? [] });
        } else if (toolId === "recent-care-gaps") {
          const response = await fetchRefillGaps(memberId);
          if (active) setData(response);
        } else if (toolId === "premium-calculation") {
          const policy = await fetchPolicy(policyId);
          const planId = policy.planId ?? policy.plan_id;
          const plan = planId ? await fetchPlan(planId) : null;
          if (active) setData({ policy, plan });
        } else if (toolId === "plan-comparison") {
          const policy = await fetchPolicy(policyId);
          const response = await fetchPlans();
          if (active) {
            setData({
              currentPlanId: policy.planId ?? policy.plan_id,
              plans: response.plans ?? [],
            });
          }
        }
        // clinical-history-review reads the member document directly.
      } catch (cause) {
        if (active) setError(cause);
      } finally {
        if (active) setLoading(false);
      }
    }

    load();
    return () => {
      active = false;
    };
  }, [toolId, memberId, policyId]);

  return { data, loading, error };
}

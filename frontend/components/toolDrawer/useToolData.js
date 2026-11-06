import { useEffect, useState } from "react";
import {
  fetchMemberClaims,
  fetchMemberTraces,
  fetchPlan,
  fetchPlans,
  fetchPolicy,
  fetchPrecedent,
} from "@/lib/api/members";
import { resolveTherapy } from "@/lib/costPresenter";
import { findPlanTreatment } from "@/lib/insurancePresenter";

/**
 * Loads whatever a given tool needs.
 *
 * There is no single `/tools/{toolId}` endpoint — each tool maps onto routes that
 * already exist in the backend, so nothing here is a placeholder:
 *   claim-history           → /api/claims/member/{id}
 *   decision-tracing        → /api/audit/member/{id}/traces
 *   premium-calculation     → the Cost Estimator: policy + plan, the member's claims
 *                             and traces, and /api/claims/precedent for a reference price
 *   plan-comparison         → /api/policies/{policyId} + /api/plans/{planId}, plus
 *                             /api/plans for the catalog
 *   clinical-history-review → already on the member document, no request
 *   recent-care-gaps        → nothing; no care-gap object exists (see CareGapsTool)
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
        } else if (toolId === "decision-tracing") {
          const response = await fetchMemberTraces(memberId);
          if (active) setData({ traces: response.traces ?? [] });
        } else if (toolId === "premium-calculation") {
          const policy = await fetchPolicy(policyId);
          const planId = policy.planId ?? policy.plan_id;
          const plan = planId ? await fetchPlan(planId) : null;

          // Claims and traces sharpen the estimate (what is already owed this year,
          // where the request stands) but must not take the tool down with them.
          const [claimsResult, tracesResult] = await Promise.allSettled([
            fetchMemberClaims(memberId),
            fetchMemberTraces(memberId),
          ]);

          // The reference price: what other members were billed for this same therapy.
          const { therapy, diagnosisCode } = resolveTherapy(member);
          const treatment = findPlanTreatment(plan, therapy, diagnosisCode);
          const procedureCode = treatment?.treatmentCode ?? treatment?.treatment_code;
          let precedent = null;
          if (procedureCode) {
            try {
              precedent = await fetchPrecedent({ procedureCode, diagnosisCode, memberId });
            } catch {
              precedent = null; // no price is a smaller estimate, not a broken tool
            }
          }

          if (active) {
            setData({
              policy,
              plan,
              claims:
                claimsResult.status === "fulfilled" ? claimsResult.value.claims ?? [] : [],
              traces:
                tracesResult.status === "fulfilled" ? tracesResult.value.traces ?? [] : [],
              precedent,
            });
          }
        } else if (toolId === "plan-comparison") {
          // Same policy → plan pair, plus the catalog; each drawer entry fetches
          // independently.
          const policy = await fetchPolicy(policyId);
          const planId = policy.planId ?? policy.plan_id;
          const plan = planId ? await fetchPlan(planId) : null;

          // The catalog is only needed for the comparison tool's second section.
          let plans = [];
          if (toolId === "plan-comparison") {
            const catalog = await fetchPlans();
            plans = catalog.plans ?? [];
          }

          if (active) setData({ policy, plan, plans });
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

import { useEffect, useState } from "react";
import {
  fetchMemberClaims,
  fetchMemberTraces,
  fetchPlan,
  fetchPolicy,
} from "@/lib/api/members";

/**
 * Loads the policy for a member, then the plan it points at — the tier table
 * lives on the plan, and only the policy knows which plan that is.
 *
 * Claims are fetched too, only to derive out-of-pocket progress.
 *
 * Runs when the Insurance Information tab first mounts, not on page load.
 *
 * @param {string|undefined} policyId  From the member document.
 * @param {string|undefined} memberId  For the claims lookup.
 */
export function useInsuranceInformation(policyId, memberId) {
  const [policy, setPolicy] = useState(null);
  const [plan, setPlan] = useState(null);
  const [claims, setClaims] = useState([]);
  const [traces, setTraces] = useState([]);
  const [loading, setLoading] = useState(Boolean(policyId));
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!policyId) return;

    let active = true;

    async function load() {
      setLoading(true);
      setError(null);

      try {
        const policyDoc = await fetchPolicy(policyId);
        if (!active) return;
        setPolicy(policyDoc);

        const planId = policyDoc.planId ?? policyDoc.plan_id;
        if (planId) {
          const planDoc = await fetchPlan(planId);
          if (active) setPlan(planDoc);
        }

        // Claims feed only the out-of-pocket bar and traces only the
        // authorization list, so neither failure should take the tab down.
        if (memberId) {
          const [claimsResult, tracesResult] = await Promise.allSettled([
            fetchMemberClaims(memberId),
            fetchMemberTraces(memberId),
          ]);

          if (active && claimsResult.status === "fulfilled") {
            setClaims(claimsResult.value.claims ?? claimsResult.value ?? []);
          }
          if (active && tracesResult.status === "fulfilled") {
            setTraces(tracesResult.value.traces ?? tracesResult.value ?? []);
          }
        }
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
  }, [policyId, memberId]);

  return { policy, plan, claims, traces, loading, error };
}

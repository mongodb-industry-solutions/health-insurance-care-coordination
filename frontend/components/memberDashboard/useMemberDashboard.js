import { useCallback, useEffect, useState } from "react";
import { fetchMember, startPendingAction } from "@/lib/api/members";

/**
 * Loads the member document for the dashboard and drives the "Start Process"
 * call. The member document already carries clinical history, eligibility and
 * pending actions, so one request covers every panel on the page.
 *
 * @param {string} memberId
 */
export function useMemberDashboard(memberId) {
  const [member, setMember] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [startingActionId, setStartingActionId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      setMember(await fetchMember(memberId));
    } catch (cause) {
      setError(cause);
    } finally {
      setLoading(false);
    }
  }, [memberId]);

  useEffect(() => {
    load();
  }, [load]);

  const startProcess = useCallback(
    async (actionId) => {
      setStartingActionId(actionId);

      try {
        await startPendingAction(memberId, actionId);
        // TODO: this only marks the action in_progress. Kicking off the agent
        // run itself has no frontend-facing endpoint yet — confirm with the
        // backend team how the workflow should be triggered from here.
        await load();
      } catch (cause) {
        setError(cause);
      } finally {
        setStartingActionId(null);
      }
    },
    [load, memberId]
  );

  return { member, loading, error, startingActionId, startProcess, reload: load };
}

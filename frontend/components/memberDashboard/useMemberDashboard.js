import { useCallback, useEffect, useState } from "react";
import { fetchMember } from "@/lib/api/members";
import { useAuthorizationRun } from "@/components/authorizationRun/useAuthorizationRun";

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
  const [runningActionId, setRunningActionId] = useState(null);
  const run = useAuthorizationRun();

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

  /**
   * Opens the streaming run. The backend moves the pending action to
   * `in_progress` itself, so there is no separate lifecycle call to make first —
   * doing one would only trip the 409 that guards against concurrent runs.
   *
   * `run.start` resolves when the stream reaches `stopped` or `error`, which is
   * when the member document is worth re-reading.
   *
   * `runningActionId` marks the action as in progress for the whole run — it is
   * deliberately not a button spinner. A run takes 60-120 seconds, and a button
   * held in a loading state that long reads as broken; the overlay and the
   * docked tab are where progress belongs.
   */
  const startProcess = useCallback(
    async (actionId) => {
      setRunningActionId(actionId);

      try {
        await run.start(memberId);
        await load();
      } finally {
        setRunningActionId(null);
      }
    },
    // `run.start` is stable; the rest of `run` changes on every event.
    [load, memberId, run.start] // eslint-disable-line react-hooks/exhaustive-deps
  );

  return {
    member,
    loading,
    error,
    runningActionId,
    startProcess,
    run,
    reload: load,
  };
}

import { useCallback, useState } from "react";
import { fetchTrace } from "@/lib/api/members";

/**
 * Lazily loads the decision trace behind a claim, cached per trace id so
 * collapsing and re-expanding a row doesn't refetch.
 */
export function useClaimTrace() {
  const [traces, setTraces] = useState({});
  const [loadingId, setLoadingId] = useState(null);

  const loadTrace = useCallback(
    async (traceId) => {
      if (!traceId || traces[traceId]) return;

      setLoadingId(traceId);
      try {
        const trace = await fetchTrace(traceId);
        setTraces((current) => ({ ...current, [traceId]: trace }));
      } catch (cause) {
        setTraces((current) => ({ ...current, [traceId]: { error: cause } }));
      } finally {
        setLoadingId(null);
      }
    },
    [traces]
  );

  return { traces, loadingId, loadTrace };
}

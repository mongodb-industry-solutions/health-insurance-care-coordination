import { useEffect, useState } from "react";

/**
 * Wall-clock seconds since the run started, ticking while it is still going.
 *
 * The stream carries no timestamps at all, so elapsed time is measured on the
 * client — it is time-on-screen, not backend processing time. Close enough for
 * the "processed in 20.5s" caption, and the only number available.
 */
export function useElapsed(startedAt, finishedAt) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!startedAt || finishedAt) return;

    const timer = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(timer);
  }, [startedAt, finishedAt]);

  if (!startedAt) return null;
  return ((finishedAt ?? now) - startedAt) / 1000;
}

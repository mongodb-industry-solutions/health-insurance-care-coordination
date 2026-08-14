"use client";

import { useEffect, useState } from "react";
import Icon from "@leafygreen-ui/icon";
import Skeleton from "@/components/skeleton/Skeleton";
import styles from "./CareGapsTool.module.css";

// Long enough to match the feel of the tools that really do fetch.
const SETTLE_MS = 400;

/**
 * Recent Care Gaps — intentionally empty.
 *
 * #PLACEHOLDER ENDPOINT - Please update once backend has this endpoint implemented
 * GET /api/members/{memberId}/care-gaps
 *
 * IMPORTANT: unlike the other tools in this drawer, this one has no corresponding
 * object or field anywhere in the data model — there is no care-gap tracking on
 * Member, Plan, or elsewhere, so nothing is fetched or computed here.
 *
 * Two things to weigh before implementing:
 *   - `GET /api/claims/member/{id}/refill-gaps` does exist and returns real
 *     medication-adherence gaps (see `fetchRefillGaps`). If refill gaps are what
 *     "care gaps" means here, this tool can be wired to that today.
 *   - `backend/seed/generators/profiles.py` refers to "cardiovascular care-gap
 *     measures (e.g. HEDIS CBP) in the care-gaps demo", which suggests a broader
 *     care-gap concept is planned but not yet modeled.
 *
 * If neither is the intent, remove this tool from the grid rather than shipping a
 * permanently-empty placeholder.
 */
export default function CareGapsTool() {
  // The skeleton is for interaction consistency with the other tools; the result
  // is known in advance.
  const [settling, setSettling] = useState(true);

  useEffect(() => {
    const timer = window.setTimeout(() => setSettling(false), SETTLE_MS);
    return () => window.clearTimeout(timer);
  }, []);

  if (settling) return <Skeleton lines={4} />;

  return (
    <div className={styles.empty}>
      <span className={styles.icon}>
        <Icon glyph="Checkmark" size={26} />
      </span>
      <p className={styles.message}>No recent care gaps identified.</p>
    </div>
  );
}

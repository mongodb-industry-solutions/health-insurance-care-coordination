"use client";

import { useEffect, useState } from "react";
import styles from "./OutOfPocketProgress.module.css";

const NEAR_MAX_PERCENT = 90;

/**
 * Out-of-pocket progress for the year. Renders nothing when the data isn't
 * available, so the tab simply omits the block.
 *
 * @param {object|null} props.outOfPocket  From toOutOfPocket(): { percent, label }.
 */
export default function OutOfPocketProgress({ outOfPocket }) {
  // Starts at 0 and widens after mount so the bar visibly fills.
  const [width, setWidth] = useState(0);

  useEffect(() => {
    if (!outOfPocket) return;

    const frame = requestAnimationFrame(() => setWidth(outOfPocket.percent));
    return () => cancelAnimationFrame(frame);
  }, [outOfPocket]);

  if (!outOfPocket) return null;

  const nearMax = outOfPocket.percent >= NEAR_MAX_PERCENT;

  return (
    <div>
      <span className={styles.label}>Out-of-pocket progress</span>

      <div
        className={styles.track}
        role="progressbar"
        aria-valuenow={outOfPocket.percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Out-of-pocket progress"
      >
        <div
          className={`${styles.fill} ${nearMax ? styles.nearMax : ""}`}
          style={{ width: `${width}%` }}
        />
      </div>

      <p className={styles.value}>{outOfPocket.label}</p>
    </div>
  );
}

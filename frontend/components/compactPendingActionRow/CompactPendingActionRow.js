"use client";

import Button from "@leafygreen-ui/button";
import styles from "./CompactPendingActionRow.module.css";

/**
 * A lower-priority pending action, inside the same washed zone as the featured
 * one — the wash represents the zone, not each individual action.
 *
 * @param {string} props.title
 * @param {"high"|"normal"} props.urgency
 * @param {boolean} props.inProgress
 * @param {() => void} props.onStartProcess
 */
export default function CompactPendingActionRow({
  title,
  urgency = "normal",
  inProgress = false,
  onStartProcess,
}) {
  return (
    <div className={styles.row}>
      <span className={styles.label}>
        <span
          className={`${styles.dot} ${urgency === "high" ? styles.dotHigh : ""}`}
        />
        {title}
      </span>

      {inProgress ? (
        <span className={styles.inProgress}>In progress</span>
      ) : (
        <Button variant="default" size="small" onClick={onStartProcess}>
          Start Process
        </Button>
      )}
    </div>
  );
}

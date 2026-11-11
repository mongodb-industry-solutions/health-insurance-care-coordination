"use client";

import Icon from "@leafygreen-ui/icon";
import { outcomeGlyph, toOutcome, toOverallProgress } from "@/lib/processPresenter";
import styles from "./ProcessDock.module.css";

const RADIUS = 9;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/**
 * The minimised process: a tab against the right edge, carrying enough state to
 * be worth glancing at — progress while it runs, the verdict once it lands.
 *
 * Exists because docking does not stop anything. The run continues server-side,
 * so there has to be a way back into it.
 *
 * @param {object} props.run  From useAuthorizationRun().
 * @param {string} props.title
 * @param {() => void} props.onOpen
 * @param {() => void} props.onDismiss
 */
export default function ProcessDock({ run, title, onOpen, onDismiss }) {
  const settled = run.status === "finished" || run.status === "error";
  const overall = toOverallProgress(run);
  const outcome = settled ? toOutcome(run) : null;

  return (
    <div className={`${styles.dock} ${(outcome && styles[outcome.tone]) || ""}`}>
      <button
        type="button"
        className={styles.open}
        onClick={onOpen}
        aria-label={`Reopen ${title}`}
      >
        <span className={styles.ring}>
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle className={styles.ringTrack} cx="12" cy="12" r={RADIUS} />
            <circle
              className={styles.ringFill}
              cx="12"
              cy="12"
              r={RADIUS}
              strokeDasharray={CIRCUMFERENCE}
              strokeDashoffset={CIRCUMFERENCE * (1 - overall / 100)}
            />
          </svg>
          {settled ? (
            <Icon
              className={styles.ringIcon}
              glyph={outcomeGlyph(outcome.tone)}
              size={11}
            />
          ) : (
            <span className={styles.ringValue}>{overall}</span>
          )}
        </span>

        <span className={styles.text}>
          <span className={styles.label}>{title}</span>
          <span className={styles.status}>
            {settled ? outcome.badge : "running"}
            {!settled && <span className={styles.dot} aria-hidden="true" />}
          </span>
        </span>

        <Icon glyph="ChevronLeft" size={14} className={styles.chevron} />
      </button>

      <button
        type="button"
        className={styles.dismiss}
        onClick={onDismiss}
        aria-label="Dismiss process"
        title="Dismiss — the run is not cancelled"
      >
        <Icon glyph="X" size={12} />
      </button>
    </div>
  );
}

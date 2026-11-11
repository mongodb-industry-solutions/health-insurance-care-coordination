"use client";

import Icon from "@leafygreen-ui/icon";
import { agentLabelOf, toStepRows } from "@/lib/processPresenter";
import styles from "./ProcessStepper.module.css";

/**
 * The three agent turns as a compact rail: where the run is, at a glance.
 *
 * Deliberately holds no log output. The reasoning text lives in one continuous
 * stream beside this, because splitting it into three per-stage boxes meant
 * three cramped scrollers and no way to read the run as a single narrative.
 *
 * @param {object} props.run  From useAuthorizationRun().
 */
export default function ProcessStepper({ run }) {
  const rows = toStepRows(run);

  return (
    <ol className={styles.stages}>
      {rows.map((row) => (
        <li
          key={row.action}
          className={`${styles.stage} ${styles[row.state] ?? ""}`}
          aria-current={row.state === "running" ? "step" : undefined}
        >
          <div className={styles.top}>
            <span className={styles.badge}>
              {row.state === "complete" ? (
                <Icon glyph="Checkmark" size={11} />
              ) : row.state === "error" ? (
                <Icon glyph="Warning" size={11} />
              ) : (
                row.number
              )}
            </span>

            <span className={styles.title}>{row.title}</span>

            {row.state === "running" && (
              <span className={styles.dot} aria-hidden="true" />
            )}
          </div>

          <div
            className={`${styles.track} ${
              row.progress.indeterminate ? styles.trackSweep : ""
            }`}
            role="progressbar"
            aria-label={`${row.title} progress`}
            aria-valuenow={
              row.progress.indeterminate
                ? undefined
                : Math.round(row.progress.value)
            }
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <span
              className={styles.fill}
              style={
                row.progress.indeterminate
                  ? undefined
                  : { width: `${row.progress.value}%` }
              }
            />
          </div>

          <div className={styles.foot}>
            <span className={styles.agent}>
              {row.turn ? agentLabelOf(row.turn.agent) : agentLabelOf(row.agent)}
            </span>
            <span className={styles.state}>
              {row.state === "running"
                ? "live"
                : row.state === "complete"
                  ? "done"
                  : row.state === "error"
                    ? "failed"
                    : row.state === "skipped"
                      ? "not required"
                      : "queued"}
              {row.countLabel ? ` · ${row.countLabel}` : ""}
            </span>
          </div>
        </li>
      ))}
    </ol>
  );
}

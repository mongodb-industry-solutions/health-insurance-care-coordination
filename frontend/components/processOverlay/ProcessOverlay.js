"use client";

import { useCallback, useEffect } from "react";
import Icon from "@leafygreen-ui/icon";
import AgentNetwork from "@/components/agentNetwork/AgentNetwork";
import ProcessCompletionCard from "@/components/processCompletion/ProcessCompletionCard";
import ProcessStepper from "@/components/processStepper/ProcessStepper";
import ReasoningStream from "@/components/reasoningStream/ReasoningStream";
import { toOverallProgress } from "@/lib/processPresenter";
import { useElapsed } from "./useElapsed";
import styles from "./ProcessOverlay.module.css";

/**
 * The process, opened over the dashboard on a blurred backdrop.
 *
 * Dismissing it while the run is still going *docks* rather than closes: the run
 * is server-side and cannot be cancelled from here, so pretending it stopped
 * would be a lie. Once the run has settled there is nothing left to watch, and
 * the same affordance dismisses it for good.
 *
 * @param {object} props.run  From useAuthorizationRun().
 * @param {string} props.title  The pending action's label.
 * @param {string} props.patientLine  One line of context, since the dashboard
 *   behind is blurred out.
 * @param {() => void} props.onDock  Collapse to the docked tab.
 * @param {() => void} props.onDismiss  Close for good.
 */
export default function ProcessOverlay({
  run,
  title,
  patientLine,
  onDock,
  onDismiss,
}) {
  const running = run.turns.find((turn) => turn.status === "running");
  const settled = run.status === "finished" || run.status === "error";
  const overall = toOverallProgress(run);
  const elapsed = useElapsed(run.startedAt, run.finishedAt);

  const requestClose = useCallback(() => {
    if (settled) onDismiss?.();
    else onDock?.();
  }, [settled, onDismiss, onDock]);

  useEffect(() => {
    const handleKeyDown = (event) => {
      if (event.key === "Escape") requestClose();
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [requestClose]);

  return (
    <>
      <div className={styles.backdrop} onClick={requestClose} />

      <div className={styles.wrap}>
        <section
          className={styles.panel}
          role="dialog"
          aria-modal="true"
          aria-label={title}
        >
          <header className={styles.header}>
            <div className={styles.headTop}>
              <div className={styles.headings}>
                <h2 className={styles.title}>{title}</h2>
                {patientLine && (
                  <p className={styles.patient}>{patientLine}</p>
                )}
              </div>

              <div className={styles.headMeta}>
                {elapsed !== null && (
                  <span className={styles.elapsed}>{elapsed.toFixed(1)}s</span>
                )}
                {run.traceId && (
                  <span className={styles.trace}>{run.traceId}</span>
                )}
                <button
                  type="button"
                  className={styles.close}
                  onClick={requestClose}
                  aria-label={settled ? "Close" : "Minimise to the side"}
                  title={settled ? "Close" : "Minimise — the run keeps going"}
                >
                  <Icon glyph={settled ? "X" : "ChevronRight"} size={18} />
                </button>
              </div>
            </div>

            <div className={styles.overall}>
              <div
                className={styles.overallTrack}
                role="progressbar"
                aria-label="Overall process progress"
                aria-valuenow={overall}
                aria-valuemin={0}
                aria-valuemax={100}
              >
                <span
                  className={styles.overallFill}
                  style={{ width: `${overall}%` }}
                />
              </div>
              <span className={styles.overallValue}>{overall}%</span>
            </div>
          </header>

          <div className={styles.body}>
            {/* Where the run is: topology, then the three stages. */}
            <aside className={styles.side}>
              <AgentNetwork activeAgent={running?.agent ?? null} />
              <ProcessStepper run={run} />
            </aside>

            {/* What the run said: one transcript, its own scroller. */}
            <div className={styles.main}>
              <ReasoningStream run={run} />

              {settled && (
                <div className={styles.outcome}>
                  <ProcessCompletionCard run={run} onReview={onDismiss} />
                  <div className={styles.footer}>
                    <button
                      type="button"
                      className={styles.backLink}
                      onClick={onDismiss}
                    >
                      Go back to main page →
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </section>
      </div>
    </>
  );
}

"use client";

import AgentNetwork from "@/components/agentNetwork/AgentNetwork";
import PatientIdentityCard from "@/components/patientIdentityCard/PatientIdentityCard";
import ProcessCompletionCard from "@/components/processCompletion/ProcessCompletionCard";
import ProcessStepper from "@/components/processStepper/ProcessStepper";
import { toOverallProgress } from "@/lib/processPresenter";
import { useElapsed } from "./useElapsed";
import styles from "./ProcessView.module.css";

/**
 * The screen that takes over the content area once "Start Process" is clicked.
 * Runs itself: there is nothing to press, and the only navigation is back to the
 * dashboard.
 *
 * Going back does not cancel anything — the run is server-side and this state
 * lives in `useMemberDashboard`, above this component, so returning mid-run
 * picks the live stream back up where it is.
 *
 * @param {object} props.run  From useAuthorizationRun().
 * @param {object} props.member  Raw member document.
 * @param {object} props.profile  Local MEMBERS entry, for the avatar.
 * @param {string} props.title  The pending action's label.
 * @param {() => void} props.onBack
 */
export default function ProcessView({ run, member, profile, title, onBack }) {
  const running = run.turns.find((turn) => turn.status === "running");
  const settled = run.status === "finished" || run.status === "error";
  const overall = toOverallProgress(run);
  const elapsed = useElapsed(run.startedAt, run.finishedAt);

  return (
    <div className={styles.backdrop}>
      <div className={styles.card}>
        <div className={styles.layout}>
          <aside className={styles.left}>
            <PatientIdentityCard member={member} profile={profile} />
            <AgentNetwork activeAgent={running?.agent ?? null} />
          </aside>

          <div className={styles.right}>
            <header className={styles.header}>
              <div className={styles.headTop}>
                <h2 className={styles.title}>{title}</h2>

                <div className={styles.headMeta}>
                  {elapsed !== null && (
                    <span className={styles.elapsed}>
                      {elapsed.toFixed(1)}s
                    </span>
                  )}
                  {run.traceId && (
                    <span className={styles.trace}>{run.traceId}</span>
                  )}
                  {!settled && (
                    <button
                      type="button"
                      className={styles.back}
                      onClick={onBack}
                    >
                      ← Go back
                    </button>
                  )}
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

            <ProcessStepper run={run} />

            {settled && (
              <>
                <ProcessCompletionCard run={run} onReview={onBack} />
                <div className={styles.footer}>
                  <button
                    type="button"
                    className={styles.back}
                    onClick={onBack}
                  >
                    Go back to main page →
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

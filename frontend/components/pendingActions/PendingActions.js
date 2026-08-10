"use client";

import Button from "@leafygreen-ui/button";
import styles from "./PendingActions.module.css";

/**
 * The member's open pending actions. "Start Process" is the entry point into
 * the agent workflow.
 *
 * @param {Array} props.actions  From toPendingActions().
 * @param {(actionId: string) => void} props.onStartProcess
 * @param {string|null} props.startingActionId  Action currently being started.
 */
export default function PendingActions({
  actions = [],
  onStartProcess,
  startingActionId,
}) {
  return (
    <section className={styles.card}>
      <h2 className={styles.title}>Pending Actions</h2>

      {actions.length === 0 ? (
        <p className={styles.empty}>Nothing pending for this member.</p>
      ) : (
        <div className={styles.list}>
          {actions.map((action) => (
            <div key={action.id} className={styles.row}>
              <span className={styles.rowLabel}>{action.label}</span>

              {action.status === "in_progress" ? (
                <span className={styles.inProgress}>In progress</span>
              ) : (
                <Button
                  variant="primary"
                  isLoading={startingActionId === action.id}
                  onClick={() => onStartProcess?.(action.id)}
                >
                  Start Process
                </Button>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

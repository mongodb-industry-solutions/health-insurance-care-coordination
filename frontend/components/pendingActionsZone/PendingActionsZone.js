"use client";

import CompactPendingActionRow from "@/components/compactPendingActionRow/CompactPendingActionRow";
import FeaturedPendingAction from "@/components/featuredPendingAction/FeaturedPendingAction";
import styles from "./PendingActionsZone.module.css";

const URGENCY_RANK = { high: 0, normal: 1 };

/** Most urgent first, then most recently raised. */
function byPriority(a, b) {
  const urgency =
    (URGENCY_RANK[a.urgency] ?? 1) - (URGENCY_RANK[b.urgency] ?? 1);
  if (urgency !== 0) return urgency;

  return String(b.raisedAt ?? "").localeCompare(String(a.raisedAt ?? ""));
}

/**
 * The pending-actions zone: a color-washed region rather than a card, holding
 * one featured action plus any others as compact rows.
 *
 * @param {Array} props.actions  From toPendingActions().
 * @param {string|null} props.startingActionId
 * @param {(actionId: string) => void} props.onStartProcess
 */
export default function PendingActionsZone({
  actions = [],
  startingActionId,
  onStartProcess,
}) {
  const sorted = [...actions].sort(byPriority);
  const [featured, ...rest] = sorted;

  return (
    <section className={styles.zone}>
      <div className={styles.content}>
        <h2 className={styles.title}>Pending Actions</h2>

        {!featured ? (
          <p className={styles.empty}>Nothing pending for this member.</p>
        ) : (
          <>
            <FeaturedPendingAction
              title={featured.label}
              context={featured.context}
              urgency={featured.urgency}
              inProgress={featured.status === "in_progress"}
              isLoading={startingActionId === featured.id}
              onStartProcess={() => onStartProcess?.(featured.id)}
            />

            {rest.length > 0 && (
              <div className={styles.compactList}>
                {rest.map((action) => (
                  <CompactPendingActionRow
                    key={action.id}
                    title={action.label}
                    urgency={action.urgency}
                    inProgress={action.status === "in_progress"}
                    isLoading={startingActionId === action.id}
                    onStartProcess={() => onStartProcess?.(action.id)}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}

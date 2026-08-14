"use client";

import Button from "@leafygreen-ui/button";
import Icon from "@leafygreen-ui/icon";
import { formatElapsed, toOutcome } from "@/lib/processPresenter";
import styles from "./ProcessCompletionCard.module.css";

/**
 * The verdict, rendered once the run reaches a terminal event.
 *
 * Carries no reasoning log of its own — the transcript beside it already holds
 * every line, and a second copy behind a toggle would only invite the two to
 * disagree.
 *
 * @param {object} props.run  From useAuthorizationRun().
 * @param {() => void} [props.onReview]  Only used by the escalated outcome.
 */
export default function ProcessCompletionCard({ run, onReview }) {
  const outcome = toOutcome(run);
  const elapsed = formatElapsed(run.startedAt, run.finishedAt);

  return (
    <section className={`${styles.card} ${styles[outcome.tone]}`}>
      <div className={styles.head}>
        <div>
          <h3 className={styles.title}>{outcome.title}</h3>
          <p className={styles.caption}>
            {elapsed ? `Processed in ${elapsed}` : "Processed"}
            {run.traceId ? ` · ${run.traceId}` : ""}
          </p>
        </div>

        {/* Not colour alone: the badge carries an icon and a word. */}
        <span className={styles.badge}>
          <Icon
            glyph={outcome.tone === "success" ? "Checkmark" : "Warning"}
            size={12}
          />
          {outcome.badge}
        </span>
      </div>

      <p className={styles.detail}>{outcome.detail}</p>

      {outcome.cta && (
        <Button
          className={styles.cta}
          variant="primary"
          size="small"
          onClick={onReview}
        >
          {outcome.cta}
        </Button>
      )}
    </section>
  );
}

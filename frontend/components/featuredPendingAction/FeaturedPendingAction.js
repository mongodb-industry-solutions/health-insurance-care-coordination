"use client";

import Button from "@leafygreen-ui/button";
import Icon from "@leafygreen-ui/icon";
import styles from "./FeaturedPendingAction.module.css";

/**
 * The top pending action, given the full treatment: urgency tag, large title,
 * context line, and the dominant CTA of the whole interface.
 *
 * @param {string} props.title
 * @param {string} props.context  One line on why the action exists.
 * @param {"high"|"normal"} props.urgency
 * @param {boolean} props.inProgress  Already started — no CTA.
 * @param {boolean} props.isLoading
 * @param {() => void} props.onStartProcess
 */
export default function FeaturedPendingAction({
  title,
  context,
  urgency = "normal",
  inProgress = false,
  isLoading = false,
  onStartProcess,
}) {
  return (
    <div>
      <div className={styles.urgency}>
        <span
          className={`${styles.dot} ${urgency === "high" ? styles.dotHigh : ""}`}
        />
        <span className={styles.urgencyLabel}>
          {inProgress ? "In progress" : "Action needed"}
        </span>
      </div>

      <h3 className={styles.title}>{title}</h3>
      {context && <p className={styles.context}>{context}</p>}

      {inProgress ? (
        <p className={styles.inProgress}>
          This case is open and awaiting a medical director.
        </p>
      ) : (
        <div className={styles.cta}>
          <Button
            className={styles.ctaButton}
            variant="primary"
            size="large"
            isLoading={isLoading}
            rightGlyph={<Icon glyph="ArrowRight" />}
            onClick={onStartProcess}
          >
            Start Process
          </Button>
        </div>
      )}
    </div>
  );
}

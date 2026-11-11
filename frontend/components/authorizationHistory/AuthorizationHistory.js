import styles from "./AuthorizationHistory.module.css";

/** Pill tint per decision. Anything unrecognized reads as pending. */
function decisionClass(rawDecision) {
  const decision = String(rawDecision ?? "").toLowerCase();

  if (decision.includes("approved")) return styles.approved;
  if (decision.includes("denied")) return styles.denied;
  return styles.pending;
}

/**
 * Past prior-authorization decisions for the member. Distinct from the Claim
 * History tool — an authorization decision is not a claim.
 *
 * @param {Array} props.entries  From toAuthorizationHistory().
 */
export default function AuthorizationHistory({ entries = [] }) {
  if (!entries.length) {
    return <p className={styles.empty}>No prior authorizations on record.</p>;
  }

  return (
    <ul className={styles.list}>
      {entries.map((entry) => (
        <li key={entry.id} className={styles.row}>
          <span className={styles.service}>
            {entry.service ?? "Prior authorization"}
            <span className={styles.date}>
              {[entry.date, entry.routedToHuman && "medical director review"]
                .filter(Boolean)
                .join(" · ")}
            </span>
          </span>

          {entry.decision && (
            <span
              className={`${styles.decision} ${decisionClass(entry.rawDecision)}`}
            >
              {entry.decision}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

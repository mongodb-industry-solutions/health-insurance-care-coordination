import styles from "./RequestedTreatmentCoverage.module.css";

/**
 * How the plan treats the therapy the member is waiting on: tier, prior-auth
 * requirement, and the cost of each treatment step. Renders nothing when the
 * plan has no matching treatment.
 *
 * @param {object|null} props.treatment  From toRequestedTreatment().
 */
export default function RequestedTreatmentCoverage({ treatment }) {
  if (!treatment) return null;

  const flags = [
    treatment.covered ? "Covered" : "Not covered",
    treatment.priorAuthRequired ? "prior auth required" : "no prior auth",
  ].join(" · ");

  return (
    <div className={styles.block}>
      <div className={styles.header}>
        <h4 className={styles.name}>{treatment.name}</h4>
        {treatment.tier && <span className={styles.tier}>{treatment.tier} tier</span>}
      </div>

      <p className={`${styles.flags} ${treatment.covered ? "" : styles.notCovered}`}>
        {flags}
      </p>

      {treatment.steps.length > 0 && (
        <ul className={styles.steps}>
          {treatment.steps.map((step) => (
            <li key={step.id} className={styles.step}>
              <span className={styles.stepName}>{step.name}</span>
              {step.cost && <span className={styles.stepCost}>{step.cost}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

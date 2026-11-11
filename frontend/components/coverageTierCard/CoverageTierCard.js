import styles from "./CoverageTierCard.module.css";

/**
 * One coverage tier. A single template for every tier — `isActive` switches to
 * the green border/title treatment for the member's own tier.
 *
 * @param {string} props.title
 * @param {boolean} props.isActive
 * @param {string} props.priorAuthLabel
 * @param {string} props.costLine
 */
export default function CoverageTierCard({
  title,
  isActive = false,
  priorAuthLabel,
  costLine,
}) {
  const detailClass = `${styles.detail} ${isActive ? styles.activeDetail : ""}`;

  return (
    <div className={`${styles.card} ${isActive ? styles.active : ""}`}>
      <h4 className={`${styles.title} ${isActive ? styles.activeTitle : ""}`}>
        {title}
      </h4>
      <p className={detailClass}>{priorAuthLabel}</p>
      <p className={detailClass}>{costLine}</p>
    </div>
  );
}

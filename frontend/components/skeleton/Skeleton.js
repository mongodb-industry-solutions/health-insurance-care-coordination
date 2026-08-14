import styles from "./Skeleton.module.css";

/** Placeholder lines shown while drawer content loads. */
export default function Skeleton({ lines = 6 }) {
  return (
    <div className={styles.stack} aria-hidden="true">
      {Array.from({ length: lines }).map((_, index) => (
        <div
          key={index}
          className={styles.line}
          // Ragged widths read as text rather than a table.
          style={{ width: `${[100, 82, 91, 68, 95, 76][index % 6]}%` }}
        />
      ))}
    </div>
  );
}

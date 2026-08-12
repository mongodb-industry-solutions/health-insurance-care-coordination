import styles from "./ComparisonTable.module.css";

/**
 * Attribute rows × columns. Column-count agnostic, so a future cross-plan
 * endpoint can pass more than the two tiers on the member's own plan.
 *
 * @param {Array} props.columns  [{ id, label, isCurrent, tier }]
 * @param {Array} props.rows  [{ id, label, value: (tier) => string }]
 * @param {string} props.attributeLabel  Header for the leading column.
 */
export default function ComparisonTable({
  columns = [],
  rows = [],
  attributeLabel = "",
}) {
  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th className={styles.attributeHead} scope="col">
            {attributeLabel}
          </th>
          {columns.map((column) => (
            <th
              key={column.id}
              scope="col"
              className={`${styles.columnHead} ${
                column.isCurrent ? styles.columnHeadCurrent : ""
              }`}
            >
              {column.label}
            </th>
          ))}
        </tr>
      </thead>

      <tbody>
        {rows.map((row) => (
          <tr key={row.id} className={styles.row}>
            <th className={styles.attribute} scope="row">
              {row.label}
            </th>
            {columns.map((column) => (
              <td
                key={column.id}
                className={`${styles.cell} ${
                  column.isCurrent ? styles.cellCurrent : ""
                }`}
              >
                {row.value(column.tier)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

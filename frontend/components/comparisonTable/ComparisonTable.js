import styles from "./ComparisonTable.module.css";

/**
 * Grouped rows × columns. Column-count agnostic, so a future cross-plan endpoint
 * can pass more than the two tiers on the member's own plan.
 *
 * @param {Array} props.columns  [{ id, label, isCurrent, tier }]
 * @param {Array} props.groups  [{ id, label, code, rows: [{ id, label, ... }] }]
 * @param {(row, column) => ReactNode} props.renderCell
 * @param {string} props.attributeLabel  Header for the leading column.
 */
export default function ComparisonTable({
  columns = [],
  groups = [],
  renderCell,
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

      {groups.map((group, groupIndex) => (
        <tbody key={group.id} className={styles.group}>
          {group.label && (
            <tr>
              <th
                className={styles.groupHead}
                colSpan={columns.length + 1}
                scope="colgroup"
              >
                {group.label}
                {group.code && <span className={styles.groupCode}>{group.code}</span>}
              </th>
            </tr>
          )}

          {group.rows.map((row, rowIndex) => {
            // Closes the highlighted column's outline on the very last row.
            const isLastRow =
              groupIndex === groups.length - 1 &&
              rowIndex === group.rows.length - 1;

            return (
              <tr key={row.id} className={styles.row}>
                <th className={styles.attribute} scope="row">
                  {row.label}
                </th>
                {columns.map((column) => (
                  <td
                    key={column.id}
                    className={`${styles.cell} ${
                      column.isCurrent ? styles.cellCurrent : ""
                    } ${isLastRow ? styles.cellLast : ""}`}
                  >
                    {renderCell(row, column)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      ))}
    </table>
  );
}

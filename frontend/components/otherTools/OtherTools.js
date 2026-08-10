"use client";

import { TOOL_CATEGORIES, getToolsByCategory } from "@/lib/const/tools";
import styles from "./OtherTools.module.css";

/**
 * Secondary tool launchers, grouped by category. Pill tint and tag text both
 * come from the tool's `category`, so adding a tool is a data-only change.
 *
 * @param {(tool: object) => void} props.onOpenTool
 */
export default function OtherTools({ onOpenTool }) {
  return (
    <section className={styles.section}>
      <h2 className={styles.title}>Other Tools</h2>
      <hr className={styles.divider} />

      {TOOL_CATEGORIES.map((category) => (
        <div key={category.id} className={styles.group}>
          <h3 className={styles.groupLabel}>{category.label}</h3>

          <div className={styles.list}>
            {getToolsByCategory(category.id).map((tool) => (
              <button
                key={tool.id}
                type="button"
                className={`${styles.row} ${styles[category.id]}`}
                onClick={() => onOpenTool?.(tool)}
              >
                <span className={styles.rowLabel}>{tool.label}</span>
                <span className={styles.tag}>{category.tag}</span>
              </button>
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}

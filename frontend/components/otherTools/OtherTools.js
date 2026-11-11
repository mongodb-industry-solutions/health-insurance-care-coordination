"use client";

import Icon from "@leafygreen-ui/icon";
import { TOOL_CATEGORIES, TOOLS, getToolsByCategory } from "@/lib/const/tools";
import styles from "./OtherTools.module.css";

const STAGGER_MS = 50;

/**
 * Secondary tool launchers, grouped by category. Tile tint and icon accent come
 * from the tool's `category`, so adding a tool is a data-only change. The
 * category is carried by tint alone here — the inline tag text would truncate at
 * tile width, and the group heading already names it.
 *
 * @param {(tool: object) => void} props.onOpenTool  Opens the tool drawer.
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
                // Cascade follows the tool's position across the whole section,
                // so the second group continues the first rather than restarting.
                style={{
                  animationDelay: `${TOOLS.indexOf(tool) * STAGGER_MS}ms`,
                }}
                onClick={() => onOpenTool?.(tool)}
              >
                <span className={styles.icon}>
                  <Icon glyph={tool.icon} size={21} />
                </span>
                <span className={styles.rowLabel}>{tool.label}</span>
                <span className={styles.chevron}>
                  <Icon glyph="ChevronRight" size={14} />
                </span>
              </button>
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}

"use client";

import Icon from "@leafygreen-ui/icon";
import ToolContent from "./ToolContent";
import { useToolDrawer } from "./useToolDrawer";
import styles from "./ToolDrawer.module.css";

/**
 * Right-side drawer for a tool's detail view. Distinct from the onboarding
 * carousel on purpose: this is a supplementary lookup, so click-outside and
 * Escape both dismiss it.
 *
 * @param {object|null} props.tool  The tool being viewed; null closes the drawer.
 * @param {object} props.member  The loaded member document.
 * @param {() => void} props.onClose
 */
export default function ToolDrawer({ tool, member, onClose }) {
  const { leaving, requestClose } = useToolDrawer(Boolean(tool), onClose);

  if (!tool) return null;

  return (
    <>
      <div
        className={`${styles.backdrop} ${leaving ? styles.backdropLeaving : ""}`}
        onClick={requestClose}
      />

      <aside
        className={`${styles.panel} ${leaving ? styles.panelLeaving : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={tool.label}
      >
        <div className={styles.header}>
          <div className={styles.heading}>
            <span className={styles.headingIcon}>
              <Icon glyph={tool.icon} size={24} />
            </span>
            <h2 className={styles.title}>{tool.label}</h2>
          </div>

          <button
            type="button"
            className={styles.close}
            onClick={requestClose}
            aria-label="Close"
          >
            <Icon glyph="X" size={18} />
          </button>
        </div>

        <div className={styles.body}>
          <ToolContent toolId={tool.id} member={member} />
        </div>
      </aside>
    </>
  );
}

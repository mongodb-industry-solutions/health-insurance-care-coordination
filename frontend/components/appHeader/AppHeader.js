"use client";

import Icon from "@leafygreen-ui/icon";
import styles from "./AppHeader.module.css";

function MongoLeaf() {
  return (
    <svg
      className={styles.leaf}
      viewBox="0 0 22 26"
      width="22"
      height="26"
      aria-hidden="true"
      focusable="false"
    >
      <path
        fill="#ffffff"
        d="M11 0S7.1 4.2 5.4 7.3C2.6 12.4 3.4 17 6.4 20c1.3 1.3 2.9 2.2 3.7 3.3l.5 2.7h.8l.5-2.7c.8-1.1 2.4-2 3.7-3.3 3-3 3.8-7.6 1-12.7C14.9 4.2 11 0 11 0zm.1 21.6c-.2-4.6-.3-13.7-.1-18.1 1.3 2.3 3.6 6.6 4 10 .5 3.8-1.7 6.7-3.9 8.1z"
      />
    </svg>
  );
}

/**
 * Top bar of the main app: brand on the left, session actions on the right.
 *
 * @param {() => void} props.onLogOut
 * @param {() => void} props.onOpenSettings
 */
export default function AppHeader({ onLogOut, onOpenSettings }) {
  return (
    <header className={styles.header}>
      <div className={styles.brand}>
        <MongoLeaf />
        <span className={styles.wordmark}>Leafy Health Insurance Platform</span>
      </div>

      <div className={styles.actions}>
        <button type="button" className={styles.action} onClick={onLogOut}>
          <span className={`${styles.actionIcon} ${styles.actionIconFilled}`}>
            <Icon glyph="ArrowRight" size={20} />
          </span>
          <span className={styles.actionLabel}>Log Out</span>
        </button>

        <button
          type="button"
          className={styles.action}
          onClick={onOpenSettings}
        >
          <span className={styles.actionIcon}>
            <Icon glyph="Settings" size={20} />
          </span>
          <span className={styles.actionLabel}>Settings</span>
        </button>
      </div>
    </header>
  );
}

import Image from "next/image";
import styles from "./Header.module.css";

/** Placeholder nav items until the real destinations exist. */
const DEFAULT_NAV_ITEMS = [
  { label: "About", href: "/about" },
];

/**
 * `action` is an optional prominent button, e.g. { label: "Go back to Demo", href: "/", back: true }.
 * `back` adds a leading arrow, `forward` a trailing one.
 */
export default function Header({ navItems = DEFAULT_NAV_ITEMS, action }) {
  return (
    <header className={styles.header}>
      <a className={styles.logo} href="/">
        <Image
          className={styles.logoImage}
          src="/MongoDB_ForestGreen.png"
          alt="MongoDB"
          width={132}
          height={32}
          priority
        />
      </a>

      <nav className={styles.nav} aria-label="Main">
        {navItems.map((item) => (
          <a key={item.label} className={styles.navLink} href={item.href}>
            {item.label}
          </a>
        ))}
        {action && (
          <a
            className={`${styles.actionBtn} ${action.subtle ? styles.actionBtnSubtle : ""}`}
            href={action.href}
          >
            {action.back && <span aria-hidden="true">←</span>}
            {action.label}
            {action.forward && <span aria-hidden="true">→</span>}
          </a>
        )}
      </nav>
    </header>
  );
}

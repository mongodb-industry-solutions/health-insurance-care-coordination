import Image from "next/image";
import styles from "./Header.module.css";

/** Placeholder nav items until the real destinations exist. */
const DEFAULT_NAV_ITEMS = [
  { label: "About", href: "#" },
  { label: "Support", href: "#" },
  { label: "Contact", href: "#" },
];

export default function Header({ navItems = DEFAULT_NAV_ITEMS }) {
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
      </nav>
    </header>
  );
}

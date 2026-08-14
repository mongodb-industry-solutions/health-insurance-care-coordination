import Image from "next/image";
import { toIdentityRows } from "@/lib/memberPresenter";
import styles from "./PatientIdentityCard.module.css";

/**
 * Patient identity summary: avatar, name, and the label/value field list.
 *
 * @param {object} props.member  Raw member document from the API (may be null while loading).
 * @param {object} props.profile  The local MEMBERS entry, for the avatar and name fallback.
 */
export default function PatientIdentityCard({ member, profile }) {
  const rows = toIdentityRows(member);
  const name = member
    ? `${member.firstName} ${member.lastName}`
    : profile.name;

  return (
    <section className={styles.card}>
      <Image
        className={styles.avatar}
        src={profile.avatar}
        alt=""
        width={92}
        height={124}
      />

      <div className={styles.details}>
        <h2 className={styles.name}>{name}</h2>

        <dl className={styles.rows}>
          {rows.map((row) => (
            <div key={row.label} style={{ display: "contents" }}>
              <dt className={styles.label}>{row.label}</dt>
              <dd
                className={`${styles.value} ${row.value ? "" : styles.missing}`}
              >
                {row.value ?? "Not on file"}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}

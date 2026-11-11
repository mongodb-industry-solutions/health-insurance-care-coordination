import Badge from "@leafygreen-ui/badge";
import { CASE_TYPE_BADGES, getAge } from "@/lib/const/members";
import styles from "./MemberInfoCard.module.css";

/**
 * Info card shown while a member card is hovered or focused. Rendered inside
 * the member card wrapper, which owns the positioning context.
 *
 * @param {object} props.member  One entry of MEMBERS.
 * @param {boolean} props.flipped  Right-align instead of left-align (collision).
 */
export default function MemberInfoCard({ member, flipped = false }) {
  const badge = CASE_TYPE_BADGES[member.caseType];

  return (
    <div
      className={`${styles.card} ${flipped ? styles.flipped : ""}`}
      role="tooltip"
      id={`member-info-${member.memberId}`}
    >
      <p className={styles.title}>
        {member.firstName} - {getAge(member.birthDate)}, {member.gender}
      </p>
      <p className={styles.body}>{member.summary}</p>
      <p className={styles.body}>{member.pathNote}</p>
      {badge && (
        <Badge className={styles.badge} variant={badge.variant}>
          {badge.label}
        </Badge>
      )}
    </div>
  );
}

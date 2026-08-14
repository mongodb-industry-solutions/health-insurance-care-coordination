import Image from "next/image";
import Button from "@leafygreen-ui/button";
import Icon from "@leafygreen-ui/icon";
import styles from "./StoryCard.module.css";

/**
 * One card of a member's story. The visual template is shared by every card —
 * the pull-quote and the CTA only render when the card calls for them.
 *
 * @param {object} props.card  { eyebrow, title, body, closingLine? }
 * @param {object} props.member  The member the story belongs to (for the avatar).
 * @param {number} props.index  Zero-based position, used for the "01 / 03" prefix.
 * @param {number} props.total  Number of cards in the story.
 * @param {boolean} props.isLast  Show the "Go to Demo" CTA.
 * @param {() => void} props.onFinish  Called by the CTA.
 */
export default function StoryCard({
  card,
  member,
  index,
  total,
  isLast = false,
  onFinish,
}) {
  const position = `${String(index + 1).padStart(2, "0")} / ${String(
    total
  ).padStart(2, "0")}`;

  return (
    <article className={styles.card}>
      <Image
        className={styles.avatar}
        src={member.avatar}
        alt=""
        width={78}
        height={105}
      />

      <p className={styles.eyebrow}>
        {position} — {card.eyebrow}
      </p>
      <h2 className={styles.title}>{card.title}</h2>
      <p className={styles.body}>{card.body}</p>

      {card.closingLine && (
        <p className={styles.closingLine}>{card.closingLine}</p>
      )}

      {isLast && (
        <div className={styles.cta}>
          <Button
            variant="primary"
            size="large"
            rightGlyph={<Icon glyph="ArrowRight" />}
            onClick={onFinish}
          >
            Go to Demo
          </Button>
        </div>
      )}
    </article>
  );
}

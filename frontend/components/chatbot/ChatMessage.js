import styles from "./ChatMessage.module.css";

/**
 * One turn in the transcript.
 *
 * Assistant text is rendered as plain pre-wrapped text rather than Markdown. That is
 * deliberate: re-parsing the whole accumulated string on every token saturates the main
 * thread on a long reply, and nothing else in this app renders Markdown today.
 *
 * @param {object} props
 * @param {object} props.message
 */
export default function ChatMessage({ message }) {
  const { role, content, agent, done, activity } = message;

  if (role === "user") {
    return (
      <div className={`${styles.row} ${styles.userRow}`}>
        <div className={`${styles.bubble} ${styles.user}`}>{content}</div>
      </div>
    );
  }

  const isError = role === "error";

  return (
    <div className={styles.row}>
      <div
        className={`${styles.bubble} ${isError ? styles.error : styles.assistant}`}
        style={{ "--bubble-accent": agent?.accent ?? "var(--color-green)" }}
      >
        {!isError && <span className={styles.author}>{agent?.label}</span>}

        {content ? (
          <p className={styles.text}>{content}</p>
        ) : (
          /* The local playground has no streaming endpoint, so the whole reply lands
             at once after a wait that can run to a minute. A spinner with a label is
             the only thing keeping that from looking frozen — a bare caret is not
             enough over that long a pause. */
          <p className={styles.activity}>
            <span className={styles.spinner} aria-hidden="true" />
            {activity ?? "Thinking…"}
          </p>
        )}

        {/* A reply that is still arriving gets a soft pulse on the accent bar. */}
        {!done && !isError && content && (
          <span className={styles.streaming} aria-hidden="true" />
        )}
      </div>
    </div>
  );
}

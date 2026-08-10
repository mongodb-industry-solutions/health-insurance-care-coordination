import styles from "./ClinicalTimeline.module.css";

/**
 * Reverse-chronological clinical timeline, plus the active-treatment pill.
 *
 * @param {Array} props.events  From toTimelineEvents(): { id, date, actor, eventType, description, isCurrent }.
 * @param {object|null} props.activeTreatment  { label, value }.
 */
export default function ClinicalTimeline({ events = [], activeTreatment }) {
  if (!events.length) {
    return <p className={styles.empty}>No clinical history on file yet.</p>;
  }

  return (
    <div>
      <ol className={styles.timeline}>
        {events.map((event) => (
          <li key={event.id} className={styles.event}>
            <span
              className={`${styles.dot} ${
                event.isCurrent ? styles.dotCurrent : ""
              }`}
            />

            {event.isCurrent ? (
              <span className={styles.currentLabel}>Currently</span>
            ) : (
              <div className={styles.meta}>
                {event.date && <span>{event.date}</span>}
                {event.actor && <span className={styles.actor}>{event.actor}</span>}
                {event.eventType && <span>· {event.eventType}</span>}
              </div>
            )}

            {event.description && (
              <p className={styles.description}>{event.description}</p>
            )}
          </li>
        ))}
      </ol>

      {activeTreatment && (
        <div className={styles.activeTreatment}>
          <span className={styles.activeTreatmentLabel}>
            {activeTreatment.label}
          </span>
          <span className={styles.activeTreatmentValue}>
            {activeTreatment.value}
          </span>
        </div>
      )}
    </div>
  );
}

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Icon from "@leafygreen-ui/icon";
import {
  agentLabelOf,
  statusLineOf,
  toStreamEntries,
} from "@/lib/processPresenter";
import styles from "./ReasoningStream.module.css";

const clockFormat = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

/**
 * Every event of the run as one continuous, chronological transcript: handoffs,
 * reasoning steps, the recommendation, the closure.
 *
 * One scroller rather than one per stage. The run is a single argument — trial
 * length feeding step therapy feeding the recommendation — and reading it in
 * three separate boxes broke that chain.
 *
 * Sticks to the newest entry only while the reader is already at the bottom, so
 * scrolling up to re-read something is not fought by the next arrival.
 *
 * @param {object} props.run  From useAuthorizationRun().
 */
export default function ReasoningStream({ run }) {
  const entries = toStreamEntries(run);
  const running = run.turns.find((turn) => turn.status === "running");
  const scroller = useRef(null);
  const [pinned, setPinned] = useState(true);

  const handleScroll = useCallback(() => {
    const node = scroller.current;
    if (!node) return;

    const distance = node.scrollHeight - node.scrollTop - node.clientHeight;
    setPinned(distance < 48);
  }, []);

  useEffect(() => {
    const node = scroller.current;
    if (!node || !pinned) return;

    node.scrollTo({ top: node.scrollHeight, behavior: "smooth" });
  }, [entries.length, pinned]);

  const jumpToLatest = () => {
    setPinned(true);
    scroller.current?.scrollTo({
      top: scroller.current.scrollHeight,
      behavior: "smooth",
    });
  };

  return (
    <section className={styles.stream}>
      <header className={styles.header}>
        <div className={styles.headText}>
          <h3 className={styles.heading}>Agent reasoning</h3>
          <p className={styles.now}>
            {running
              ? statusLineOf(running)
              : run.status === "running"
                ? "Waiting for an agent to pick the case up…"
                : "Transcript complete."}
          </p>
        </div>

        <span className={styles.count}>{entries.length} events</span>
      </header>

      <div
        className={styles.body}
        ref={scroller}
        onScroll={handleScroll}
        role="log"
        aria-live="polite"
        aria-label="Agent reasoning transcript"
        tabIndex={0}
      >
        {entries.length === 0 ? (
          <p className={styles.empty}>
            Waiting for the first event from the backend…
          </p>
        ) : (
          entries.map((entry) => <Entry key={entry.id} entry={entry} />)
        )}

        {run.status === "running" && (
          <p className={styles.working}>
            <span className={styles.workingDots} aria-hidden="true">
              <span />
              <span />
              <span />
            </span>
            {running ? agentLabelOf(running.agent) : "The orchestrator"} is
            working
          </p>
        )}
      </div>

      {!pinned && (
        <button type="button" className={styles.jump} onClick={jumpToLatest}>
          <Icon glyph="ArrowDown" size={12} />
          Jump to latest
        </button>
      )}
    </section>
  );
}

function Entry({ entry }) {
  if (entry.kind === "stage") {
    return (
      <div className={styles.stageMark}>
        <span className={styles.stageNumber}>{entry.stage}</span>
        <span className={styles.stageTitle}>{entry.title}</span>
        <span className={styles.stageAgent}>{agentLabelOf(entry.agent)}</span>
        <span className={styles.stageRule} aria-hidden="true" />
        <time className={styles.time}>{clockFormat.format(entry.at)}</time>
      </div>
    );
  }

  if (entry.kind === "step") {
    return (
      <article className={styles.entry}>
        <div className={styles.entryHead}>
          <code className={styles.name}>{entry.name}</code>
          {entry.memoryType && (
            <span className={styles.memory}>{entry.memoryType}</span>
          )}
          {typeof entry.confidence === "number" && (
            <span className={styles.confidence}>
              {entry.confidence.toFixed(2)}
            </span>
          )}
          <time className={styles.time}>{clockFormat.format(entry.at)}</time>
        </div>
        <p className={styles.detail}>{entry.detail}</p>
      </article>
    );
  }

  const tone = entry.tone ? styles[entry.tone] : "";

  return (
    <article
      className={`${styles.milestone} ${tone} ${
        entry.kind === "terminal" ? styles.terminal : ""
      }`}
    >
      <span className={styles.milestoneIcon}>
        <Icon glyph={entry.icon ?? "Checkmark"} size={12} />
      </span>
      <p className={styles.milestoneText}>{entry.text}</p>
      <time className={styles.time}>{clockFormat.format(entry.at)}</time>
    </article>
  );
}

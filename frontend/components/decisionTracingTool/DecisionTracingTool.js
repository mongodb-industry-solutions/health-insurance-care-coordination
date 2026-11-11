"use client";

import { toPercent, toTraceSegments } from "@/lib/tracePresenter";
import styles from "./DecisionTracingTool.module.css";

const DOT_CLASS = {
  agent: styles.dotAgent,
  gate: styles.dotGate,
  human: styles.dotHuman,
};

function outcomeClass(decision) {
  const value = String(decision ?? "").toLowerCase();

  if (value.includes("denied")) return styles.outcomeDenied;
  if (value.includes("approved")) return "";
  return styles.outcomePending;
}

function readable(value) {
  if (!value) return null;
  const text = String(value).replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** One reasoning step, gate check, or human action. */
function TraceNode({ node }) {
  return (
    <li className={styles.node}>
      <span className={`${styles.dot} ${DOT_CLASS[node.kind]}`} />

      <div className={styles.nodeHeader}>
        <span className={styles.nodeTitle}>{node.title}</span>

        {node.memoryType && (
          <span
            className={`${styles.badge} ${
              node.kind === "gate" ? styles.badgeGate : ""
            }`}
          >
            {node.memoryType}
          </span>
        )}

        {node.confidence != null && (
          <span className={styles.confidence}>
            {toPercent(node.confidence)} confidence
          </span>
        )}
      </div>

      {/* `detail` is written as a plain-language sentence — shown verbatim. */}
      {node.detail && <p className={styles.detail}>{node.detail}</p>}

      {(node.role || node.closedBy) && (
        <p className={styles.role}>
          {[
            node.role && `Decision maker: ${node.role}`,
            node.closedBy && `closed by ${node.closedBy}`,
            node.closedAt,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      )}
    </li>
  );
}

/** The decision closing out a trace, plus any human override. */
function OutcomeBanner({ outcome }) {
  if (!outcome.decision && !outcome.rationale) return null;

  return (
    <div className={`${styles.outcome} ${outcomeClass(outcome.decision)}`}>
      <span className={styles.outcomeLabel}>Outcome</span>
      <p className={styles.outcomeDecision}>
        {readable(outcome.decision) ?? "Pending"}
        {outcome.confidence != null && (
          <span className={styles.confidence}>
            {" "}
            {toPercent(outcome.confidence)} confidence
          </span>
        )}
      </p>

      {outcome.rationale && (
        <p className={styles.outcomeRationale}>{outcome.rationale}</p>
      )}

      {outcome.overrideFlag && (
        <p className={styles.override}>
          Overridden by {outcome.overrideBy ?? "a reviewer"}
          {outcome.overrideReason ? ` — ${outcome.overrideReason}` : ""}
        </p>
      )}
    </div>
  );
}

/**
 * Decision Tracing: every decision made for this member, as a chronological
 * timeline. Reuses the dashboard timeline's dot-and-line language; dot color
 * carries the actor (agent reasoning, mechanical gate, human review).
 *
 * @param {Array} props.traces  From GET /api/audit/member/{memberId}.
 */
export default function DecisionTracingTool({ traces = [] }) {
  const segments = toTraceSegments(traces);

  if (!segments.length) {
    return (
      <p className={styles.empty}>
        No decisions have been made for this member yet. Once a pending action is
        started, every reasoning step will appear here.
      </p>
    );
  }

  return (
    <>
      {segments.map((segment, index) => (
        <div key={segment.id} className={styles.segment}>
          <div className={styles.segmentHeader}>
            <p className={styles.segmentTitle}>
              {segment.decisionType ?? "Decision"}
              {segment.requestedService && ` — ${segment.requestedService}`}
            </p>
            <p className={styles.segmentMeta}>
              {[segment.createdAt, segment.triggeredBy]
                .filter(Boolean)
                .join(" · ")}
            </p>

            {(segment.reviewRequiredReason ||
              segment.regulatoryFlags.length > 0 ||
              segment.guidelineRef) && (
              <div className={styles.tags}>
                {segment.guidelineRef && (
                  <span className={styles.tag}>{segment.guidelineRef}</span>
                )}
                {segment.reviewRequiredReason && (
                  <span className={styles.tag}>
                    {readable(segment.reviewRequiredReason)}
                  </span>
                )}
                {segment.regulatoryFlags.map((flag) => (
                  <span key={flag} className={styles.tag}>
                    {readable(flag)}
                  </span>
                ))}
              </div>
            )}
          </div>

          {segment.nodes.length > 0 && (
            <ol className={styles.timeline}>
              {segment.nodes.map((node) => (
                <TraceNode key={node.id} node={node} />
              ))}
            </ol>
          )}

          <OutcomeBanner outcome={segment.outcome} />

          {/* Chained traces stay visually connected rather than standing alone. */}
          {segment.linked.map((link) => (
            <p key={link.traceId} className={styles.link}>
              {[
                link.relationship ?? "Led to",
                link.decisionType,
                link.occurredAt,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          ))}

          {index < segments.length - 1 && segment.linked.length === 0 && (
            <p className={styles.link}>Followed by</p>
          )}
        </div>
      ))}
    </>
  );
}

/**
 * Shapes audit traces from `GET /api/audit/member/{id}` into timeline segments.
 *
 * Nodes are classified by *actor* — who or what acted — rather than by outcome,
 * since the point of the view is showing how a decision was reached.
 */

function pick(source, ...keys) {
  if (!source) return undefined;
  return keys.map((key) => source[key]).find((value) => value != null);
}

/** Step names that are mechanical fact checks rather than reasoning. */
const GATE_PATTERNS = [
  "eligibility",
  "coverage",
  "verify_",
  "check_",
  "benefit",
];

function isAdministrativeGate(step) {
  const name = String(step.name ?? pick(step, "step_id", "stepId") ?? "").toLowerCase();
  return GATE_PATTERNS.some((pattern) => name.includes(pattern));
}

function readable(value) {
  if (!value) return null;
  const text = String(value).replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * One segment per trace, in chronological order, each with its nodes, compliance
 * tags, outcome and the relationship to whatever it led to.
 */
export function toTraceSegments(traces = []) {
  const ordered = [...traces].sort((a, b) =>
    String(pick(a, "created_at", "createdAt") ?? "").localeCompare(
      String(pick(b, "created_at", "createdAt") ?? "")
    )
  );

  return ordered.map((trace) => {
    const audit = trace.audit ?? {};
    const review = trace.review ?? {};
    const outcome = trace.outcome ?? {};

    // `steps` has no explicit order field; array order is the sequence.
    const nodes = (trace.steps ?? []).map((step, index) => ({
      id: pick(step, "step_id", "stepId") ?? `step-${index}`,
      kind: isAdministrativeGate(step) ? "gate" : "agent",
      title: readable(step.name) ?? "Reasoning step",
      memoryType: pick(step, "memory_type", "memoryType"),
      detail: step.detail,
      confidence: step.confidence,
    }));

    const routedToHuman = pick(review, "routed_to_human", "routedToHuman");
    const closedBy = pick(review, "closed_by", "closedBy");
    const finalDecisionMaker = pick(
      review,
      "final_decision_maker",
      "finalDecisionMaker"
    );

    if (routedToHuman || closedBy || finalDecisionMaker) {
      nodes.push({
        id: `${pick(trace, "trace_id", "traceId")}-review`,
        kind: "human",
        title: routedToHuman ? "Routed to human review" : "Closed",
        role: finalDecisionMaker,
        closedBy,
        closedAt: pick(review, "closed_at", "closedAt"),
        detail: review.notes,
      });
    }

    // `linkedTraces` ties a prior authorization to what followed it.
    const linked = (pick(trace, "linked_traces", "linkedTraces") ?? []).map(
      (link) => ({
        traceId: pick(link, "trace_id", "traceId"),
        relationship: readable(link.relationship),
        decisionType: readable(pick(link, "decision_type", "decisionType")),
        occurredAt: pick(link, "occurred_at", "occurredAt"),
      })
    );

    return {
      id: pick(trace, "trace_id", "traceId"),
      decisionType: readable(pick(trace, "decision_type", "decisionType")),
      requestedService: pick(trace, "requested_service", "requestedService"),
      createdAt: pick(trace, "created_at", "createdAt"),
      triggeredBy: pick(audit, "triggered_by", "triggeredBy"),
      // Compliance context, surfaced as muted tags rather than dropped.
      reviewRequiredReason: pick(
        audit,
        "review_required_reason",
        "reviewRequiredReason"
      ),
      regulatoryFlags: pick(audit, "regulatory_flags", "regulatoryFlags") ?? [],
      guidelineRef: pick(
        pick(trace, "context_snapshot", "contextSnapshot"),
        "guideline_ref",
        "guidelineRef"
      ),
      nodes,
      linked,
      outcome: {
        decision: outcome.decision ?? trace.status,
        rationale: outcome.rationale,
        confidence: outcome.confidence,
        overrideFlag: Boolean(pick(outcome, "override_flag", "overrideFlag")),
        overrideBy: pick(outcome, "override_by", "overrideBy"),
        overrideReason: pick(outcome, "override_reason", "overrideReason"),
      },
    };
  });
}

/** Whole percent from a 0–1 confidence, or null. */
export function toPercent(confidence) {
  if (confidence == null) return null;
  return `${Math.round(confidence * 100)}%`;
}

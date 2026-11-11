/**
 * Shapes an authorization run into the three-step process view.
 *
 * The stream has two nested rhythms: agent *turns* (`turn_started` /
 * `turn_finished`) and the reasoning *steps* recorded inside them. The stepper
 * is the turns — the backend drives exactly the three the design asks for
 * (insurance gates, clinical review, routing) — and each turn's steps become
 * the tool list and the log lines inside its card.
 *
 * See `backend/authorization/service.py`: `next_action` returns one of
 * `start` / `clinical_review` / `routing`, which is what arrives as
 * `turn_started.action`.
 */

/**
 * The three turns a full run takes, in order. Also the pending-state skeleton.
 *
 * `expectedSteps` is what makes the progress bars determinate: the reasoning
 * steps each turn records are a known, fixed set (`eligibility_gate`,
 * `coverage_gate` for the insurance gates; the four clinical ones after that).
 * The routing turn records no named steps of its own, so it is the one stage
 * that has to run indeterminate — see `progressOf`.
 */
export const PROCESS_STEPS = [
  {
    action: "start",
    title: "Check eligibility and coverage",
    agent: "insurance",
    expectedSteps: 2,
    banner: "Eligibility and coverage confirmed for the requested treatment.",
  },
  {
    action: "clinical_review",
    title: "Clinical review of the requested treatment",
    agent: "care_coordination",
    expectedSteps: 4,
    banner: "Clinical review complete — a recommendation was recorded.",
  },
  {
    action: "routing",
    title: "Verify approval/denial decision",
    agent: "insurance",
    expectedSteps: 0,
    banner: "Decision verified and recorded on the audit trace.",
  },
];

export const AGENT_LABELS = {
  insurance: "Insurance Agent",
  care_coordination: "Health Agent",
};

/** `recorded_by` on a step is prefixed; the turn's `agent` is not. */
export function agentKeyOf(value) {
  return String(value ?? "").replace(/^system:/, "").replace(/_agent$/, "");
}

export function agentLabelOf(value) {
  const key = agentKeyOf(value);
  return AGENT_LABELS[key] ?? "Agent";
}

/**
 * The narration line for a turn. Falls back to the turn's own sentence before
 * any step has landed, then tracks the most recent step so the line keeps
 * moving during the long LLM silences.
 */
const OPENING_LINES = {
  start: "The agent is opening the case and checking the member's eligibility.",
  clinical_review:
    "The health agent is reviewing the clinical record against the guideline.",
  routing: "The agent is verifying the recommendation and routing the decision.",
};

const STEP_PHASES = {
  eligibility_gate: "Confirming the member is eligible on the service date.",
  coverage_gate: "Validating the plan's coverage rules for this treatment.",
  concept_match: "Matching the requested treatment to a clinical concept.",
  classification: "Classifying the treatment against the guideline.",
  trial_review: "Reviewing the documented treatment trial for continuity.",
  step_therapy: "Checking the step-therapy requirement.",
};

export function statusLineOf(turn) {
  const latest = turn.steps[turn.steps.length - 1];
  if (latest && STEP_PHASES[latest.name]) return STEP_PHASES[latest.name];
  if (latest) return `Recording ${latest.name.replace(/_/g, " ")}.`;
  return OPENING_LINES[turn.action] ?? "Working on this step.";
}

/**
 * How far along one stage is.
 *
 * A running stage is deliberately capped below 100% — a bar that sits full while
 * the agent is still thinking reads as a stall. A stage with no expected step
 * count creeps rather than lying about a fraction, and reports itself as
 * indeterminate so the bar can animate instead.
 */
function progressOf(definition, turn, state) {
  if (state === "complete") return { value: 100, indeterminate: false };
  if (state === "pending" || state === "skipped") {
    return { value: 0, indeterminate: false };
  }

  const recorded = turn?.steps.length ?? 0;

  if (state === "error") {
    return { value: Math.max(8, (recorded / 4) * 100), indeterminate: false };
  }

  if (!definition.expectedSteps) {
    return { value: 45, indeterminate: true };
  }

  const fraction = recorded / definition.expectedSteps;
  return { value: Math.min(92, 8 + fraction * 84), indeterminate: false };
}

/** "3/4", or null where there is no step count to count against. */
function countLabelOf(definition, turn, state) {
  if (!definition.expectedSteps) return null;
  if (state === "pending" || state === "skipped") return null;

  const recorded = turn?.steps.length ?? 0;
  const total = Math.max(definition.expectedSteps, recorded);
  return `${recorded}/${total}`;
}

/**
 * Merges the turns the stream reported onto the three-step skeleton, so pending
 * steps render before they start and steps a short run never reaches are marked
 * as such rather than left spinning.
 *
 * Runs that end early are normal — a benefit exclusion closes in one turn.
 */
export function toStepRows(run) {
  const finished = run.status === "finished" || run.status === "error";

  return PROCESS_STEPS.map((definition, index) => {
    const turn = run.turns.find((entry) => entry.action === definition.action);
    const number = index + 1;
    const state = turn ? turn.status : finished ? "skipped" : "pending";

    return {
      ...definition,
      number,
      state, // pending | running | complete | error | skipped
      turn: turn ?? null,
      progress: progressOf(definition, turn, state),
      countLabel: countLabelOf(definition, turn, state),
      statusLine: turn
        ? statusLineOf(turn)
        : state === "skipped"
          ? "Not required for this case."
          : null,
      logs: turn ? turn.steps.map((step) => step.detail).filter(Boolean) : [],
      steps: turn ? turn.steps : [],
    };
  });
}

/**
 * Every event the run produced, flattened into one chronological stream.
 *
 * Built from `run.events` rather than `run.steps` on purpose: the reasoning
 * steps are the substance, but the handoffs, the trace opening, the
 * recommendation and the closure are the spine that makes the steps make sense.
 * Dropping them would leave 10-20 second holes with nothing explaining them.
 *
 * Timestamps are client arrival times — the stream carries none of its own.
 */
export function toStreamEntries(run) {
  const entries = [];
  let stage = 0;
  // The decision the case was closed with, so the run's last line can match it.
  let closedDecision = null;

  run.events.forEach(({ event, data, at }, index) => {
    const push = (entry) => entries.push({ id: `${index}-${event}`, at, ...entry });

    switch (event) {
      case "accepted":
        push({
          kind: "milestone",
          icon: "Note",
          text: `Case opened for ${
            data.proposed_treatment ?? "the requested treatment"
          }${data.service_date ? `, service date ${data.service_date}` : ""}.`,
        });
        break;

      case "turn_started": {
        stage += 1;
        const definition = PROCESS_STEPS.find(
          (entry) => entry.action === data.action
        );
        push({
          kind: "stage",
          stage,
          title: definition?.title ?? data.action,
          agent: data.agent,
        });
        break;
      }

      case "trace_opened":
        push({
          kind: "milestone",
          icon: "Beaker",
          text: `Audit trace ${data.trace_id} opened.`,
        });
        break;

      case "step":
        push({
          kind: "step",
          name: data.name,
          detail: data.detail,
          confidence: data.confidence,
          memoryType: data.memory_type,
          agent: agentKeyOf(data.recorded_by),
        });
        break;

      case "recommendation":
        push({
          kind: "milestone",
          icon: "Charts",
          tone: isDenied(data.decision) ? "denied" : "accent",
          text: `Recommendation: ${data.decision}${
            typeof data.confidence === "number"
              ? ` at ${data.confidence.toFixed(2)} confidence`
              : ""
          }.${data.rationale ? ` ${data.rationale}` : ""}`,
        });
        break;

      case "escalated":
        push({
          kind: "milestone",
          icon: "Warning",
          tone: "warn",
          text: `Routed to a medical director — ${String(
            data.reason ?? "escalated"
          ).replace(/_/g, " ")}.`,
        });
        break;

      case "closed":
        closedDecision = data.decision;
        push({
          kind: "milestone",
          icon: isDenied(data.decision) ? "XWithCircle" : "Checkmark",
          tone: isDenied(data.decision) ? "denied" : "accent",
          text: `Case closed as ${String(data.decision).replace(/_/g, " ")} by ${
            data.closed_by ?? "the agent"
          }.`,
        });
        break;

      case "stopped":
        push({
          kind: "terminal",
          icon: isDenied(closedDecision) ? "XWithCircle" : "CheckmarkWithCircle",
          tone: isDenied(closedDecision) ? "denied" : undefined,
          text: `Run finished — ${String(data.reason).replace(/_/g, " ")}.`,
        });
        break;

      case "error":
        push({
          kind: "terminal",
          icon: "Warning",
          tone: "error",
          text: data.detail ?? "The run failed.",
        });
        break;

      default:
        break;
    }
  });

  return entries;
}

/** The run-level bar: the mean of the three stages' own progress. */
export function toOverallProgress(run) {
  const rows = toStepRows(run);
  const settled = run.status === "finished" || run.status === "error";

  // A short run genuinely finished, even with stages it never needed.
  if (settled) return 100;

  const total = rows.reduce((sum, row) => sum + row.progress.value, 0);
  return Math.round(total / rows.length);
}

/**
 * The final summary card's verdict. A denial is still a successful run — the
 * agent was allowed to decide. An escalation is the case the reviewer must pick
 * up, so it gets its own amber state rather than being folded into success.
 */
/** Is this decision a denial? `denied`, or anything that spells it that way. */
export function isDenied(decision) {
  return String(decision ?? "").toLowerCase().includes("denied");
}

/** The icon for a settled run: a tick for success, a cross for a denial, else a warning. */
export function outcomeGlyph(tone) {
  if (tone === "success") return "Checkmark";
  if (tone === "denied") return "XWithCircle";
  return "Warning";
}

export function toOutcome(run) {
  if (run.status === "error") {
    return {
      tone: "failed",
      badge: "Failed",
      title: "Process Failed",
      detail: run.error ?? "The run stopped before reaching a decision.",
      cta: null,
    };
  }

  if (run.stopReason === "awaiting_medical_director") {
    return {
      tone: "review",
      badge: "Needs review",
      title: "Awaiting Medical Director",
      detail:
        run.escalation?.reason === "confidence_below_guideline_threshold"
          ? "The agent was not confident enough to close this case on its own."
          : "A clinical denial requires a physician to close the case.",
      cta: "Review manually",
    };
  }

  if (run.stopReason === "stalled" || run.stopReason === "stream_ended") {
    return {
      tone: "review",
      badge: "Needs review",
      title: "Process Incomplete",
      detail:
        run.stopReason === "stalled"
          ? "An agent finished its turn without moving the case forward."
          : "The live connection ended before the run reported a result.",
      cta: "Review manually",
    };
  }

  // The agent closed the case, and the decision was a denial (an eligibility or benefit
  // exclusion it may decide on its own). The process worked; the answer was no, so it
  // must not read as a success.
  if (isDenied(run.closure?.decision)) {
    return {
      tone: "denied",
      badge: "Denied",
      title: "Request Denied",
      detail: `Closed as denied by ${run.closure.closed_by ?? "the agent"}.`,
      cta: null,
    };
  }

  return {
    tone: "success",
    badge: "Success",
    title: "Process Completed",
    detail: run.closure
      ? `Closed as ${String(run.closure.decision).replace(/_/g, " ")} by ${
          run.closure.closed_by ?? "the agent"
        }.`
      : "The case reached a decision.",
    cta: null,
  };
}

/** "20.5s" from the wall-clock span the hook recorded. */
export function formatElapsed(startedAt, finishedAt) {
  if (!startedAt || !finishedAt) return null;
  return `${((finishedAt - startedAt) / 1000).toFixed(1)}s`;
}

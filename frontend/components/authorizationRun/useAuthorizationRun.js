import { useCallback, useEffect, useRef, useState } from "react";
import { streamAuthorizationRun } from "@/lib/api/authorization";

const INITIAL = {
  status: "idle", // idle | running | finished | error
  turns: [], // { turn, action, agent, status, steps[], startedAt, finishedAt }
  events: [],
  steps: [],
  traceId: null,
  accepted: null,
  recommendation: null,
  escalation: null,
  closure: null,
  stopReason: null,
  error: null,
  startedAt: null,
  finishedAt: null,
};

/** Replaces one turn in the list, matched by turn number. */
function patchTurn(turns, number, patch) {
  return turns.map((entry) =>
    entry.turn === number ? { ...entry, ...patch } : entry
  );
}

/** The turn a `step` event belongs to: the one currently open. */
function openTurnOf(turns) {
  return [...turns].reverse().find((entry) => entry.status === "running");
}

/**
 * Drives one prior-authorization run and collects everything the stream reports.
 *
 * The stream is the only progress channel — there is no reconnect endpoint, so a
 * dropped run has to be recovered from `GET /api/audit/traces/{traceId}` or by
 * restarting the view. Because of that, this state deliberately lives above the
 * process view: navigating back to the dashboard must not unmount it.
 */
export function useAuthorizationRun() {
  const [state, setState] = useState(INITIAL);
  const abortRef = useRef(null);

  // Abort an in-flight read if the component goes away mid-run.
  useEffect(() => () => abortRef.current?.abort(), []);

  const handleEvent = useCallback((event, data) => {
    setState((previous) => {
      const at = Date.now();
      const next = {
        ...previous,
        // Steps have no server timestamps, so stamp them on arrival.
        events: [...previous.events, { event, data, at }],
      };

      switch (event) {
        case "accepted":
          next.accepted = data;
          break;

        case "trace_opened":
          next.traceId = data.trace_id;
          break;

        case "turn_started":
          next.turns = [
            ...previous.turns,
            {
              turn: data.turn,
              action: data.action,
              agent: data.agent,
              status: "running",
              steps: [],
              startedAt: at,
              finishedAt: null,
            },
          ];
          break;

        case "turn_finished":
          next.turns = patchTurn(previous.turns, data.turn, {
            status: "complete",
            finishedAt: at,
          });
          next.traceId = data.trace_id ?? previous.traceId;
          break;

        case "step": {
          next.steps = [...previous.steps, data];
          const open = openTurnOf(previous.turns);
          if (open) {
            next.turns = patchTurn(previous.turns, open.turn, {
              steps: [...open.steps, data],
            });
          }
          break;
        }

        case "recommendation":
          next.recommendation = data;
          break;

        case "escalated":
          next.escalation = data;
          break;

        case "closed":
          next.closure = data;
          break;

        case "stopped":
          next.status = "finished";
          next.stopReason = data.reason;
          next.traceId = data.trace_id ?? previous.traceId;
          next.finishedAt = at;
          break;

        case "error":
          next.status = "error";
          next.error = data.detail ?? "The run failed.";
          next.finishedAt = at;
          // The turn that was open never finished — say so rather than
          // leaving it pulsing forever.
          next.turns = previous.turns.map((entry) =>
            entry.status === "running"
              ? { ...entry, status: "error", finishedAt: at }
              : entry
          );
          break;

        default:
          break;
      }

      return next;
    });
  }, []);

  const start = useCallback(
    async (memberId, { serviceDate } = {}) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setState({ ...INITIAL, status: "running", startedAt: Date.now() });

      try {
        await streamAuthorizationRun(memberId, {
          onEvent: handleEvent,
          serviceDate,
          signal: controller.signal,
        });

        // The stream can end without a terminal event if the connection drops.
        setState((previous) =>
          previous.status === "running"
            ? {
                ...previous,
                status: "finished",
                stopReason: "stream_ended",
                finishedAt: Date.now(),
              }
            : previous
        );
      } catch (cause) {
        if (controller.signal.aborted) return;
        setState((previous) => ({
          ...previous,
          status: "error",
          error: cause.message,
          finishedAt: Date.now(),
        }));
      }
    },
    [handleEvent]
  );

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setState(INITIAL);
  }, []);

  return { ...state, start, reset };
}

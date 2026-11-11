import { apiFetch } from "./client";

// See `client.js` — same-origin by default, proxied by `next.config.mjs`.
const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

/** Events after which the backend sends nothing more. */
const TERMINAL_EVENTS = new Set(["stopped", "error"]);

/**
 * GET /api/members/{memberId}/authorization/can-start — whether the Start
 * button should be enabled. `reason` is `no_pending_action` or
 * `already_in_progress`.
 */
export function canStartAuthorization(memberId) {
  return apiFetch(`/api/members/${memberId}/authorization/can-start`);
}

/** GET /api/authorization/pending-review — cases waiting on a human. */
export function fetchPendingReview() {
  return apiFetch("/api/authorization/pending-review");
}

/**
 * POST /api/authorization/{traceId}/medical-director-decision — close an
 * escalated case. Every parameter goes on the query string, not in a body.
 *
 * @param {string} traceId
 * @param {object} params
 * @param {"approved"|"denied"} params.decision
 * @param {string} [params.notes]
 * @param {string} [params.medicalDirectorId]
 */
export function submitMedicalDirectorDecision(
  traceId,
  { decision, notes, medicalDirectorId } = {}
) {
  const params = new URLSearchParams({ decision });
  if (notes) params.set("notes", notes);
  if (medicalDirectorId) params.set("medical_director_id", medicalDirectorId);

  return apiFetch(
    `/api/authorization/${traceId}/medical-director-decision?${params}`,
    { method: "POST" }
  );
}

/**
 * Parses one SSE frame into `{ event, data }`. Returns null for keepalives
 * (lines starting with `:`) and for anything unparseable.
 */
function parseFrame(frame) {
  const trimmed = frame.trim();
  if (!trimmed || trimmed.startsWith(":")) return null;

  const event = trimmed.match(/^event: (.+)$/m)?.[1];
  const raw = trimmed.match(/^data: (.+)$/m)?.[1];
  if (!event) return null;

  try {
    return { event, data: raw ? JSON.parse(raw) : {} };
  } catch {
    return { event, data: {} };
  }
}

/**
 * POST /api/members/{memberId}/authorization/start — starts a prior-auth run
 * and streams progress back as `text/event-stream`. One call, held open for the
 * whole run (60-120s). `EventSource` cannot POST, so this reads the body itself.
 *
 * Validation happens before the stream opens, so a 404 (unknown member) or 409
 * (a run is already open) throws rather than arriving as an `error` event.
 *
 * Closing the reader does **not** cancel the run — the agents keep working, the
 * UI just stops seeing it.
 *
 * @param {string} memberId
 * @param {object} options
 * @param {(event: string, data: object) => void} options.onEvent
 * @param {string} [options.serviceDate]  `YYYY-MM-DD`, defaults to today.
 * @param {AbortSignal} [options.signal]
 */
export async function streamAuthorizationRun(
  memberId,
  { onEvent, serviceDate, signal } = {}
) {
  const query = serviceDate ? `?service_date=${serviceDate}` : "";
  const response = await fetch(
    `${BASE_URL}/api/members/${memberId}/authorization/start${query}`,
    { method: "POST", signal }
  );

  if (!response.ok) {
    const detail = await response
      .json()
      .then((body) => body.detail)
      .catch(() => null);
    throw new Error(detail ?? `Could not start the run (${response.status})`);
  }

  const reader = response.body
    .pipeThrough(new TextDecoderStream())
    .getReader();
  let buffer = "";

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += value;
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? ""; // the tail may be a partial frame

      for (const frame of frames) {
        const parsed = parseFrame(frame);
        if (!parsed) continue;

        onEvent?.(parsed.event, parsed.data);
        if (TERMINAL_EVENTS.has(parsed.event)) return;
      }
    }
  } finally {
    reader.cancel().catch(() => {});
  }
}

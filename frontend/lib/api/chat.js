import { apiFetch } from "./client";

// See `client.js` — same-origin by default, proxied by `next.config.mjs`.
const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

/** Events after which the backend sends nothing more. */
const TERMINAL_EVENTS = new Set(["done", "failed"]);

/** GET /api/chat/agents — the options for the agent picker. */
export function fetchChatAgents() {
  return apiFetch("/api/chat/agents");
}

/**
 * Parses one SSE frame into `{ event, data }`. Returns null for keepalives
 * (lines starting with `:`) and for anything unparseable.
 *
 * Identical in shape to the parser in `authorization.js` — the backend emits one
 * SSE dialect for both streams, so this is the same job twice rather than two
 * protocols.
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
 * POST /api/chat/{agentId}/stream — sends one message and streams the reply.
 *
 * `sessionId` is omitted on the first turn of a conversation and sent on every
 * turn after, which is what gives the agent memory. The `done` event carries the
 * id to use next; see `useChat.js` for the write-once rule that goes with it.
 *
 * `EventSource` cannot POST, so this reads the response body itself.
 *
 * Aborting via `signal` stops the browser reading. It does **not** stop the agent:
 * the turn runs to completion upstream, we just stop listening.
 *
 * @param {string} agentId
 * @param {object} options
 * @param {string} options.message
 * @param {(event: string, data: object) => void} options.onEvent
 * @param {string} [options.sessionId]
 * @param {AbortSignal} [options.signal]
 */
export async function streamChatMessage(
  agentId,
  { message, onEvent, sessionId, signal } = {}
) {
  const response = await fetch(`${BASE_URL}/api/chat/${agentId}/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // Null rather than omitted is fine here: the backend drops a falsy value before
    // it reaches the agent, which is where "absent means new conversation" matters.
    body: JSON.stringify({ message, session_id: sessionId ?? null }),
    signal,
  });

  if (!response.ok) {
    const detail = await response
      .json()
      .then((body) => body.detail)
      .catch(() => null);
    throw new Error(detail ?? `The agent could not be reached (${response.status})`);
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

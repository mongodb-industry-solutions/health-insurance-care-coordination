import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { fetchChatAgents, streamChatMessage } from "@/lib/api/chat";

/**
 * Owns the conversation: one independent thread per agent, plus the send/stream
 * lifecycle.
 *
 * Two things here are load-bearing and easy to get wrong:
 *
 *  1. **A session id is written once per conversation.** The agent returns a fresh
 *     `execution_id` on *every* turn, but only the first one is the conversation
 *     handle. Overwriting it on each turn silently restarts the conversation while
 *     still looking like it works — the agent just quietly forgets everything.
 *
 *  2. **Threads are separate but streams are concurrent.** Switching agents swaps the
 *     visible transcript; it does not touch either session id and does not cancel an
 *     in-flight reply, so an answer that lands while you are reading the other agent
 *     is still there when you switch back.
 *
 * @param {object} [context]
 * @param {string} [context.memberId]    Prefixed to the first message of a conversation
 *                                       so the agent knows who is asking.
 * @param {string} [context.memberName]
 */
export function useChat({ memberId, memberName } = {}) {
  const [agents, setAgents] = useState([]);
  const [agentId, setAgentId] = useState(null);
  // Every agent's turns in one list, tagged by agent; the caller only ever sees the
  // selected agent's slice. Kept as one array so a reply can be patched by id without
  // first working out which thread it belongs to.
  const [allMessages, setAllMessages] = useState([]);
  const [streamingAgents, setStreamingAgents] = useState(() => new Set());
  const [loadError, setLoadError] = useState(null);

  // Session ids live in a ref, not state: one arriving mid-stream must not re-render
  // the transcript. Nothing renders them directly.
  const sessionsRef = useRef({}); // agentId -> sessionId
  const activeStreamsRef = useRef({}); // agentId -> AbortController

  const selectedAgent = agents.find((a) => a.id === agentId) ?? agents[0] ?? null;

  useEffect(() => {
    let cancelled = false;

    fetchChatAgents()
      .then(({ agents: list, default: fallback }) => {
        if (cancelled) return;
        setAgents(list);
        setAgentId((current) => current ?? fallback ?? list[0]?.id ?? null);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err.message);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  // Abort every in-flight read on unmount, so a closed panel stops consuming a stream.
  useEffect(() => {
    const streams = activeStreamsRef.current;
    return () => {
      Object.values(streams).forEach((controller) => controller.abort());
    };
  }, []);

  const messages = useMemo(
    () => allMessages.filter((m) => m.agent?.id === selectedAgent?.id),
    [allMessages, selectedAgent?.id]
  );

  const patchMessage = useCallback((id, patch) => {
    setAllMessages((current) =>
      current.map((message) =>
        message.id === id
          ? { ...message, ...(typeof patch === "function" ? patch(message) : patch) }
          : message
      )
    );
  }, []);

  const markStreaming = useCallback((id, isStreaming) => {
    setStreamingAgents((current) => {
      const next = new Set(current);
      if (isStreaming) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);

  /**
   * Clears one agent's thread completely: its transcript and the session id behind it,
   * so the next message starts a conversation the agent has no memory of.
   *
   * Any in-flight reply is aborted first — without that, a stream still running would
   * patch a message that has just been removed, and its `done` frame would write a
   * session id back into the conversation we are trying to end.
   */
  const resetSession = useCallback(
    (id) => {
      const target = id ?? selectedAgent?.id;
      if (!target) return;

      activeStreamsRef.current[target]?.abort();
      delete sessionsRef.current[target];
      setAllMessages((current) => current.filter((m) => m.agent?.id !== target));
    },
    [selectedAgent?.id]
  );

  const stopStreaming = useCallback((id) => {
    activeStreamsRef.current[id]?.abort();
  }, []);

  const sendMessage = useCallback(
    async (text) => {
      const agent = selectedAgent;
      const trimmed = text.trim();
      // The ref, not `streamingAgents`, is the authoritative busy check — state lags a
      // render behind and would let a double-tap start two runs.
      if (!trimmed || !agent || activeStreamsRef.current[agent.id]) return;

      const sessionId = sessionsRef.current[agent.id] ?? null;

      // Random ids, not timestamps: two agents answering in the same millisecond would
      // collide, and a patch meant for one reply would land on the other.
      const userId = crypto.randomUUID();
      const replyId = crypto.randomUUID();

      setAllMessages((current) => [
        ...current,
        { id: userId, role: "user", content: trimmed, agent },
        {
          id: replyId,
          role: "assistant",
          content: "",
          agent,
          done: false,
          activity: null,
        },
      ]);

      const controller = new AbortController();
      activeStreamsRef.current[agent.id] = controller;
      markStreaming(agent.id, true);

      // Only the opening message of a conversation carries the member context; after
      // that the agent has it in session memory and repeating it wastes tokens.
      const message = sessionId
        ? trimmed
        : [
            memberId ? `[Member context: ${memberName ?? "member"} (${memberId})]` : null,
            trimmed,
          ]
            .filter(Boolean)
            .join("\n\n");

      try {
        await streamChatMessage(agent.id, {
          message,
          sessionId,
          signal: controller.signal,
          onEvent: (event, data) => {
            if (event === "token") {
              // Clearing `activity` on the first real token stops the tool status
              // lingering underneath the answer.
              patchMessage(replyId, (m) => ({
                content: m.content + (data.content ?? ""),
                activity: null,
              }));
              return;
            }
            if (event === "activity") {
              patchMessage(replyId, { activity: data.content || null });
              return;
            }
            if (event === "done") {
              // First write wins. Later turns return their own execution id, which is
              // not the conversation handle. Skipped entirely if the thread was reset
              // mid-flight, so a cleared conversation cannot be revived by a late frame.
              if (
                data.sessionId &&
                !sessionsRef.current[agent.id] &&
                activeStreamsRef.current[agent.id] === controller
              ) {
                sessionsRef.current[agent.id] = data.sessionId;
              }
              patchMessage(replyId, { done: true, activity: null });
              return;
            }
            if (event === "failed") {
              patchMessage(replyId, {
                role: "error",
                content: data.detail ?? "Something went wrong.",
                done: true,
                activity: null,
              });
            }
          },
        });
      } catch (err) {
        // Aborting is a user action, not a failure — keep whatever arrived. If the
        // abort came from a reset the message is already gone, and the patch is a no-op.
        if (err.name === "AbortError") {
          patchMessage(replyId, (m) => ({
            done: true,
            activity: null,
            content: m.content || "Stopped.",
          }));
        } else {
          patchMessage(replyId, {
            role: "error",
            content: err.message,
            done: true,
            activity: null,
          });
        }
      } finally {
        // Only clear the slot if it is still ours; a reset may have started a new run.
        if (activeStreamsRef.current[agent.id] === controller) {
          delete activeStreamsRef.current[agent.id];
        }
        markStreaming(agent.id, false);
      }
    },
    [selectedAgent, memberId, memberName, patchMessage, markStreaming]
  );

  return {
    agents,
    selectedAgent,
    selectAgent: setAgentId,
    /** The selected agent's thread only. */
    messages,
    sendMessage,
    stopStreaming,
    resetSession,
    loadError,
    isStreaming: selectedAgent ? streamingAgents.has(selectedAgent.id) : false,
    /** Derived from state, not the session ref, so the button re-renders when it changes. */
    canReset: messages.length > 0,
    /** Total replies across every agent — the launcher badge. */
    replyCount: allMessages.filter((m) => m.role !== "user").length,
    /** Agents with an unread-ish thread, for the dot on the inactive tab. */
    hasThread: (id) => allMessages.some((m) => m.agent?.id === id),
  };
}

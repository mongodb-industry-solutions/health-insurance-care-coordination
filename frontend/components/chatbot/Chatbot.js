"use client";

import { useEffect, useRef, useState } from "react";
import Icon from "@leafygreen-ui/icon";

import ChatMessage from "./ChatMessage";
import { useChat } from "./useChat";
import styles from "./Chatbot.module.css";

const SUGGESTIONS = {
  insurance: [
    "What does my plan cover for specialist visits?",
    "Why was my most recent claim denied?",
    "How much have I paid out of pocket this year?",
  ],
  care_coordination: [
    "Summarise my clinical history.",
    "What treatments have I already tried?",
    "Why is a prior authorization needed for my treatment?",
  ],
};

/**
 * Floating assistant: a launcher pinned to the bottom-right that expands into a modal
 * conversation with either agent.
 *
 * Each agent keeps its own thread — switching tabs swaps the whole transcript rather than
 * mixing both agents into one feed, so a conversation about a claim never gets tangled up
 * with one about treatment. Replies still stream concurrently: an answer that lands while
 * you are reading the other agent is waiting when you switch back. See `useChat.js`.
 *
 * @param {object} props
 * @param {string} [props.memberId]    Given to the agent as opening context.
 * @param {string} [props.memberName]
 */
export default function Chatbot({ memberId, memberName }) {
  const [isOpen, setIsOpen] = useState(false);
  const [draft, setDraft] = useState("");

  const chat = useChat({ memberId, memberName });
  const {
    agents,
    selectedAgent,
    selectAgent,
    messages,
    sendMessage,
    stopStreaming,
    resetSession,
    isStreaming,
    canReset,
    loadError,
    replyCount,
    hasThread,
  } = chat;

  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  // Escape closes, matching ProcessOverlay. Bound only while open so it never competes
  // with another dialog's handler.
  useEffect(() => {
    if (!isOpen) return;
    const onKeyDown = (e) => {
      if (e.key === "Escape") setIsOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isOpen]);

  useEffect(() => {
    if (isOpen) bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages, isOpen]);

  // Refocus after a switch, and on open. The textarea is disabled while the selected
  // agent streams, and the browser blurs a disabled element — so focusing on send alone
  // would not survive.
  useEffect(() => {
    if (isOpen) inputRef.current?.focus();
  }, [isOpen, selectedAgent?.id]);

  const submit = (e) => {
    e?.preventDefault();
    if (!draft.trim() || isStreaming) return;
    sendMessage(draft);
    setDraft("");
  };

  const onKeyDown = (e) => {
    // Enter sends, Shift+Enter breaks the line — the convention every chat uses.
    if (e.key === "Enter" && !e.shiftKey) submit(e);
  };

  const accent = selectedAgent?.accent ?? "var(--color-green)";

  if (!isOpen) {
    return (
      <button
        type="button"
        className={styles.launcher}
        onClick={() => setIsOpen(true)}
        aria-label="Open the assistant"
        title="Ask the assistant"
      >
        <span className={styles.launcherGlow} aria-hidden="true" />
        <Icon glyph="Sparkle" size={20} />
        <span className={styles.launcherText}>Ask an agent</span>
        {replyCount > 0 && (
          <span className={styles.launcherBadge} aria-hidden="true">
            {replyCount}
          </span>
        )}
      </button>
    );
  }

  return (
    <>
      <div
        className={styles.backdrop}
        onClick={() => setIsOpen(false)}
        aria-hidden="true"
      />
      <div className={styles.wrap}>
        <section
          className={styles.panel}
          role="dialog"
          aria-modal="true"
          aria-label="Assistant"
          style={{ "--accent": accent }}
        >
          <header className={styles.header}>
            <div className={styles.headTop}>
              <div className={styles.headings}>
                <h2 className={styles.title}>Assistant</h2>
                <p className={styles.subtitle}>
                  {memberName ? `On behalf of ${memberName}` : "Ask about coverage or care"}
                </p>
              </div>
              <button
                type="button"
                className={styles.close}
                onClick={() => setIsOpen(false)}
                aria-label="Close the assistant"
                title="Close"
              >
                <Icon glyph="X" size={16} />
              </button>
            </div>

            <div className={styles.agentRow} role="tablist" aria-label="Choose an agent">
              {agents.map((agent) => {
                const active = agent.id === selectedAgent?.id;
                return (
                  <button
                    key={agent.id}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    className={`${styles.agentTab} ${active ? styles.agentTabActive : ""}`}
                    style={{ "--tab-accent": agent.accent }}
                    onClick={() => selectAgent(agent.id)}
                  >
                    {/* Solid on the inactive tab too when that agent has a thread —
                        otherwise switching away makes a conversation look lost. */}
                    <span
                      className={`${styles.agentDot} ${
                        hasThread(agent.id) ? styles.agentDotActive : ""
                      }`}
                      aria-hidden="true"
                    />
                    <span className={styles.agentLabel}>{agent.label}</span>
                    <span className={styles.agentBlurb}>{agent.blurb}</span>
                  </button>
                );
              })}
            </div>
          </header>

          <div className={styles.transcript}>
            {loadError && (
              <p className={styles.loadError}>
                The assistant is unavailable: {loadError}
              </p>
            )}

            {messages.length === 0 && !loadError && (
              <div className={styles.empty}>
                <p className={styles.emptyTitle}>
                  {selectedAgent
                    ? `Ask the ${selectedAgent.label} anything`
                    : "Loading agents…"}
                </p>
                <div className={styles.suggestions}>
                  {(SUGGESTIONS[selectedAgent?.id] ?? []).map((prompt) => (
                    <button
                      key={prompt}
                      type="button"
                      className={styles.suggestion}
                      onClick={() => sendMessage(prompt)}
                    >
                      <span>{prompt}</span>
                      <Icon glyph="ChevronRight" size={14} />
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((message) => (
              <ChatMessage key={message.id} message={message} />
            ))}

            <div ref={bottomRef} />
          </div>

          <form className={styles.composer} onSubmit={submit}>
            <textarea
              ref={inputRef}
              className={styles.input}
              value={draft}
              rows={1}
              placeholder={
                isStreaming
                  ? `${selectedAgent?.label ?? "The agent"} is replying…`
                  : "Ask a question…"
              }
              disabled={isStreaming || !selectedAgent}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
              aria-label="Message"
            />
            <div className={styles.composerBar}>
              <button
                type="button"
                className={styles.newChat}
                onClick={() => resetSession(selectedAgent?.id)}
                disabled={!canReset}
                title="Clear this agent's conversation. The other agent's thread is untouched."
              >
                New chat
              </button>

              {isStreaming ? (
                <button
                  type="button"
                  className={styles.stop}
                  onClick={() => stopStreaming(selectedAgent?.id)}
                >
                  Stop
                </button>
              ) : (
                <button
                  type="submit"
                  className={styles.send}
                  disabled={!draft.trim() || !selectedAgent}
                >
                  Send
                  <Icon glyph="ArrowRight" size={14} />
                </button>
              )}
            </div>
          </form>
        </section>
      </div>
    </>
  );
}

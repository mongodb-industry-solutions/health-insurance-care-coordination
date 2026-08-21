"use client";

import { useState } from "react";
import Button from "@leafygreen-ui/button";
import Icon from "@leafygreen-ui/icon";
import MemberCard from "@/components/memberCard/MemberCard";
import { resetDemo } from "@/lib/api/admin";
import { MEMBERS } from "@/lib/const/members";
import styles from "./MemberSelection.module.css";

/**
 * Landing hero plus the "log in as" member picker.
 *
 * @param {(member: object) => void} props.onSelect  Called when a card is picked.
 * @param {(member: object) => void} props.onStart  Called when "Start Demo" is pressed.
 */
export default function MemberSelection({ members = MEMBERS, onSelect, onStart }) {
  const [selectedId, setSelectedId] = useState(null);
  const selectedMember =
    members.find((member) => member.memberId === selectedId) ?? null;

  // Reset is destructive, so the button asks first: one click arms the inline
  // confirm, a second one in that panel actually runs it. Plain markup rather
  // than a dialog component — the panel sits in the flow directly under the
  // button, so nothing has to trap focus or portal out.
  const [confirming, setConfirming] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [resetState, setResetState] = useState(null); // {ok, message} | null

  const handleSelect = (member) => {
    setSelectedId(member.memberId);
    onSelect?.(member);
  };

  const handleReset = async () => {
    setResetting(true);
    setResetState(null);
    try {
      await resetDemo();
      // Any member picked before the wipe refers to state that no longer exists.
      setSelectedId(null);
      setResetState({ ok: true, message: "Demo data reset. Ready for a new run." });
    } catch (error) {
      setResetState({ ok: false, message: `Reset failed: ${error.message}` });
    } finally {
      // Dismissed either way; the outcome is reported below the picker so the
      // message outlives the panel and stays readable while you pick a member.
      setResetting(false);
      setConfirming(false);
    }
  };

  return (
    <section className={styles.section}>
      <h1 className={styles.heading}>
        Welcome to the{" "}
        <span className={styles.headingAccent}>
          Leafy Health Insurance Platform
        </span>
      </h1>
      <p className={styles.subheading}>Your peace of mind is our priority.</p>

      <div className={styles.cards}>
        {members.map((member) => (
          <MemberCard
            key={member.memberId}
            member={member}
            selected={member.memberId === selectedId}
            onSelect={handleSelect}
          />
        ))}
      </div>

      <p className={styles.instruction}>
        Please select the user you would like to login as.
      </p>

      <div className={styles.actions}>
        <Button
          className={styles.startButton}
          variant="primary"
          disabled={!selectedMember}
          rightGlyph={<Icon glyph="ArrowRight" />}
          onClick={() => onStart?.(selectedMember)}
        >
          {selectedMember
            ? `Start Demo as ${selectedMember.firstName}`
            : "Start Demo"}
        </Button>

        {/* Demo-operator control, not a member-facing one: restores every
            member's baseline so the next run starts from a known state. */}
        <Button
          className={styles.resetButton}
          variant="dangerOutline"
          disabled={resetting || confirming}
          onClick={() => {
            setResetState(null);
            setConfirming(true);
          }}
        >
          Reset demo
        </Button>
      </div>

      {confirming && (
        <div className={styles.confirm} role="alertdialog" aria-label="Reset demo data">
          <p className={styles.confirmTitle}>Reset demo data?</p>
          <p className={styles.confirmBody}>
            This wipes every seeded collection — members, policies, claims, audit
            traces, notifications, guidelines and plans — then reseeds the
            canonical members and shared catalog. Any authorization run recorded
            so far is discarded. Takes a second or two.
          </p>
          <div className={styles.confirmActions}>
            <Button variant="danger" disabled={resetting} onClick={handleReset}>
              {resetting ? "Resetting…" : "Yes, reset everything"}
            </Button>
            <Button disabled={resetting} onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {resetState && (
        <p
          className={resetState.ok ? styles.resetOk : styles.resetError}
          role="status"
        >
          {resetState.message}
        </p>
      )}
    </section>
  );
}

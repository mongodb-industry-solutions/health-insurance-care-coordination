"use client";

import { useState } from "react";
import Button from "@leafygreen-ui/button";
import Icon from "@leafygreen-ui/icon";
import MemberCard from "@/components/memberCard/MemberCard";
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

  const handleSelect = (member) => {
    setSelectedId(member.memberId);
    onSelect?.(member);
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

      <Button
        className={styles.startButton}
        variant="primary"
        disabled={!selectedMember}
        rightGlyph={<Icon glyph="ArrowRight" />}
        onClick={() => onStart?.(selectedMember)}
      >
        {selectedMember ? `Start Demo as ${selectedMember.firstName}` : "Start Demo"}
      </Button>
    </section>
  );
}

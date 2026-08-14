"use client";

import Image from "next/image";
import MemberInfoCard from "@/components/memberInfoCard/MemberInfoCard";
import { useMemberCard } from "./useMemberCard";
import styles from "./MemberCard.module.css";

/**
 * A single selectable member profile: avatar + name acting as one button, with
 * an info card that appears on hover or keyboard focus.
 *
 * @param {object} props.member  One entry of MEMBERS.
 * @param {boolean} props.selected  Toggles the filled background.
 * @param {(member: object) => void} props.onSelect
 */
export default function MemberCard({ member, selected = false, onSelect }) {
  const { wrapperRef, infoVisible, flipped, show, hide } = useMemberCard();

  return (
    <div
      className={styles.wrapper}
      ref={wrapperRef}
      onMouseEnter={show}
      onMouseLeave={hide}
    >
      <button
        type="button"
        className={`${styles.card} ${selected ? styles.selected : ""}`}
        aria-pressed={selected}
        aria-describedby={
          infoVisible ? `member-info-${member.memberId}` : undefined
        }
        onFocus={show}
        onBlur={hide}
        onClick={() => onSelect?.(member)}
      >
        <Image
          className={styles.avatar}
          src={member.avatar}
          alt=""
          width={74}
          height={74}
        />
        <span className={styles.name}>{member.firstName}</span>
      </button>

      {infoVisible && <MemberInfoCard member={member} flipped={flipped} />}
    </div>
  );
}

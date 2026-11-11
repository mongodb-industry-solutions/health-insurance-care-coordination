"use client";

import { useEffect, useState } from "react";
import Icon from "@leafygreen-ui/icon";
import StoryCard from "@/components/storyCard/StoryCard";
import { getMemberStory } from "@/lib/const/memberStories";
import { useStoryCarousel } from "./useStoryCarousel";
import styles from "./StoryCarousel.module.css";

const EXIT_DURATION = 450;

/**
 * Guided story shown over a dark veil once a member is selected.
 *
 * Two ways out, both deliberate: "Go to Demo" on the last card carries on to the
 * dashboard, and "Choose a different patient" (or Escape) backs out to the picker
 * for someone who picked the wrong member. There is still no click-outside
 * dismissal, so a stray click cannot skip the narrative or lose the selection.
 *
 * @param {object} props.member  The selected member.
 * @param {() => void} props.onFinish  Called after the exit animation completes.
 * @param {() => void} [props.onCancel]  Called, after the same animation, when the
 *   viewer backs out to choose a different patient.
 */
export default function StoryCarousel({ member, onFinish, onCancel }) {
  const story = getMemberStory(member.memberId);
  const cards = story?.cards ?? [];
  const [leaving, setLeaving] = useState(false);
  const { index, goTo, next, previous, isFirst, isLast, touchHandlers } =
    useStoryCarousel(cards.length);

  // Leaves through the exit animation, then hands control back. Guarded so a second
  // click, or Escape pressed while the veil is fading, cannot fire the callback twice.
  const leave = (callback) => {
    if (leaving) return;
    setLeaving(true);
    window.setTimeout(() => callback?.(), EXIT_DURATION);
  };
  const handleFinish = () => leave(onFinish);
  const handleCancel = () => leave(onCancel);

  // Escape backs out to the picker, the same as the button. Bound on every render so it
  // always sees the current `leaving`.
  useEffect(() => {
    const handleKeyDown = (event) => {
      if (event.key === "Escape") handleCancel();
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  });

  if (!cards.length) return null;

  return (
    <div
      className={`${styles.veil} ${leaving ? styles.leaving : ""}`}
      role="dialog"
      aria-modal="true"
      aria-label={`${member.firstName}'s story`}
    >
      <div className={styles.stage} {...touchHandlers}>
        <button
          type="button"
          className={styles.arrow}
          onClick={previous}
          disabled={isFirst}
          aria-label="Previous card"
        >
          <Icon glyph="ChevronLeft" size={24} />
        </button>

        <div className={styles.column}>
          <div className={styles.viewport}>
            <div
              className={styles.track}
              style={{ transform: `translateX(-${index * 100}%)` }}
            >
              {cards.map((card, cardIndex) => (
                <div
                  key={card.eyebrow}
                  className={`${styles.slide} ${
                    cardIndex === index ? styles.slideActive : ""
                  }`}
                  aria-hidden={cardIndex !== index}
                >
                  <StoryCard
                    card={card}
                    member={member}
                    index={cardIndex}
                    total={cards.length}
                    isLast={cardIndex === cards.length - 1}
                    onFinish={handleFinish}
                  />
                </div>
              ))}
            </div>
          </div>

          <div className={styles.dots}>
            {cards.map((card, cardIndex) => (
              <button
                key={card.eyebrow}
                type="button"
                className={`${styles.dot} ${
                  cardIndex === index ? styles.dotActive : ""
                }`}
                onClick={() => goTo(cardIndex)}
                aria-label={`Go to card ${cardIndex + 1}`}
                aria-current={cardIndex === index}
              />
            ))}
          </div>

          <button
            type="button"
            className={styles.exit}
            onClick={handleCancel}
            title="Back to patient selection (Esc)"
          >
            <Icon glyph="X" size={16} />
            <span>Choose a different patient</span>
          </button>
        </div>

        <button
          type="button"
          className={styles.arrow}
          onClick={next}
          disabled={isLast}
          aria-label="Next card"
        >
          <Icon glyph="ChevronRight" size={24} />
        </button>
      </div>
    </div>
  );
}

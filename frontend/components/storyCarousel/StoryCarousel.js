"use client";

import { useState } from "react";
import Icon from "@leafygreen-ui/icon";
import StoryCard from "@/components/storyCard/StoryCard";
import { getMemberStory } from "@/lib/const/memberStories";
import { useStoryCarousel } from "./useStoryCarousel";
import styles from "./StoryCarousel.module.css";

const EXIT_DURATION = 450;

/**
 * Guided story shown over a dark veil once a member is selected. There is no
 * click-outside or Escape dismissal on purpose — the only way out is the
 * "Go to Demo" button on the last card, so the narrative can't be skipped.
 *
 * @param {object} props.member  The selected member.
 * @param {() => void} props.onFinish  Called after the exit animation completes.
 */
export default function StoryCarousel({ member, onFinish }) {
  const story = getMemberStory(member.memberId);
  const cards = story?.cards ?? [];
  const [leaving, setLeaving] = useState(false);
  const { index, goTo, next, previous, isFirst, isLast, touchHandlers } =
    useStoryCarousel(cards.length);

  if (!cards.length) return null;

  const handleFinish = () => {
    setLeaving(true);
    window.setTimeout(() => onFinish?.(), EXIT_DURATION);
  };

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

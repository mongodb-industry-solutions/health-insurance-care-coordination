import { useCallback, useEffect, useRef, useState } from "react";

const SWIPE_THRESHOLD = 50; // px of horizontal travel that counts as a swipe

/**
 * Index state for the story carousel, plus arrow-key and swipe navigation.
 *
 * @param {number} total  Number of cards.
 */
export function useStoryCarousel(total) {
  const [index, setIndex] = useState(0);
  const touchStartX = useRef(null);

  const goTo = useCallback(
    (next) => setIndex(Math.min(Math.max(next, 0), total - 1)),
    [total]
  );

  const next = useCallback(() => goTo(index + 1), [goTo, index]);
  const previous = useCallback(() => goTo(index - 1), [goTo, index]);

  useEffect(() => {
    const handleKeyDown = (event) => {
      if (event.key === "ArrowRight") next();
      if (event.key === "ArrowLeft") previous();
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [next, previous]);

  const touchHandlers = {
    onTouchStart: (event) => {
      touchStartX.current = event.touches[0].clientX;
    },
    onTouchEnd: (event) => {
      if (touchStartX.current === null) return;

      const travel = event.changedTouches[0].clientX - touchStartX.current;
      if (travel <= -SWIPE_THRESHOLD) next();
      if (travel >= SWIPE_THRESHOLD) previous();

      touchStartX.current = null;
    },
  };

  return {
    index,
    goTo,
    next,
    previous,
    isFirst: index === 0,
    isLast: index === total - 1,
    touchHandlers,
  };
}

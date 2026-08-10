import { useCallback, useRef, useState } from "react";

const INFO_CARD_WIDTH = 340;
const VIEWPORT_MARGIN = 16;

/**
 * Hover/focus state for a member card, plus the collision check that decides
 * whether the info card hangs to the right or flips to the left.
 */
export function useMemberCard() {
  const wrapperRef = useRef(null);
  const [infoVisible, setInfoVisible] = useState(false);
  const [flipped, setFlipped] = useState(false);

  const show = useCallback(() => {
    const wrapper = wrapperRef.current;

    if (wrapper) {
      const { left } = wrapper.getBoundingClientRect();
      const overflowsRight =
        left + INFO_CARD_WIDTH > window.innerWidth - VIEWPORT_MARGIN;
      setFlipped(overflowsRight);
    }

    setInfoVisible(true);
  }, []);

  const hide = useCallback(() => setInfoVisible(false), []);

  return { wrapperRef, infoVisible, flipped, show, hide };
}

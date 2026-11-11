import { useCallback, useEffect, useState } from "react";

const EXIT_DURATION = 250;

/**
 * Close-with-exit-animation plus Escape handling for the tool drawer.
 *
 * @param {boolean} isOpen
 * @param {() => void} onClose
 */
export function useToolDrawer(isOpen, onClose) {
  const [leaving, setLeaving] = useState(false);

  const requestClose = useCallback(() => {
    setLeaving(true);
    window.setTimeout(() => {
      setLeaving(false);
      onClose?.();
    }, EXIT_DURATION);
  }, [onClose]);

  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (event) => {
      if (event.key === "Escape") requestClose();
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, requestClose]);

  return { leaving, requestClose };
}

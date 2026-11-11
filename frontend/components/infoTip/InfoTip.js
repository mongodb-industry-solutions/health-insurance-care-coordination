"use client";

import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import Icon from "@leafygreen-ui/icon";
import { boundsFor, placePopup } from "./placement";
import styles from "./InfoTip.module.css";

/** The widest a pop-up gets; narrower when the drawer it sits in is. */
const MAX_WIDTH = 270;

/**
 * A small "i" that explains a term in a pop-up.
 *
 * Opens on hover and on keyboard focus, and stays open when clicked (so it works
 * on touch screens, and so the text can be read without holding the pointer
 * still). Closes on Escape, on a click elsewhere, or on a second click.
 *
 * Escape is caught before the tool drawer sees it: closing a pop-up must not also
 * close the drawer it sits in.
 *
 * @param {string} props.label  What it explains. Becomes the accessible name.
 * @param {string} [props.title]  Optional bold first line of the pop-up.
 * @param {"start"|"end"} [props.align]  Which edge of the "i" the pop-up starts from.
 *   Only a starting point: once open, the pop-up measures itself against the drawer
 *   it sits in and slides (or flips above the "i") so it is never cut off, whatever
 *   this says.
 * @param {React.ReactNode} props.children  The explanation. Keep it to a few lines.
 */
export default function InfoTip({ label, title, align = "start", children }) {
  const id = useId();
  const root = useRef(null);
  const popup = useRef(null);
  const [hovered, setHovered] = useState(false);
  const [pinned, setPinned] = useState(false);
  const open = hovered || pinned;

  // Keep the pop-up inside the drawer. Runs before the browser paints, so it never shows
  // in the wrong place. Done on the element directly: it is a measurement of where the
  // box landed, not state anyone else needs.
  useLayoutEffect(() => {
    const element = popup.current;
    const anchor = root.current;
    if (!open || !element || !anchor) return;

    const bounds = boundsFor(anchor);
    element.style.maxWidth = `${Math.max(120, Math.min(MAX_WIDTH, bounds.right - bounds.left))}px`;

    const { dx, above } = placePopup({
      popup: element.getBoundingClientRect(), // where it lands before any adjustment
      button: anchor.getBoundingClientRect(),
      bounds,
    });

    element.style.translate = `${dx}px 0`;
    if (above) {
      element.style.top = "auto";
      element.style.bottom = "calc(100% + 6px)";
    }
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;

    const close = () => {
      setHovered(false);
      setPinned(false);
    };
    const handleKeyDown = (event) => {
      if (event.key !== "Escape") return;
      // Capture phase + stopPropagation: the drawer listens on `window` and must not
      // see this Escape.
      event.stopPropagation();
      close();
    };
    const handleMouseDown = (event) => {
      if (root.current && !root.current.contains(event.target)) close();
    };

    document.addEventListener("keydown", handleKeyDown, true);
    document.addEventListener("mousedown", handleMouseDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown, true);
      document.removeEventListener("mousedown", handleMouseDown);
    };
  }, [open]);

  return (
    <span
      ref={root}
      className={styles.root}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <button
        type="button"
        className={`${styles.button} ${open ? styles.buttonOpen : ""}`}
        aria-label={`About ${label}`}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => {
          // First click pins it open; a click on a pinned one closes it, even while the
          // pointer is still over it.
          if (pinned) {
            setPinned(false);
            setHovered(false);
          } else {
            setPinned(true);
          }
        }}
        onFocus={() => setHovered(true)}
        onBlur={() => setHovered(false)}
      >
        <Icon glyph="InfoWithCircle" size={14} />
      </button>

      {open && (
        <span
          ref={popup}
          id={id}
          role="tooltip"
          className={`${styles.popup} ${align === "end" ? styles.end : ""}`}
        >
          {title && <strong className={styles.title}>{title}</strong>}
          {children}
        </span>
      )}
    </span>
  );
}

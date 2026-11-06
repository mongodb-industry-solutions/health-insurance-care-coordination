/**
 * Where a pop-up has to sit so it is never cut off.
 *
 * Pure geometry (all values in viewport pixels, as `getBoundingClientRect` gives
 * them), so it can be checked without a browser. The pop-up is measured where it
 * naturally lands: below its "i", lined up with it. This says how far to slide it
 * sideways to stay inside `bounds`, and whether to flip it above the "i" when there
 * is no room below.
 *
 * @param {{left:number,right:number,height:number}} props.popup
 * @param {{top:number,bottom:number}} props.button
 * @param {{left:number,right:number,top:number,bottom:number}} props.bounds
 * @param {number} [props.gap]  Space between the "i" and the pop-up.
 * @returns {{dx:number, above:boolean}}
 */
export function placePopup({ popup, button, bounds, gap = 8 }) {
  let dx = 0;
  if (popup.left < bounds.left) dx = bounds.left - popup.left;
  else if (popup.right > bounds.right) dx = bounds.right - popup.right;

  const roomBelow = bounds.bottom - button.bottom;
  const roomAbove = button.top - bounds.top;
  const above = roomBelow < popup.height + gap && roomAbove > roomBelow;

  return { dx, above };
}

/**
 * The box a pop-up must stay inside: the drawer (or dialog) that holds its "i",
 * clipped to the screen, with a margin. Falls back to the screen itself.
 */
export function boundsFor(anchor, margin = 12) {
  const panel = anchor.closest('[role="dialog"]');
  const box = panel
    ? panel.getBoundingClientRect()
    : { left: 0, right: window.innerWidth, top: 0, bottom: window.innerHeight };

  return {
    left: Math.max(box.left, 0) + margin,
    right: Math.min(box.right, window.innerWidth) - margin,
    top: Math.max(box.top, 0) + margin,
    bottom: Math.min(box.bottom, window.innerHeight) - margin,
  };
}

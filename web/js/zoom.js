// How many cents the chart shows top to bottom, and pinch zoom to change it.
// A pinch or the mouse wheel zooms; a double tap goes back to the automatic size.

export const MIN_SPAN = 600;      // half an octave: the closest view
export const MAX_SPAN = 3600;     // three octaves: the widest view
export const OCTAVE_VIEW = 1400;  // one octave plus half a lane on each side

export const clampSpan = (span) => Math.min(MAX_SPAN, Math.max(MIN_SPAN, span));

/** Automatic size: at least one octave, more on a tall chart (about 50 px per lane). */
export function defaultSpan(chartHeight) {
  return clampSpan(Math.max(OCTAVE_VIEW, Math.min(2400, chartHeight * 2.7)));
}

/** Fingers apart (dist grows) shows fewer cents: zoom in. */
export function pinchSpan(startSpan, startDist, dist) {
  if (!(startDist > 0) || !(dist > 0)) return clampSpan(startSpan);
  return clampSpan((startSpan * startDist) / dist);
}

/** Mouse wheel: down zooms out, up zooms in. */
export function wheelSpan(span, deltaY) {
  return clampSpan(span * Math.exp(deltaY * 0.0015));
}

/**
 * Pinch, wheel and double tap on `el`. `get()` returns the current span,
 * `set(span | null)` stores it (null = automatic again).
 */
export function attachZoom(el, get, set) {
  const pointers = new Map();
  let start = null;
  let lastTap = 0;
  const distance = () => {
    const [a, b] = [...pointers.values()];
    return Math.hypot(a.x - b.x, a.y - b.y);
  };
  el.addEventListener("pointerdown", (e) => {
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size === 2) start = { span: get(), dist: distance() };
    if (pointers.size === 1) {
      if (e.timeStamp - lastTap < 300) set(null);
      lastTap = e.timeStamp;
    }
  });
  el.addEventListener("pointermove", (e) => {
    if (!pointers.has(e.pointerId)) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size === 2 && start) set(pinchSpan(start.span, start.dist, distance()));
  });
  const up = (e) => {
    pointers.delete(e.pointerId);
    if (pointers.size < 2) start = null;
  };
  el.addEventListener("pointerup", up);
  el.addEventListener("pointercancel", up);
  el.addEventListener("wheel", (e) => {
    e.preventDefault();
    set(wheelSpan(get(), e.deltaY));
  }, { passive: false });
}

// Draws the scrolling pitch chart on a canvas: note lanes with blocks (the calm
// default) or the detailed curve with guide lines. Time runs left to right with
// "now" at the right edge; pitch runs bottom to top in cents.

import { noteBlocks } from "./scales.js";

const MIN_GUTTER = 64;      // css px for the note names on the left; grows to fit "Mi koron"
const RIGHT_PAD = 14;
const MAX_JUMP = 500;       // cents; bigger one-frame jumps are detector slips, not drawn

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export class Chart {
  /** `onResize` is called after a resize, which clears the canvas, so it can redraw. */
  constructor(canvas, onResize = () => {}) {
    this.canvas = canvas;
    this.onResize = () => {};
    this.ctx = canvas.getContext("2d");
    this.readColors();
    this.resize();
    this.onResize = onResize;
    new ResizeObserver(() => this.resize()).observe(canvas);
  }

  readColors() {
    this.colors = {
      bg: cssVar("--chart-bg"), laneA: cssVar("--lane-a"), laneB: cssVar("--lane-b"),
      laneTonic: cssVar("--lane-tonic"), laneNow: cssVar("--lane-now"), text: cssVar("--text-dim"),
      textNow: cssVar("--text"), guide: cssVar("--guide"), tonic: cssVar("--tonic"),
      voice: cssVar("--voice"), inTune: cssVar("--in-tune"), offTune: cssVar("--off-tune"),
    };
  }

  resize() {
    const dpr = window.devicePixelRatio || 1;
    const r = this.canvas.getBoundingClientRect();
    this.w = Math.max(1, r.width);
    this.h = Math.max(1, r.height);
    this.canvas.width = Math.round(this.w * dpr);
    this.canvas.height = Math.round(this.h * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.onResize();
  }

  /**
   * view: "notes" | "curve". lanes: [[center, low, high]]. guides: [[cents, label]].
   * name(cents): note name for a lane. current: cents of the note I'm on, or null.
   */
  draw({ times, cents, now, history, center, span, lanes, name, view, tolerance, current }) {
    const { ctx, w, h, colors } = this;
    const lo = center - span / 2, hi = center + span / 2;
    // Measured over all lanes (the names repeat each octave), so it does not shift while scrolling.
    const allNames = lanes.map(([c]) => name(c));
    ctx.font = "700 15px system-ui, sans-serif";
    const GUTTER = Math.max(MIN_GUTTER, ...allNames.map((n) => ctx.measureText(n).width + 20));
    const plotW = w - GUTTER - RIGHT_PAD;
    const y = (c) => ((hi - c) / span) * h;
    const x = (t) => GUTTER + ((t - (now - history)) / history) * plotW;
    const isTonic = (c) => Math.abs(((c % 1200) + 1200) % 1200) < 1e-6 ||
                           Math.abs(((c % 1200) + 1200) % 1200 - 1200) < 1e-6;

    ctx.fillStyle = colors.bg;
    ctx.fillRect(0, 0, w, h);

    // Lanes keep their index so the stripes don't swap colors while the view moves.
    const visible = lanes.map((lane, i) => [...lane, i]).filter(([, l, u]) => u > lo && l < hi);
    ctx.font = "500 15px system-ui, sans-serif";
    ctx.textBaseline = "middle";
    ctx.textAlign = "right";

    if (view === "notes") {
      visible.forEach(([c, l, u, i]) => {
        const now_ = current !== null && Math.abs(c - current) < 1e-6;
        ctx.fillStyle = isTonic(c) ? colors.laneTonic : now_ ? colors.laneNow
          : i % 2 ? colors.laneA : colors.laneB;
        ctx.fillRect(0, y(u), w, y(l) - y(u));
      });
    } else {
      ctx.setLineDash([4, 6]);
      for (const [c] of visible) {
        ctx.strokeStyle = isTonic(c) ? colors.tonic : colors.guide;
        ctx.lineWidth = isTonic(c) ? 2 : 1;
        if (isTonic(c)) ctx.setLineDash([]);
        ctx.beginPath();
        ctx.moveTo(GUTTER, y(c));
        ctx.lineTo(w, y(c));
        ctx.stroke();
        ctx.setLineDash([4, 6]);
      }
      ctx.setLineDash([]);
    }

    // Note names in the gutter, the current one brighter.
    for (const [c] of visible) {
      const now_ = current !== null && Math.abs(c - current) < 1e-6;
      ctx.fillStyle = now_ ? colors.textNow : isTonic(c) ? colors.tonic : colors.text;
      ctx.font = `${now_ ? 700 : 500} 15px system-ui, sans-serif`;
      ctx.fillText(name(c), GUTTER - 10, y(c));
    }

    // Visible part of the trace.
    const t0 = now - history - 0.2;
    let start = times.length;
    while (start > 0 && times[start - 1] >= t0) start--;
    const ts = times.slice(start), cs = cents.slice(start);

    if (view === "notes") {
      const centers = visible.map(([c]) => c);
      for (const b of noteBlocks(ts, cs, centers)) {
        const lane = visible.find(([c]) => c === b.center);
        const half = ((y(lane[1]) - y(lane[2])) / 2) * 0.62;
        ctx.fillStyle = Math.abs(b.dev) <= tolerance ? colors.inTune : colors.offTune;
        roundRect(ctx, x(b.t0), y(b.center) - half, Math.max(2, x(b.t1) - x(b.t0)), 2 * half, 6);
      }
    }

    // The voice itself: a thin line over the blocks, a stronger one in the curve view.
    ctx.strokeStyle = colors.voice;
    ctx.lineWidth = view === "notes" ? 1.5 : 2.5;
    ctx.lineJoin = "round";
    ctx.beginPath();
    let pen = false;
    for (let i = 0; i < ts.length; i++) {
      const c = cs[i];
      if (!Number.isFinite(c) || (i > 0 && Math.abs(c - cs[i - 1]) > MAX_JUMP)) {
        pen = false;
        if (!Number.isFinite(c)) continue;
      }
      if (pen) ctx.lineTo(x(ts[i]), y(c));
      else ctx.moveTo(x(ts[i]), y(c));
      pen = true;
    }
    ctx.stroke();

    // A dot at "now" while I'm singing.
    const last = cs.length - 1;
    if (last >= 0 && Number.isFinite(cs[last]) && cs[last] > lo && cs[last] < hi) {
      ctx.fillStyle = colors.voice;
      ctx.beginPath();
      ctx.arc(x(ts[last]), y(cs[last]), 6, 0, 2 * Math.PI);
      ctx.fill();
    }
  }
}

function roundRect(ctx, x, y, w, h, r) {
  r = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.fill();
}

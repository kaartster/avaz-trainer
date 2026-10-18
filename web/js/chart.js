// Draws pitch on a canvas: note lanes with blocks (the calm default) or detailed
// curves with guide lines. Time runs left to right, pitch bottom to top in cents.
// Layers: the teacher (blue blocks) and me (green when on the note, orange when
// off), each a thin line on top so ornaments stay visible.

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
      teacher: cssVar("--teacher"), teacherLine: cssVar("--teacher-line"),
      shade: cssVar("--shade"), cursor: cssVar("--cursor"),
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
   * t0, t1: time range shown. center, span: cents range shown.
   * lanes: [[center, low, high]]. name(cents): note name of a lane.
   * view: "notes" | "curve". current: cents of the lane to highlight, or null.
   * layers: [{times, cents, role: "teacher" | "mine"}]. Times must be increasing.
   * cursor: time of a vertical line, or null. shade: [from, to] to tint, or null.
   */
  draw({ t0, t1, center, span, lanes, name, view, tolerance, current = null,
         layers = [], cursor = null, shade = null }) {
    const { ctx, w, h, colors } = this;
    const lo = center - span / 2, hi = center + span / 2;
    // Measured over all lanes (the names repeat each octave), so it does not shift while scrolling.
    ctx.font = "700 15px system-ui, sans-serif";
    const gutter = Math.max(MIN_GUTTER, ...lanes.map(([c]) => ctx.measureText(name(c)).width + 20));
    const plotW = w - gutter - RIGHT_PAD;
    const y = (c) => ((hi - c) / span) * h;
    const x = (t) => gutter + ((t - t0) / (t1 - t0)) * plotW;
    const isTonic = (c) => {
      const f = ((c % 1200) + 1200) % 1200;
      return f < 1e-6 || 1200 - f < 1e-6;
    };

    ctx.fillStyle = colors.bg;
    ctx.fillRect(0, 0, w, h);

    // Lanes keep their index so the stripes don't swap colors while the view moves.
    const visible = lanes.map((lane, i) => [...lane, i]).filter(([, l, u]) => u > lo && l < hi);
    const isCurrent = (c) => current !== null && Math.abs(c - current) < 1e-6;

    if (view === "notes") {
      for (const [c, l, u, i] of visible) {
        ctx.fillStyle = isTonic(c) ? colors.laneTonic : isCurrent(c) ? colors.laneNow
          : i % 2 ? colors.laneA : colors.laneB;
        ctx.fillRect(0, y(u), w, y(l) - y(u));
      }
    } else {
      for (const [c] of visible) {
        ctx.setLineDash(isTonic(c) ? [] : [4, 6]);
        ctx.strokeStyle = isTonic(c) ? colors.tonic : colors.guide;
        ctx.lineWidth = isTonic(c) ? 2 : 1;
        ctx.beginPath();
        ctx.moveTo(gutter, y(c));
        ctx.lineTo(w, y(c));
        ctx.stroke();
      }
      ctx.setLineDash([]);
    }

    if (shade) {
      ctx.fillStyle = colors.shade;
      const a = Math.max(gutter, x(shade[0])), b = Math.min(w, x(shade[1]));
      if (b > a) ctx.fillRect(a, 0, b - a, h);
    }

    // Note names in the gutter, the current one brighter.
    ctx.textBaseline = "middle";
    ctx.textAlign = "right";
    for (const [c] of visible) {
      ctx.fillStyle = isCurrent(c) ? colors.textNow : isTonic(c) ? colors.tonic : colors.text;
      ctx.font = `${isCurrent(c) ? 700 : 500} 15px system-ui, sans-serif`;
      ctx.fillText(name(c), gutter - 10, y(c));
    }

    ctx.save();
    ctx.beginPath();
    ctx.rect(gutter - 2, 0, w - gutter + 2, h);
    ctx.clip();
    const centers = visible.map(([c]) => c);
    const halfOf = (c) => {
      const lane = visible.find(([lc]) => lc === c);
      return (y(lane[1]) - y(lane[2])) / 2;
    };
    for (const layer of layers) {
      const { ts, cs } = slice(layer.times, layer.cents, t0 - 0.3, t1 + 0.3);
      const teacher = layer.role === "teacher";
      if (view === "notes") {
        for (const b of noteBlocks(ts, cs, centers)) {
          const half = halfOf(b.center) * (teacher ? 0.82 : 0.5);
          ctx.fillStyle = teacher ? colors.teacher
            : Math.abs(b.dev) <= tolerance ? colors.inTune : colors.offTune;
          roundRect(ctx, x(b.t0), y(b.center) - half, Math.max(2, x(b.t1) - x(b.t0)), 2 * half, 6);
        }
      }
      ctx.strokeStyle = teacher ? colors.teacherLine : colors.voice;
      ctx.lineWidth = view === "notes" ? (teacher ? 1.2 : 1.5) : (teacher ? 2 : 2.5);
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
    }
    ctx.restore();

    if (cursor !== null && cursor >= t0 && cursor <= t1) {
      ctx.strokeStyle = colors.cursor;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x(cursor), 0);
      ctx.lineTo(x(cursor), h);
      ctx.stroke();
    }

    // A dot at the newest point of my voice while I'm singing.
    const mine = layers.find((l) => l.role === "mine");
    if (mine && mine.times.length) {
      const k = mine.times.length - 1, c = mine.cents[k];
      if (Number.isFinite(c) && c > lo && c < hi && mine.times[k] >= t0 && mine.times[k] <= t1) {
        ctx.fillStyle = colors.voice;
        ctx.beginPath();
        ctx.arc(x(mine.times[k]), y(c), 6, 0, 2 * Math.PI);
        ctx.fill();
      }
    }
  }
}

/** The points with times in [a, b], found by binary search. */
function slice(times, cents, a, b) {
  const lower = (v) => {
    let l = 0, r = times.length;
    while (l < r) {
      const m = (l + r) >> 1;
      if (times[m] < v) l = m + 1; else r = m;
    }
    return l;
  };
  const i = lower(a), j = lower(b);
  return { ts: Array.prototype.slice.call(times, i, j), cs: Array.prototype.slice.call(cents, i, j) };
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

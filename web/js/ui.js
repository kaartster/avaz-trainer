// Small UI helpers shared by the screens.

import { laneEdges } from "./scales.js";

export const $ = (id) => document.getElementById(id);

/** Fill `container` with radio-like option buttons. */
export function options(container, items, current, onPick) {
  container.innerHTML = "";
  for (const { value, label, small } of items) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "opt";
    b.setAttribute("role", "radio");
    b.setAttribute("aria-checked", String(value === current));
    b.textContent = label;
    if (small) {
      const s = document.createElement("small");
      s.textContent = small;
      b.append(s);
    }
    b.addEventListener("click", () => onPick(value));
    container.append(b);
  }
}

let toastTimer = null;
export function toast(text, ms = 4000) {
  const t = $("toast");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), ms);
}

/** Lanes of `scale` around `center` cents. */
export function lanesAround(scale, center) {
  const centers = [...new Set(scale.positionsInRange(center - 1600, center + 1600)
    .map(([c]) => Math.round(c * 1000) / 1000))];
  return laneEdges(centers);
}

/** Cents shown top to bottom: about 50 px per lane. */
export function spanFor(chart) {
  return Math.max(800, Math.min(1600, chart.h * 2.7));
}

/** "3:07" */
export function clock(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** Escape text for innerHTML. */
export function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

"""Draws the teacher's and my pitch on a chart, as note blocks or as detailed curves.

Two looks, switched with one key:

* **notes** (default): one shaded lane per note of the dastgah, named after the
  real note ("Mi", "Fa sori", ...) on the left axis. While a voice stays on a
  note its lane lights up as a block: blue for the teacher, green for me when I
  am within the tolerance of the note, orange when I am further off. Thin curves
  on top still show the ornaments.
* **curve**: the detailed curves in cents with dashed guide lines, as before.

Both views own their plot; this class only owns the items it adds to it.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui

from ..cents import OCTAVE
from ..keys import scale_note_name
from ..notes import break_jumps, lane_edges, note_blocks
from ..scales import Scale

LANE_COLORS = ("#2b3038", "#23272e")
TONIC_LANE = "#26392d"
IN_TUNE = "#2ecc71"
OFF_TUNE = "#e69a1c"


def _rgba(color: str, alpha: int) -> QtGui.QColor:
    c = QtGui.QColor(color)
    c.setAlpha(alpha)
    return c


def _blend(color: str, alpha: int, over: str = LANE_COLORS[0]) -> QtGui.QColor:
    """``color`` at ``alpha`` mixed onto the lane background, as one opaque color.

    The pitch lines must stay opaque: pyqtgraph draws a see-through line as one
    huge path, and Qt 6.11 crashes now and then painting a whole song that way.
    """
    a = alpha / 255
    top, bottom = QtGui.QColor(color), QtGui.QColor(over)
    return QtGui.QColor(*(round(a * t + (1 - a) * b) for t, b in
                          zip(top.getRgb()[:3], bottom.getRgb()[:3])))


class NoteDisplay:
    def __init__(self, plot: pg.PlotWidget, scale: Scale | None, colors: dict,
                 name_tonic_hz: float | None, notes: bool = True, tolerance: float = 25.0):
        self.plot = plot
        self.scale = scale
        self.colors = colors
        self.name_tonic_hz = name_tonic_hz
        self.tolerance = float(tolerance)
        self.notes = bool(notes) and scale is not None
        self.centers: list[float] = []
        self.lanes: list[tuple[float, float, float]] = []
        self._guides: list = []        # items of the curve look
        self._lane_items: list = []    # items of the notes look
        self._teacher = (np.zeros(0), np.zeros(0))
        self._mine = (np.zeros(0), np.zeros(0))

        self.teacher_blocks = pg.BarGraphItem(x0=[0], x1=[0], y0=[0], y1=[0])
        self.teacher_blocks.setZValue(-10)
        self.my_blocks = pg.BarGraphItem(x0=[0], x1=[0], y0=[0], y1=[0])
        self.my_blocks.setZValue(-5)
        for item in (self.teacher_blocks, self.my_blocks):
            item.setVisible(False)
            plot.addItem(item)
        self.teacher_line = plot.plot([], [], connect="finite")
        self.my_line = plot.plot([], [], connect="finite")
        for line in (self.teacher_line, self.my_line):
            # Short segments instead of one path for the whole song (see _blend).
            line.curve.setSegmentedLineMode("on")
        self._style_lines()

    # ---------------------------------------------------------------- setup
    def set_range(self, lo: float, hi: float) -> None:
        """Build guides and lanes for the vertical range ``lo..hi`` cents."""
        for item in self._guides + self._lane_items:
            self.plot.removeItem(item)
        self._guides, self._lane_items = [], []
        tonic_pen = pg.mkPen(self.colors.get("tonic", "#2ca02c"), width=2)
        if self.scale is None:
            line = pg.InfiniteLine(0, angle=0, pen=tonic_pen)
            self.plot.addItem(line)
            self._guides.append(line)
            self.centers, self.lanes = [], []
            self._apply_mode()
            return
        positions = self.scale.positions_in_range(lo - 200, hi + 200)
        for cents, label in positions:
            if not lo <= cents <= hi:
                continue
            is_tonic = abs(cents % OCTAVE) < 1e-6
            pen = tonic_pen if is_tonic else pg.mkPen(self.colors.get("guide", "#888888"), width=1,
                                                        style=QtCore.Qt.DashLine)
            line = pg.InfiniteLine(cents, angle=0, pen=pen, label=label,
                                   labelOpts={"position": 0.01, "color": "#aaaaaa", "movable": False})
            self.plot.addItem(line)
            self._guides.append(line)

        self.centers = sorted({round(c, 3) for c, _ in positions})
        self.lanes = lane_edges(self.centers)
        for i, (center, low, high) in enumerate(self.lanes):
            is_tonic = abs(center % OCTAVE) < 1e-6
            color = TONIC_LANE if is_tonic else LANE_COLORS[i % 2]
            band = pg.LinearRegionItem(values=(low, high), orientation="horizontal", movable=False,
                                       brush=pg.mkBrush(color), pen=pg.mkPen(None))
            band.setZValue(-20)
            self.plot.addItem(band)
            self._lane_items.append(band)
        self._apply_mode()

    def set_name_tonic(self, hz: float | None) -> None:
        """The tonic used to name lanes (mine: what I sing)."""
        self.name_tonic_hz = hz
        self._apply_mode()

    def toggle(self) -> bool:
        if self.scale is not None:
            self.notes = not self.notes
            self._apply_mode()
        return self.notes

    # ---------------------------------------------------------------- data
    def set_teacher(self, times, cents) -> None:
        self._teacher = (np.asarray(times, dtype=float), np.asarray(cents, dtype=float))
        self.teacher_line.setData(*break_jumps(*self._teacher))
        self._update_blocks(self.teacher_blocks, *self._teacher, mine=False)

    def set_mine(self, times, cents) -> None:
        self._mine = (np.asarray(times, dtype=float), np.asarray(cents, dtype=float))
        self.my_line.setData(*break_jumps(*self._mine))
        self._update_blocks(self.my_blocks, *self._mine, mine=True)

    # ---------------------------------------------------------------- drawing
    def _apply_mode(self) -> None:
        for item in self._guides:
            item.setVisible(not self.notes)
        for item in self._lane_items:
            item.setVisible(self.notes)
        axis = self.plot.getAxis("left")
        if self.notes and self.name_tonic_hz:
            axis.setTicks([[(center, scale_note_name(self.name_tonic_hz, center))
                            for center, _, _ in self.lanes], []])
            self.plot.setLabel("left", "note")
        else:
            axis.setTicks(None)
            self.plot.setLabel("left", "cents relative to tonic")
        self._style_lines()
        self._update_blocks(self.teacher_blocks, *self._teacher, mine=False)
        self._update_blocks(self.my_blocks, *self._mine, mine=True)

    def _style_lines(self) -> None:
        teacher = self.colors.get("teacher", "#1f77b4")
        mine = self.colors.get("mine", "#d62728")
        if self.notes:
            self.teacher_line.setPen(pg.mkPen(_blend("#85b7eb", 170), width=1))
            self.my_line.setPen(pg.mkPen(_blend("#ffffff", 220), width=1.3))
        else:
            self.teacher_line.setPen(pg.mkPen(teacher, width=1.3))
            self.my_line.setPen(pg.mkPen(mine, width=2))

    def _update_blocks(self, item: pg.BarGraphItem, times, cents, mine: bool) -> None:
        if not self.notes or not self.lanes or times.size == 0:
            item.setVisible(False)
            return
        b = note_blocks(times, cents, self.centers)
        if b["t0"].size == 0:
            item.setVisible(False)
            return
        half = {center: (high - low) / 2 * 0.85 for center, low, high in self.lanes}
        h = np.array([half[round(c, 3)] for c in b["center"]])
        if mine:
            brushes = [pg.mkBrush(IN_TUNE if abs(d) <= self.tolerance else OFF_TUNE) for d in b["dev"]]
        else:
            brushes = pg.mkBrush(_rgba(self.colors.get("teacher", "#1f77b4"), 150))
        item.setOpts(x0=b["t0"], x1=b["t1"], y0=b["center"] - h, y1=b["center"] + h,
                     brushes=brushes if mine else None, brush=None if mine else brushes,
                     pen=pg.mkPen(None))
        item.setVisible(True)

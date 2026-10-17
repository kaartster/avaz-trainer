"""Scrolling live pitch chart with scale guide lines and a deviation readout."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from ..cents import OCTAVE
from ..live import LiveTrace, PitchStream
from ..scales import Scale, nearest_note


class LiveView(QtWidgets.QMainWindow):
    def __init__(self, source, stream: PitchStream, scale: Scale | None, settings: dict,
                 title: str = "avaz live"):
        super().__init__()
        self.source = source
        self.stream = stream
        self.scale = scale
        live = settings.get("live", {})
        colors = settings.get("colors", {})
        self.tolerance = float(settings.get("scoring", {}).get("tolerance_cents", 25))
        self.history = float(live.get("history_seconds", 8))
        self.lo, self.hi = [float(v) for v in live.get("cents_range", [-700, 1900])]
        self.trace = LiveTrace(self.history, stream.hop_length / stream.sample_rate)
        self.paused = False

        self.setWindowTitle(title)
        pg.setConfigOptions(antialias=False, background="k", foreground="w")
        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        self.setCentralWidget(central)

        self.plot = pg.PlotWidget()
        self.plot.setLabel("left", "cents relative to tonic")
        self.plot.setLabel("bottom", "seconds")
        self.plot.setYRange(self.lo, self.hi, padding=0)
        self.plot.setMouseEnabled(x=False, y=True)
        self.plot.showGrid(x=False, y=False)
        layout.addWidget(self.plot, stretch=1)

        self._draw_guides(colors)
        self.curve = self.plot.plot([], [], pen=pg.mkPen(colors.get("mine", "#d62728"), width=2),
                                    connect="finite")
        self.marker = pg.ScatterPlotItem(size=10, brush=pg.mkBrush(colors.get("mine", "#d62728")))
        self.plot.addItem(self.marker)

        self.readout = QtWidgets.QLabel("...")
        self.readout.setAlignment(QtCore.Qt.AlignCenter)
        font = QtGui.QFont()
        font.setPointSize(28)
        font.setBold(True)
        self.readout.setFont(font)
        layout.addWidget(self.readout)

        self.status = self.statusBar()
        self.status.showMessage(
            f"input: {getattr(source, 'name', '?')}   tonic: {stream.tonic_hz:.1f} Hz   "
            f"scale: {scale.name if scale else 'none'}   [Esc quit, Space or Enter pause, R reset]")

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._tick)

    def _draw_guides(self, colors):
        if self.scale is None:
            line = pg.InfiniteLine(0, angle=0, pen=pg.mkPen(colors.get("tonic", "#2ca02c"), width=2))
            self.plot.addItem(line)
            return
        for c, label in self.scale.positions_in_range(self.lo, self.hi):
            is_tonic = abs(c % OCTAVE) < 1e-6
            pen = pg.mkPen(colors.get("tonic" if is_tonic else "guide", "#888888"),
                           width=2 if is_tonic else 1,
                           style=QtCore.Qt.SolidLine if is_tonic else QtCore.Qt.DashLine)
            line = pg.InfiniteLine(c, angle=0, pen=pen, label=label,
                                   labelOpts={"position": 0.02, "color": "#aaaaaa",
                                              "movable": False})
            self.plot.addItem(line)

    def start(self):
        self.source.start()
        self.timer.start()

    def closeEvent(self, event):
        self.timer.stop()
        try:
            self.source.stop()
        except Exception:
            pass
        super().closeEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key == QtCore.Qt.Key_Escape:
            self.close()
        elif key in (QtCore.Qt.Key_Space, QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self.paused = not self.paused
        elif key == QtCore.Qt.Key_R:
            self.trace = LiveTrace(self.history, self.stream.hop_length / self.stream.sample_rate)
        else:
            super().keyPressEvent(event)

    def _tick(self):
        blocks = self.source.blocks.drain()
        if self.paused:
            return
        points = []
        for block in blocks:
            points.extend(self.stream.process(block))
        if not points:
            return
        self.trace.append(points)
        t, c = self.trace.window()
        self.curve.setData(t, c)
        now = self.trace.latest_time
        self.plot.setXRange(now - self.history, now, padding=0)
        latest = self.trace.latest_cents
        if np.isfinite(latest):
            self.marker.setData([now], [latest])
        else:
            self.marker.setData([], [])
        self._update_readout()

    def _update_readout(self):
        c = self.trace.stable_cents(0.3)
        if not np.isfinite(c):
            self.readout.setText("...")
            self.readout.setStyleSheet("color: #777777")
            return
        if self.scale is None:
            self.readout.setText(f"{c:+.0f} cents")
            self.readout.setStyleSheet("color: white")
            return
        pos, label, dev = nearest_note(c, self.scale)
        octave = int(np.floor(pos / OCTAVE))
        octave_txt = "" if octave == 0 else f" ({octave:+d} oct)"
        if abs(dev) <= self.tolerance:
            color = "#2ecc71"
        elif abs(dev) <= 2 * self.tolerance:
            color = "#f1c40f"
        else:
            color = "#e74c3c"
        self.readout.setText(f"{label}{octave_txt}   {dev:+.0f} cents")
        self.readout.setStyleSheet(f"color: {color}")


def run_live_view(source, stream: PitchStream, scale: Scale | None, settings: dict,
                  screenshot: str | None = None, quit_after: float | None = None) -> int:
    """Open the window. ``screenshot`` and ``quit_after`` exist for automated checks."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    view = LiveView(source, stream, scale, settings)
    view.resize(1100, 650)
    view.show()
    view.start()
    if quit_after:
        def _finish():
            if screenshot:
                view.grab().save(screenshot)
            view.close()
        QtCore.QTimer.singleShot(int(quit_after * 1000), _finish)
    return app.exec()

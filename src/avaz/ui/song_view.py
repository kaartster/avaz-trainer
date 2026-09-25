"""Freeform practice window: play a whole recording, pause anywhere to sing.

Unlike :mod:`practice_view`, there are no pre-cut phrases. I walk through the
recording myself: Space starts it, Space again pauses it right where I want to
sing, and Space a third time saves what I sang and moves the teacher on from
that same spot. R replays the stretch I just sang instead of moving on. Every
stretch I pause on is saved as a normal phrase (WAV plus pitch curve) the first
time I finish it, so it works afterwards with ``avaz score``, ``avaz history``
and ordinary ``avaz practice``.

Voice start: after a pause the app waits for my voice instead of starting the
clock at the key press, so the time I need to take a breath does not count.
My curve is drawn so that the moment I start singing lines up with the moment
the teacher starts singing in that stretch. The first ``onset_grace_seconds``
after the pause are ignored, because the speakers are still ringing with the
teacher's last note.

Same key: when the teacher sang the recording in my own range (``same_key`` in
the song's song.yaml), my pitch is drawn and scored as it is, measured from the
teacher's tonic, with no transposition and no octave folding.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from ..cents import OCTAVE, octave_shift
from ..live import build_pitch_stream
from ..practice import (IDLE, PLAY, RESPOND, Attempt, FreeformSession, OnsetDetector,
                        PracticeEngine, export_live_segment, first_voiced_time, load_phrase,
                        save_attempt)
from ..scales import Scale

HELP = "Space start/pause/next   R repeat this stretch   V voice start   O octave fold   Esc quit"


class SongView(QtWidgets.QMainWindow):
    def __init__(self, engine: PracticeEngine, song_path: Path, song_audio: np.ndarray,
                 teacher_curve, out_dir: Path, settings: dict, scale: Scale | None,
                 my_tonic: float, same_key: bool = False, view_seconds: float = 20.0):
        super().__init__()
        self.engine = engine
        self.settings = settings
        self.scale = scale
        self.colors = settings.get("colors", {})
        self.teacher_curve = teacher_curve
        self.teacher_tonic = teacher_curve.tonic_hz if teacher_curve is not None else my_tonic
        self.same_key = bool(same_key)
        self.my_tonic = self.teacher_tonic if self.same_key else my_tonic
        self.out_dir = Path(out_dir)
        self.view_seconds = float(view_seconds)
        self.pr = settings.get("practice", {})
        self.fold = False if self.same_key else bool(self.pr.get("fold_octave", True))
        self.voice_start = bool(self.pr.get("start_on_voice", True))
        self.grace_samples = int(float(self.pr.get("onset_grace_seconds", 0.4)) * engine.sample_rate)

        self.freeform = FreeformSession(total_len=song_audio.size)
        self.engine.load(self.freeform, song_audio)
        self._prev_phase = IDLE
        self._exported_key: tuple[int, int] | None = None
        self._exported_wav: Path | None = None
        self.attempt: Attempt | None = None
        self.onset: OnsetDetector | None = None
        self._resp_samples = 0          # samples heard since the pause
        self._voice_at: float | None = None   # seconds from the pause to my voice
        self._my_onset = float("nan")   # where singing starts in my attempt's own times
        self._teacher_onset = 0.0       # where singing starts in the teacher's stretch
        self.shift = 0.0
        self.saved_count = 0

        self._build_ui()
        self.setWindowTitle(f"avaz song: {song_path.stem}")

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    # ------------------------------------------------------------------ UI setup
    def _build_ui(self):
        pg.setConfigOptions(antialias=False, background="k", foreground="w")
        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        self.setCentralWidget(central)

        self.header = QtWidgets.QLabel("")
        font = QtGui.QFont()
        font.setPointSize(13)
        self.header.setFont(font)
        layout.addWidget(self.header)

        self.plot = pg.PlotWidget()
        self.plot.setLabel("left", "cents relative to tonic")
        self.plot.setLabel("bottom", "song time (s)")
        self.plot.setMouseEnabled(x=False, y=True)
        layout.addWidget(self.plot, stretch=1)

        c = self.teacher_curve
        lo, hi = -700.0, 1900.0
        if c is not None:
            finite = c.cents[np.isfinite(c.cents)]
            if finite.size:
                lo = float(np.floor((np.percentile(finite, 0.5) - 200) / 100) * 100)
                hi = float(np.ceil((np.percentile(finite, 99.5) + 200) / 100) * 100)
        self.plot.setYRange(lo, hi, padding=0)
        self._draw_guides(lo, hi)

        self.teacher_line = self.plot.plot(
            c.times if c is not None else [], c.cents if c is not None else [],
            pen=pg.mkPen(self.colors.get("teacher", "#1f77b4"), width=1.3), connect="finite")
        self.my_curve = self.plot.plot([], [], pen=pg.mkPen(self.colors.get("mine", "#d62728"),
                                                            width=2), connect="finite")
        self.cursor = pg.InfiniteLine(0, angle=90, pen=pg.mkPen("#ffffff", width=1))
        self.plot.addItem(self.cursor)
        self.segment_box = pg.LinearRegionItem(values=(0, 0), movable=False,
                                               brush=(255, 255, 255, 20))
        self.segment_box.setVisible(False)
        self.plot.addItem(self.segment_box)

        self.state_label = QtWidgets.QLabel("Space to begin")
        f2 = QtGui.QFont()
        f2.setPointSize(20)
        f2.setBold(True)
        self.state_label.setFont(f2)
        self.state_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.state_label)
        self.statusBar().showMessage(HELP)

    def _draw_guides(self, lo, hi):
        if self.scale is None:
            self.plot.addItem(pg.InfiniteLine(0, angle=0,
                              pen=pg.mkPen(self.colors.get("tonic", "#2ca02c"), width=2)))
            return
        for cents, label in self.scale.positions_in_range(lo, hi):
            is_tonic = abs(cents % OCTAVE) < 1e-6
            pen = pg.mkPen(self.colors.get("tonic" if is_tonic else "guide", "#888888"),
                           width=2 if is_tonic else 1,
                           style=QtCore.Qt.SolidLine if is_tonic else QtCore.Qt.DashLine)
            self.plot.addItem(pg.InfiniteLine(cents, angle=0, pen=pen, label=label,
                              labelOpts={"position": 0.01, "color": "#aaaaaa", "movable": False}))

    # ------------------------------------------------------------------ actions
    def keyPressEvent(self, event):
        key = event.key()
        if key == QtCore.Qt.Key_Escape:
            self.close()
        elif key == QtCore.Qt.Key_Space:
            self.engine.toggle()
        elif key == QtCore.Qt.Key_R:
            self.engine.repeat_segment()
        elif key == QtCore.Qt.Key_V:
            self.voice_start = not self.voice_start
        elif key == QtCore.Qt.Key_O:
            self.fold = not self.fold
            if not self.fold:
                self.shift = 0.0
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.timer.stop()
        try:
            self.engine.stop_session()
            self.engine.close()
        except Exception:
            pass
        super().closeEvent(event)

    # ------------------------------------------------------------------ per frame
    def _tick(self):
        sr = self.engine.sample_rate
        phase = self.freeform.phase
        entering_respond = phase == RESPOND and self._prev_phase != RESPOND
        leaving_respond = self._prev_phase == RESPOND and phase != RESPOND

        if entering_respond:
            self._begin_response()
        for tag, pos, block in self.engine.captured.drain():
            if tag == RESPOND and self.attempt is not None:
                self._feed_response(block)
        if leaving_respond:
            self._end_response()

        self._draw_attempt(sr)
        self._update_cursor(phase, sr)
        self._update_view_range(phase, sr)
        self._update_labels(phase)
        self._prev_phase = phase

    def _waiting_for_voice(self) -> bool:
        return (self.freeform.phase == RESPOND and self.voice_start
                and self.onset is not None and not self.onset.triggered)

    def _begin_response(self):
        sr = self.engine.sample_rate
        start, end = self.freeform.segment_start, self.freeform.segment_end
        stream = build_pitch_stream(self.settings, self.my_tonic)
        if self.voice_start:
            offset = 0.0            # aligned by voice onset, so sound card latency cancels out
        else:
            lat = getattr(self.engine, "latency", (0.0, 0.0))
            cfg = self.pr.get("latency_compensation", "auto")
            offset = lat[0] + lat[1] if cfg == "auto" else float(cfg or 0.0)
        self.attempt = Attempt(stream, time_offset=offset)
        self.onset = OnsetDetector(stream.detector, stream.hop_length,
                                   rms_db=float(self.pr.get("onset_rms_db", -40)),
                                   voiced_frames=int(self.pr.get("onset_voiced_frames", 6)),
                                   preroll_seconds=float(self.pr.get("onset_preroll_seconds", 0.15)))
        self._resp_samples = 0
        self._voice_at = None
        self._my_onset = float("nan")
        self._teacher_onset = 0.0
        c = self.teacher_curve
        if c is not None:
            m = (c.times >= start / sr) & (c.times < end / sr)
            t0 = first_voiced_time(c.times[m] - start / sr, c.f0_hz[m])
            self._teacher_onset = t0 if np.isfinite(t0) else 0.0
        self.my_curve.setData([], [])
        self.shift = 0.0
        if (start, end) != self._exported_key:
            wav = export_live_segment(self.engine.play_buffer, sr, self.teacher_curve,
                                      start / sr, end / sr, self.out_dir)
            self._exported_key, self._exported_wav = (start, end), wav

    def _feed_response(self, block: np.ndarray):
        if not self.voice_start:
            self.attempt.add(block)
            return
        before = self._resp_samples
        self._resp_samples += block.size
        if before < self.grace_samples:
            return                  # the speakers are still ringing with the teacher's note
        if not self.onset.triggered:
            if self.onset.feed(block):
                preroll = self.onset.preroll
                self._voice_at = (self._resp_samples - preroll.size) / self.engine.sample_rate
                self.attempt.add(preroll)
        else:
            self.attempt.add(block)

    def _end_response(self):
        attempt, self.attempt = self.attempt, None
        if attempt is None or self._exported_wav is None:
            return
        if not attempt.blocks:
            self.statusBar().showMessage(f"no voice heard, nothing saved    {HELP}")
            return
        sr = self.engine.sample_rate
        phrase = load_phrase(self._exported_wav, sr)
        extra = {"same_key": self.same_key}
        if self._voice_at is not None:
            extra["voice_start_seconds"] = round(self._voice_at, 3)
        wav = save_attempt(attempt, phrase, "freeform", 1.0, self.teacher_tonic, self.shift,
                           extra=extra)
        self.saved_count += 1
        msg = f"saved {wav.name} ({phrase.name})"
        if self._voice_at is not None:
            msg += f", started singing {self._voice_at:.1f}s after the pause"
        if phrase.curve is not None:
            try:
                from ..compare import score_attempt, record_score
                tol = float(self.settings.get("scoring", {}).get("tolerance_cents", 25))
                result = score_attempt(phrase.curve, attempt.curve(wav.name), tolerance=tol,
                                       same_key=self.same_key)
                record_score(wav, result, "live")
                msg += f"    score: {result.pct_within:.0f}% within {tol:.0f}c, mean {result.mad:.0f}c"
                if abs(result.key_offset) >= 10:
                    word = "sharp" if result.key_offset > 0 else "flat"
                    msg += f", {word} by {abs(result.key_offset):.0f}c overall"
            except Exception as exc:
                msg += f"    (score failed: {exc})"
        self.statusBar().showMessage(f"{msg}    {HELP}")

    # ------------------------------------------------------------------ drawing
    def _x_origin(self, sr: float) -> float:
        """Song time where my attempt's time 0 is drawn."""
        seg = self.freeform.segment_start / sr
        if self.voice_start and np.isfinite(self._my_onset):
            return seg + self._teacher_onset - self._my_onset
        return seg

    def _draw_attempt(self, sr):
        if self.attempt is None or not self.attempt.points:
            return
        t = np.array([p[0] for p in self.attempt.points])
        f0 = np.array([p[1] for p in self.attempt.points])
        cts = np.array([p[2] for p in self.attempt.points])
        if not np.isfinite(self._my_onset):
            self._my_onset = first_voiced_time(t, f0)
        if self.fold and self.teacher_curve is not None:
            c = self.teacher_curve
            seg = c.cents[(c.times >= self.freeform.segment_start / sr) &
                          (c.times < self.freeform.segment_end / sr)]
            self.shift = octave_shift(cts, seg, min_points=5)
        self.my_curve.setData(t + self._x_origin(sr), cts + self.shift)

    def _update_cursor(self, phase, sr):
        if phase != RESPOND:
            self.cursor.setPos(self.freeform.pos / sr)
            return
        seg = self.freeform.segment_start / sr
        if self._waiting_for_voice() or self.attempt is None or not self.attempt.points:
            self.cursor.setPos(seg + (self._teacher_onset if self.voice_start else 0.0))
        else:
            self.cursor.setPos(self.attempt.points[-1][0] + self._x_origin(sr))

    def _update_view_range(self, phase, sr):
        pos = self.freeform.pos / sr
        if phase == RESPOND:
            a, b = self.freeform.segment_start / sr, self.freeform.segment_end / sr
            pad = max(0.3, (b - a) * 0.08)
            self.plot.setXRange(a - pad, b + pad, padding=0)
            self.segment_box.setRegion((a, b))
            self.segment_box.setVisible(True)
        else:
            self.segment_box.setVisible(False)
            if phase == PLAY:
                lead = self.view_seconds * 0.3
                self.plot.setXRange(pos - lead, pos + (self.view_seconds - lead), padding=0)

    def _update_labels(self, phase):
        total_s = self.freeform.total_len / self.engine.sample_rate
        pos_s = self.freeform.pos / self.engine.sample_rate
        key = "same as teacher" if self.same_key else f"transposed to mine ({self.my_tonic:.1f} Hz)"
        self.header.setText(
            f"{pos_s:6.1f} / {total_s:6.1f} s   tonic {self.teacher_tonic:.1f} Hz   key: {key}   "
            f"voice start: {'on' if self.voice_start else 'off'}   "
            f"fold: {'on' if self.fold else 'off'}   saved: {self.saved_count}")
        if phase == IDLE:
            txt, color = ("song finished, close whenever you like" if self.freeform.reached_end
                          else "Space to begin"), "#aaaaaa"
        elif phase == PLAY:
            txt, color = "LISTEN", "#3498db"
        elif self._waiting_for_voice():
            txt, color = "SING WHEN READY", "#f1c40f"
        else:
            txt, color = "YOUR TURN", "#e74c3c"
        if self.shift:
            txt += f"   (curve shifted {self.shift:+.0f} cents)"
        self.state_label.setText(txt)
        self.state_label.setStyleSheet(f"color: {color}")


def run_song_view(engine: PracticeEngine, song_path: Path, song_audio, teacher_curve,
                  out_dir: Path, settings: dict, scale: Scale | None, my_tonic: float,
                  same_key: bool = False, script: list | None = None,
                  screenshot: str | None = None, quit_after: float | None = None) -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    view = SongView(engine, song_path, song_audio, teacher_curve, out_dir, settings, scale,
                    my_tonic, same_key=same_key)
    view.resize(1200, 700)
    view.show()
    engine.start()

    if script:
        t = 0.0
        for step in script:
            if step.startswith("wait:"):
                t += float(step.split(":", 1)[1])
                continue
            if step.startswith("shot:"):
                path = step.split(":", 1)[1]
                QtCore.QTimer.singleShot(int(t * 1000), lambda p=path: view.grab().save(p))
                continue
            if step.startswith("play:"):
                # Test hook: play a file through the speakers as a stand-in for singing.
                def _play(p=step.split(":", 1)[1]):
                    import sounddevice as sd
                    from ..audio_io import load_audio
                    y, sr = load_audio(p)
                    sd.play(y, sr)
                QtCore.QTimer.singleShot(int(t * 1000), _play)
                continue
            action = {"space": engine.toggle, "repeat": engine.repeat_segment}.get(step)
            if action:
                QtCore.QTimer.singleShot(int(t * 1000), action)
    if quit_after:
        def _finish():
            if screenshot:
                view.grab().save(screenshot)
            view.close()
        QtCore.QTimer.singleShot(int(quit_after * 1000), _finish)
    return app.exec()

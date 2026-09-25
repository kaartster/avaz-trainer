"""Real-time pitch detection on short audio blocks.

The rest of the app only uses :class:`PitchDetector`: give it one frame of samples,
get back a frequency in Hz or NaN when the frame is unvoiced. Two backends exist:

* ``NumpyYin``: a self contained YIN implementation. Always available.
* ``AubioYin``: wraps the ``aubio`` library when it is installed.

YIN in one paragraph: for each candidate period ``tau`` it measures how different
the signal is from itself shifted by ``tau`` samples (the "difference function").
A periodic signal gives a dip near zero at its period. The dips are normalised so
the first one below a threshold can be picked reliably, and the exact minimum is
refined by fitting a parabola through three points.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np


class PitchDetector(Protocol):
    frame_length: int
    sample_rate: int

    def detect(self, frame: np.ndarray) -> float:
        """Return f0 in Hz for one frame of ``frame_length`` samples, or NaN."""
        ...


class NumpyYin:
    def __init__(self, sample_rate: int = 44100, frame_length: int = 2048,
                 fmin: float = 70.0, fmax: float = 1000.0, threshold: float = 0.15,
                 silence_rms: float = 0.005):
        self.sample_rate = int(sample_rate)
        self.frame_length = int(frame_length)
        self.fmin = float(fmin)
        self.fmax = float(fmax)
        self.threshold = float(threshold)
        self.silence_rms = float(silence_rms)
        self.tau_min = max(1, int(np.floor(self.sample_rate / self.fmax)))
        self.tau_max = int(np.ceil(self.sample_rate / self.fmin))
        if self.tau_max >= self.frame_length:
            raise ValueError("frame_length must be larger than sample_rate / fmin")
        # Number of samples compared for each lag. Constant so all lags are comparable.
        self.window = self.frame_length - self.tau_max
        self.nfft = 1 << int(np.ceil(np.log2(self.frame_length + self.window)))

    def difference_function(self, x: np.ndarray) -> np.ndarray:
        """d(tau) = sum_j (x[j] - x[j+tau])^2 for j in [0, window), tau in [0, tau_max]."""
        w = self.window
        xw = x[:w]
        # Cross term via FFT correlation: c(tau) = sum_j x[j] * x[j + tau]
        fx = np.fft.rfft(x, self.nfft)
        fxw = np.fft.rfft(xw, self.nfft)
        corr = np.fft.irfft(fx * np.conj(fxw), self.nfft)[: self.tau_max + 1]
        # Energy terms via cumulative sums
        sq = np.concatenate([[0.0], np.cumsum(x * x)])
        e0 = sq[w]                                       # sum x[0:w]^2
        taus = np.arange(self.tau_max + 1)
        e_tau = sq[taus + w] - sq[taus]                  # sum x[tau:tau+w]^2
        d = e0 + e_tau - 2.0 * corr
        return np.maximum(d, 0.0)

    @staticmethod
    def cumulative_mean_normalized(d: np.ndarray) -> np.ndarray:
        out = np.ones_like(d)
        cumsum = np.cumsum(d[1:])
        taus = np.arange(1, d.size)
        with np.errstate(divide="ignore", invalid="ignore"):
            out[1:] = np.where(cumsum > 0, d[1:] * taus / cumsum, 1.0)
        return out

    def detect(self, frame: np.ndarray) -> float:
        x = np.asarray(frame, dtype=np.float64)
        if x.size != self.frame_length:
            raise ValueError(f"expected {self.frame_length} samples, got {x.size}")
        if np.sqrt(np.mean(x * x)) < self.silence_rms:
            return float("nan")
        d = self.difference_function(x)
        cmnd = self.cumulative_mean_normalized(d)
        lo, hi = self.tau_min, self.tau_max
        # First lag below the threshold, then walk down to the local minimum.
        below = np.nonzero(cmnd[lo:hi] < self.threshold)[0]
        if below.size == 0:
            return float("nan")
        tau = lo + int(below[0])
        while tau + 1 < hi and cmnd[tau + 1] < cmnd[tau]:
            tau += 1
        # Parabolic interpolation around the minimum for sub-sample precision.
        if 0 < tau < cmnd.size - 1:
            a, b, c = cmnd[tau - 1], cmnd[tau], cmnd[tau + 1]
            denom = a - 2 * b + c
            shift = 0.5 * (a - c) / denom if denom != 0 else 0.0
            shift = float(np.clip(shift, -1.0, 1.0))
        else:
            shift = 0.0
        period = tau + shift
        return float(self.sample_rate / period)


class AubioYin:
    def __init__(self, sample_rate: int = 44100, frame_length: int = 2048,
                 fmin: float = 70.0, fmax: float = 1000.0, threshold: float = 0.15,
                 silence_rms: float = 0.005):
        import aubio  # noqa: F401  (raises ImportError if not installed)
        self.sample_rate = int(sample_rate)
        self.frame_length = int(frame_length)
        self._pitch = aubio.pitch("yin", frame_length, frame_length, sample_rate)
        self._pitch.set_unit("Hz")
        self._pitch.set_tolerance(threshold)
        self._pitch.set_silence(20 * np.log10(max(silence_rms, 1e-9)))
        self.fmin = fmin
        self.fmax = fmax

    def detect(self, frame: np.ndarray) -> float:
        x = np.ascontiguousarray(frame, dtype=np.float32)
        f0 = float(self._pitch(x)[0])
        if f0 <= 0 or not (self.fmin <= f0 <= self.fmax):
            return float("nan")
        return f0


def create_detector(backend: str = "auto", **kwargs) -> PitchDetector:
    """Build a pitch detector. ``backend`` is "auto", "numpy" or "aubio"."""
    if backend in ("auto", "aubio"):
        try:
            return AubioYin(**kwargs)
        except ImportError:
            if backend == "aubio":
                raise
    return NumpyYin(**kwargs)


def backend_name(detector: PitchDetector) -> str:
    return type(detector).__name__

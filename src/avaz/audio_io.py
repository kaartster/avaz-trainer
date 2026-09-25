"""Audio file loading and conversion, device listing, WAV writing.

Loading strategy: try ``soundfile`` first (WAV, FLAC, OGG, MP3). If that fails,
decode with ffmpeg (M4A, OPUS, anything else) straight into memory. ffmpeg is
taken from PATH when present, otherwise from the ``imageio-ffmpeg`` package which
ships its own binary, so no system install is required.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf


def find_ffmpeg() -> str | None:
    """Return a path to an ffmpeg executable, or None if none can be found."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _decode_with_ffmpeg(path: Path, sr: int | None) -> tuple[np.ndarray, int]:
    exe = find_ffmpeg()
    if exe is None:
        raise RuntimeError("ffmpeg not found. Install it (winget install Gyan.FFmpeg) or "
                           "pip install imageio-ffmpeg")
    if sr is None:
        sr = probe_sample_rate(path, exe) or 44100
    cmd = [exe, "-v", "error", "-i", str(path), "-f", "f32le", "-acodec", "pcm_f32le",
           "-ac", "1", "-ar", str(sr), "-"]
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed on {path}: {proc.stderr.decode(errors='replace')}")
    y = np.frombuffer(proc.stdout, dtype=np.float32).astype(np.float32)
    return y, sr


def probe_sample_rate(path: Path, exe: str | None = None) -> int | None:
    """Ask ffmpeg for the native sample rate of a file. Returns None on failure."""
    exe = exe or find_ffmpeg()
    if exe is None:
        return None
    ffprobe = str(Path(exe).with_name(Path(exe).name.replace("ffmpeg", "ffprobe")))
    if shutil.which(ffprobe) or Path(ffprobe).exists():
        proc = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a:0",
                               "-show_entries", "stream=sample_rate", "-of", "csv=p=0",
                               str(path)], capture_output=True, check=False)
        try:
            return int(proc.stdout.decode("utf-8", "replace").strip().splitlines()[0])
        except (ValueError, IndexError):
            pass
    # Fallback: parse ffmpeg's stderr banner
    # Decode manually: ffmpeg prints the filename in UTF-8 and Windows consoles
    # default to cp1252, which would crash text mode on Persian names.
    proc = subprocess.run([exe, "-i", str(path)], capture_output=True, check=False)
    for line in proc.stderr.decode("utf-8", "replace").splitlines():
        if "Audio:" in line and "Hz" in line:
            for tok in line.replace(",", " ").split():
                if tok.isdigit() and 8000 <= int(tok) <= 192000:
                    return int(tok)
    return None


def load_audio(path: str | Path, sr: int | None = None) -> tuple[np.ndarray, int]:
    """Load any audio file as mono float32. Returns ``(samples, sample_rate)``.

    If ``sr`` is given the audio is resampled to it, otherwise the file's own rate
    is kept.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    try:
        y, file_sr = sf.read(str(path), dtype="float32", always_2d=True)
        y = y.mean(axis=1)
    except Exception:
        return _decode_with_ffmpeg(path, sr)
    if sr is not None and sr != file_sr:
        import librosa
        y = librosa.resample(y, orig_sr=file_sr, target_sr=sr).astype(np.float32)
        file_sr = sr
    return y.astype(np.float32), int(file_sr)


def save_wav(path: str | Path, y: np.ndarray, sr: int) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.asarray(y, dtype=np.float32), sr, subtype="PCM_16")


def list_devices() -> str:
    """Human readable table of audio devices, as sounddevice prints it."""
    import sounddevice as sd
    lines = [str(sd.query_devices())]
    try:
        default_in, default_out = sd.default.device
        lines.append("")
        lines.append(f"default input:  {default_in}  ({sd.query_devices(default_in)['name']})")
        lines.append(f"default output: {default_out}  ({sd.query_devices(default_out)['name']})")
    except Exception as exc:
        lines.append(f"(could not read default devices: {exc})")
    return "\n".join(lines)

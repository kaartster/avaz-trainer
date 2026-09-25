"""Vocal separation with Demucs, so the slicer and histogram see only the voice.

Demucs is a neural network that splits a mix into stems (vocals, drums, bass,
other). Only the vocals stem is kept as ``<name>.vocals.wav``; the rest is summed
into ``<name>.accompaniment.wav`` in case it is useful later. It runs on the CPU
in a few minutes per recording, so it is an offline preprocessing step.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def vocals_path_for(audio_path: str | Path) -> Path:
    p = Path(audio_path)
    return p.with_name(p.stem + ".vocals.wav")


def accompaniment_path_for(audio_path: str | Path) -> Path:
    p = Path(audio_path)
    return p.with_name(p.stem + ".accompaniment.wav")


def separate_file(path: str | Path, model_name: str = "htdemucs", device: str | None = None,
                  progress: bool = True) -> tuple[Path, Path]:
    """Split ``path`` into vocals and accompaniment WAVs next to it. Returns both paths."""
    try:
        import torch
        from demucs.apply import apply_model
        from demucs.pretrained import get_model
    except ImportError as exc:
        raise RuntimeError("Demucs is not installed. Run: pip install demucs") from exc

    from .audio_io import load_audio, save_wav

    path = Path(path)
    model = get_model(model_name)
    model.eval()
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    y, sr = load_audio(path, sr=model.samplerate)
    # Demucs expects (batch, channels, samples) with the model's channel count (2).
    mix = torch.from_numpy(np.stack([y] * model.audio_channels)).float()[None]
    ref = mix.mean(0)
    mix = (mix - ref.mean()) / (ref.std() + 1e-8)
    with torch.no_grad():
        stems = apply_model(model, mix, device=device, progress=progress, split=True,
                            overlap=0.25)[0]
    stems = stems * (ref.std() + 1e-8) + ref.mean()
    sources = list(model.sources)
    vocals = stems[sources.index("vocals")].mean(0).cpu().numpy()
    others = [stems[i].mean(0).cpu().numpy() for i, s in enumerate(sources) if s != "vocals"]
    accompaniment = np.sum(others, axis=0) if others else np.zeros_like(vocals)

    vocals_path = vocals_path_for(path)
    acc_path = accompaniment_path_for(path)
    save_wav(vocals_path, vocals, sr)
    save_wav(acc_path, accompaniment, sr)
    return vocals_path, acc_path

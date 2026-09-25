"""Command line entry points: ``avaz <command> ...``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import load_settings


def _parse_tonic(value: str | None, settings: dict | None = None):
    """--tonic value -> float, "auto" or "final". None falls back to settings, then auto."""
    if value is None:
        configured = (settings or {}).get("tonic", {}).get("teacher_hz")
        return float(configured) if configured else "auto"
    if value.lower() in ("auto", "histogram"):
        return "auto"
    if value.lower() == "final":
        return "final"
    return float(value)


def cmd_devices(args) -> int:
    from .audio_io import list_devices
    print(list_devices())
    return 0


def cmd_check(args) -> int:
    """Verify ffmpeg, sounddevice and the YIN backend."""
    import numpy as np
    from .audio_io import find_ffmpeg
    from .pitch_live import create_detector, backend_name

    ok = True
    exe = find_ffmpeg()
    print(f"ffmpeg:      {exe or 'NOT FOUND'}")
    ok &= exe is not None

    try:
        import sounddevice as sd
        n = len(sd.query_devices())
        din, dout = sd.default.device
        print(f"sounddevice: {n} devices, default input {din}, default output {dout}")
    except Exception as exc:
        print(f"sounddevice: FAILED ({exc})")
        ok = False

    try:
        det = create_detector(args.backend, sample_rate=44100, frame_length=2048)
        t = np.arange(2048) / 44100
        f0 = det.detect(0.3 * np.sin(2 * np.pi * 220.0 * t))
        err = 1200 * np.log2(f0 / 220.0)
        print(f"yin backend: {backend_name(det)}, 220 Hz test tone -> {f0:.2f} Hz "
              f"({err:+.1f} cents)")
        ok &= abs(err) < 5
    except Exception as exc:
        print(f"yin backend: FAILED ({exc})")
        ok = False

    print("all good" if ok else "some checks failed")
    return 0 if ok else 1


def cmd_analyze(args) -> int:
    from .pitch_offline import analyze_file, save_curve, curve_path_for
    from .scales import load_scales
    from .plots import plot_curve
    import numpy as np

    settings = load_settings()
    src = Path(args.file)
    print(f"analyzing {src.name} ...")
    curve = analyze_file(src, tonic_hz=_parse_tonic(args.tonic, settings), settings=settings)
    out = Path(args.output) if args.output else curve_path_for(src)
    save_curve(curve, out)
    voiced_pct = 100 * curve.voiced.mean() if curve.voiced.size else 0
    print(f"duration {curve.duration:.1f} s, {curve.times.size} frames, "
          f"{voiced_pct:.0f}% voiced, hop {curve.hop_seconds * 1000:.1f} ms")
    print(f"tonic: {curve.tonic_hz:.2f} Hz")
    finite = curve.cents[np.isfinite(curve.cents)]
    if finite.size:
        print(f"range: {finite.min():.0f} to {finite.max():.0f} cents relative to tonic")
    print(f"saved {out}")
    scale = None
    if args.scale:
        scale = load_scales()[args.scale]
    if not args.no_plot or args.save_plot:
        plot_curve(curve, scale=scale, colors=settings.get("colors", {}),
                   save_path=args.save_plot, show=not args.no_plot)
    return 0


def cmd_histogram(args) -> int:
    from .pitch_offline import analyze_file, load_curve, curve_path_for
    from .cents import pitch_histogram
    from .scales import load_scales, suggest_scale_positions, find_histogram_peaks
    from .plots import plot_histogram

    settings = load_settings()
    src = Path(args.file)
    if src.suffix == ".json":
        curve = load_curve(src)
    else:
        cached = curve_path_for(src)
        if cached.exists() and not args.reanalyze:
            print(f"using cached curve {cached.name} (pass --reanalyze to redo)")
            curve = load_curve(cached)
        else:
            print(f"analyzing {src.name} ...")
            curve = analyze_file(src, tonic_hz=_parse_tonic(args.tonic, settings), settings=settings)
    tonic = _parse_tonic(args.tonic, settings)
    if tonic not in ("auto", "final") and abs(tonic - curve.tonic_hz) > 1e-6:
        curve = curve.with_tonic(tonic)
    print(f"tonic: {curve.tonic_hz:.2f} Hz")

    centers, counts = pitch_histogram(curve.cents, bin_cents=args.bin, fold=True,
                                      smooth_bins=args.smooth)
    peaks = find_histogram_peaks(centers, counts, min_separation_cents=args.min_separation,
                                 min_height_fraction=args.min_height)
    suggested = suggest_scale_positions(centers, counts, min_separation_cents=args.min_separation,
                                        min_height_fraction=args.min_height)
    total = counts.sum() or 1.0
    print("\npeaks (cents above tonic, folded into one octave):")
    for c, h in peaks:
        print(f"  {c:7.1f}  {100 * h / total:5.1f}%  {'#' * int(40 * h / counts.max())}")
    print("\nsuggested scale positions (paste into config/scales.yaml):")
    print("  positions: [" + ", ".join(f"{p:.0f}" for p in suggested) + "]")

    scale = load_scales()[args.scale] if args.scale else None
    if not args.no_plot or args.save_plot:
        plot_histogram(centers, counts, suggested=suggested, scale=scale,
                       title=f"{curve.source}  tonic {curve.tonic_hz:.1f} Hz",
                       colors=settings.get("colors", {}), save_path=args.save_plot,
                       show=not args.no_plot)
    return 0


def _load_or_analyze(src: Path, settings: dict, tonic, reanalyze: bool = False):
    """Return the pitch curve of an audio file, analyzing it if no cached curve exists."""
    from .pitch_offline import analyze_file, load_curve, save_curve, curve_path_for
    cached = curve_path_for(src)
    if cached.exists() and not reanalyze:
        print(f"using cached curve {cached.name}")
        curve = load_curve(cached)
        if tonic not in ("auto", "final") and abs(tonic - curve.tonic_hz) > 1e-6:
            curve = curve.with_tonic(tonic)
        return curve
    print(f"analyzing {src.name} (this takes a while) ...")
    curve = analyze_file(src, tonic_hz=tonic, settings=settings)
    save_curve(curve, cached)
    return curve


def cmd_separate(args) -> int:
    from .separate import separate_file, vocals_path_for
    src = Path(args.file)
    if vocals_path_for(src).exists() and not args.force:
        print(f"{vocals_path_for(src).name} already exists (use --force to redo)")
        return 0
    print(f"separating {src.name} with {args.model} ...")
    vocals, acc = separate_file(src, model_name=args.model)
    print(f"saved {vocals}")
    print(f"saved {acc}")
    return 0


def _phrase_out_dir(src: Path, out_dir: str | None) -> Path:
    from .config import data_dir
    if out_dir:
        return Path(out_dir)
    stem = src.name
    for suffix in (".vocals.wav", ".wav", ".m4a", ".mp3", ".opus", ".flac", ".ogg"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return data_dir() / "phrases" / stem


def _slicer_params(args, settings: dict) -> dict:
    sl = settings.get("slicer", {})
    def pick(arg_value, key, default):
        return arg_value if arg_value is not None else sl.get(key, default)
    return dict(
        silence_db=pick(getattr(args, "silence_db", None), "silence_db", -40),
        min_pause_seconds=pick(getattr(args, "min_pause", None), "min_pause_seconds", 0.6),
        min_phrase_seconds=pick(getattr(args, "min_phrase", None), "min_phrase_seconds", 0.8),
        pad_seconds=pick(getattr(args, "pad", None), "pad_seconds", 0.1))


def cmd_slice(args) -> int:
    from .audio_io import load_audio
    from .slicer import detect_phrases, read_labels, write_labels, export_phrases

    settings = load_settings()
    src = Path(args.file)
    out_dir = _phrase_out_dir(src, args.out_dir)
    y, sr = load_audio(src)

    if args.labels:
        phrases = read_labels(args.labels)
        print(f"using {len(phrases)} phrases from {args.labels}")
    else:
        phrases = detect_phrases(y, sr, **_slicer_params(args, settings))
        print(f"detected {len(phrases)} phrases")

    labels_path = out_dir / "labels.txt"
    write_labels(phrases, labels_path)
    for ph in phrases:
        print(f"  {ph.label}  {ph.start:7.2f} - {ph.end:7.2f}  ({ph.duration:5.2f} s)")
    print(f"labels: {labels_path}")
    print("  to fix cuts by hand: open the audio in Audacity, File > Import > Labels, edit, "
          "File > Export > Labels, then rerun with --labels <file>")

    if args.clean and out_dir.exists():
        removed = 0
        for old_file in list(out_dir.glob("*.wav")) + list(out_dir.glob("*.pitch.json")):
            if old_file.name.startswith("call_response"):
                continue
            old_file.unlink()
            removed += 1
        print(f"removed {removed} old phrase files from {out_dir}")

    curve = None
    if not args.no_curves:
        curve = _load_or_analyze(src, settings, _parse_tonic(args.tonic, settings))
    written = export_phrases(y, sr, phrases, out_dir, curve=curve)
    print(f"wrote {len(written)} phrase files to {out_dir}")

    if args.plot or args.save_plot:
        from .plots import plot_segmentation
        plot_segmentation(y, sr, phrases, curve=curve, title=src.name,
                          colors=settings.get("colors", {}), show=args.plot,
                          save_path=args.save_plot)
    return 0


def cmd_callresponse(args) -> int:
    from .audio_io import load_audio, save_wav
    from .slicer import detect_phrases, read_labels, write_labels, build_call_response

    settings = load_settings()
    src = Path(args.file)
    y, sr = load_audio(src)
    out_dir = _phrase_out_dir(src, args.out_dir)
    labels = args.labels
    if labels is None and (out_dir / "labels.txt").exists():
        labels = out_dir / "labels.txt"
    if labels:
        phrases = read_labels(labels)
        print(f"using {len(phrases)} phrases from {labels}")
    else:
        phrases = detect_phrases(y, sr, **_slicer_params(args, settings))
        print(f"detected {len(phrases)} phrases (run avaz slice first to check them)")
    margin = args.margin
    if margin is None:
        margin = settings.get("slicer", {}).get("response_margin_seconds", 0.5)
    track, track_labels = build_call_response(y, sr, phrases, margin_seconds=margin,
                                              lead_in_seconds=args.lead_in)
    out = Path(args.output) if args.output else out_dir / "call_response.wav"
    save_wav(out, track, sr)
    write_labels(track_labels, out.with_suffix(".labels.txt"))
    print(f"saved {out}  ({track.size / sr:.1f} s, {len(phrases)} phrases, "
          f"margin {margin:.2f} s)")
    return 0


def _resolve_device(spec, kind: str):
    """Device index, or a case-insensitive substring of the device name, or None."""
    if spec is None or spec == "":
        return None
    try:
        return int(spec)
    except ValueError:
        pass
    import sounddevice as sd
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    for i, d in enumerate(sd.query_devices()):
        if d[key] > 0 and spec.lower() in d["name"].lower():
            return i
    raise SystemExit(f"no {kind} device matching '{spec}' (see avaz devices)")


def cmd_live(args) -> int:
    from .live import build_pitch_stream, MicSource, FileSource
    from .scales import load_scales
    from .ui.live_view import run_live_view

    settings = load_settings()
    tonic_cfg = settings.get("tonic", {})
    if args.tonic is not None:
        tonic = float(args.tonic)
    else:
        tonic = tonic_cfg.get("mine_hz") or tonic_cfg.get("teacher_hz")
        if not tonic:
            raise SystemExit("no tonic: pass --tonic <hz> or set tonic.teacher_hz in settings.yaml")
        tonic = float(tonic)
    scale = load_scales()[args.scale] if args.scale else None
    stream = build_pitch_stream(settings, tonic, backend=args.backend,
                                sample_rate=args.sample_rate, hop_length=args.hop,
                                smoothing_frames=args.smooth)
    block = args.block or stream.hop_length
    if args.input_file:
        source = FileSource(args.input_file, stream.sample_rate, block,
                            device=_resolve_device(args.device, "output"), loop=not args.once)
    else:
        source = MicSource(stream.sample_rate, block,
                           device=_resolve_device(args.device, "input"))
    print(f"input: {source.name}")
    print(f"tonic {tonic:.1f} Hz, hop {stream.hop_length} samples "
          f"({1000 * stream.hop_length / stream.sample_rate:.1f} ms), "
          f"smoothing {stream.smoothing_frames} frames, backend {type(stream.detector).__name__}")
    return run_live_view(source, stream, scale, settings, screenshot=args.screenshot,
                         quit_after=args.quit_after)


def cmd_practice(args) -> int:
    from .practice import PracticeEngine
    from .scales import load_scales
    from .ui.practice_view import run_practice_view

    settings = load_settings()
    audio = settings.get("audio", {})
    sr = int(args.sample_rate or audio.get("sample_rate", 44100))
    block = int(args.block or audio.get("hop_length", 256))
    scale = load_scales()[args.scale] if args.scale else None
    engine = PracticeEngine(sr, block,
                            input_device=_resolve_device(args.device, "input"),
                            output_device=_resolve_device(args.output, "output"),
                            monitor_gain=args.gain)
    print(f"input: {engine.input_name}")
    print(f"output: {engine.output_name}")
    print(f"stream latency in/out: {1000 * engine.latency[0]:.0f} / {1000 * engine.latency[1]:.0f} ms")
    return run_practice_view(engine, Path(args.phrase), settings, scale,
                             float(args.tonic) if args.tonic else None, args.mode, args.speed,
                             args.loop, screenshot=args.screenshot, quit_after=args.quit_after,
                             autostart=args.autostart, same_key=args.same_key)


def cmd_song(args) -> int:
    from .audio_io import load_audio
    from .config import load_song_config, save_song_config, resolve_tonics
    from .practice import PracticeEngine
    from .scales import load_scales
    from .ui.song_view import run_song_view

    settings = load_settings()
    audio = settings.get("audio", {})
    sr = int(args.sample_rate or audio.get("sample_rate", 44100))
    block = int(args.block or audio.get("hop_length", 256))
    scale = load_scales()[args.scale] if args.scale else None

    src = Path(args.file)
    out_dir = _phrase_out_dir(src, args.out_dir)

    # Choices given on the command line are remembered for this song.
    teacher_arg = _parse_tonic(args.teacher_tonic, {}) if args.teacher_tonic else None
    if args.same_key is not None or isinstance(teacher_arg, float):
        path = save_song_config(out_dir, same_key=args.same_key,
                                teacher_tonic_hz=teacher_arg if isinstance(teacher_arg, float) else None)
        print(f"remembered in {path}")
    song_cfg = load_song_config(out_dir)
    teacher, mine, same_key = resolve_tonics(
        song_cfg, settings, my_tonic=float(args.my_tonic) if args.my_tonic else None)
    if teacher_arg in ("auto", "final"):
        teacher = teacher_arg

    curve = _load_or_analyze(src, settings, teacher if teacher else "auto")
    if same_key:
        mine = curve.tonic_hz
    if not mine:
        raise SystemExit("no tonic: pass --my-tonic <hz> or set tonic.mine_hz in settings.yaml")
    y, _ = load_audio(src, sr=sr)

    engine = PracticeEngine(sr, block,
                            input_device=_resolve_device(args.device, "input"),
                            output_device=_resolve_device(args.output, "output"),
                            monitor_gain=args.gain)
    print(f"input: {engine.input_name}")
    print(f"output: {engine.output_name}")
    print(f"stream latency in/out: {1000 * engine.latency[0]:.0f} / {1000 * engine.latency[1]:.0f} ms")
    if same_key:
        print(f"tonic {curve.tonic_hz:.1f} Hz, same key as the teacher (my pitch is not transposed)")
    else:
        print(f"tonic: teacher {curve.tonic_hz:.1f} Hz, mine {mine:.1f} Hz (my curve is transposed)")
    print(f"saving stretches I pause on to {out_dir}")
    return run_song_view(engine, src, y, curve, out_dir, settings, scale, float(mine),
                         same_key=same_key,
                         script=args.script.split(",") if args.script else None,
                         screenshot=args.screenshot, quit_after=args.quit_after)


def _attempt_wavs(target: Path) -> list[Path]:
    """Attempt WAVs: one file, one phrase folder, or every phrase folder of a song."""
    if target.is_dir():
        direct = sorted(p for p in target.glob("*.wav"))
        return direct or sorted(target.rglob("*.wav"))
    if target.suffix == ".json":
        stem = target.name.split(".")[0]
        return [target.with_name(stem + ".wav")]
    return [target]


def cmd_score(args) -> int:
    from .compare import (score_attempt, attempt_curve, reference_for, record_score,
                          load_history, history_path, read_meta)
    from .config import load_song_config
    from .pitch_offline import load_curve
    from .scales import load_scales
    from .plots import plot_score

    settings = load_settings()
    tol = args.tolerance if args.tolerance is not None else \
        float(settings.get("scoring", {}).get("tolerance_cents", 25))
    scale = load_scales()[args.scale] if args.scale else None
    wavs = _attempt_wavs(Path(args.attempt))
    if not wavs:
        raise SystemExit(f"no attempts found in {args.attempt}")
    if args.new:
        def scored_offline(w):
            entry = load_history(history_path(w)).get(w.stem, {})
            return entry.get("method") == "offline"
        wavs = [w for w in wavs if not scored_offline(w)]
        if not wavs:
            print("nothing new to score")
            return 0
    for wav in wavs:
        ref_path = Path(args.reference) if args.reference else reference_for(wav)
        if ref_path is None:
            print(f"{wav.name}: no reference curve known, pass --reference <phrase.pitch.json>")
            continue
        reference = load_curve(ref_path)
        method = "live" if args.live else "offline"
        if method == "offline":
            print(f"{wav.name}: analyzing with pyin ...")
        attempt = attempt_curve(wav, method=method, settings=settings,
                                tonic_hz=float(args.my_tonic) if args.my_tonic else None)
        # Same key: explicit flag, else what the session recorded, else the song's song.yaml.
        same_key = args.same_key
        if same_key is None:
            same_key = read_meta(wav).get("same_key")
        if same_key is None:
            same_key = bool(load_song_config(ref_path.parent).get("same_key", False))
        result = score_attempt(reference, attempt, tolerance=tol, same_key=same_key, band=args.band)
        record_score(wav, result, method)
        print(f"{wav.parent.name}/{wav.name}  vs  {ref_path.name}"
              + ("   (same key)" if same_key else ""))
        print(result.summary())
        print()
        if (args.plot or args.save_plot) and len(wavs) == 1:
            plot_score(result, title=f"{wav.parent.name} / {wav.stem}   within {tol:.0f}c: "
                                     f"{result.pct_within:.0f}%   mean {result.mad:.0f}c",
                       scale=scale, colors=settings.get("colors", {}), show=args.plot,
                       save_path=args.save_plot)
    return 0


def cmd_history(args) -> int:
    from .compare import load_history, history_rows
    from .plots import plot_history

    target = Path(args.phrase)
    if target.is_file():
        target = target.parent
    hist_file = target / "history.json"
    rows = history_rows(load_history(hist_file))
    if not rows:
        print(f"no scores yet in {hist_file}")
        return 0
    print(f"{target.parent.name} / {target.name}")
    print(f"{'attempt':<16} {'mode':<6} {'speed':>5} {'within':>7} {'mean':>6} {'median':>7} {'timing':>7} {'method'}")
    for r in rows:
        print(f"{r['name']:<16} {str(r.get('mode')):<6} {r.get('speed') or 1:>5.1f} "
              f"{r['pct_within']:>6.0f}% {r['mad']:>5.0f}c {r['median_abs']:>6.0f}c "
              f"{100 * r['timing_ratio']:>6.0f}% {r.get('method', '')}")
    if args.plot or args.save_plot:
        plot_history(rows, title=f"{target.parent.name} / {target.name}", show=args.plot,
                     save_path=args.save_plot)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="avaz", description="Persian classical singing trainer")
    p.add_argument("--version", action="version", version=f"avaz {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("devices", help="list audio input and output devices")
    s.set_defaults(func=cmd_devices)

    s = sub.add_parser("check", help="verify ffmpeg, sounddevice and the YIN backend")
    s.add_argument("--backend", default="auto", choices=["auto", "numpy", "aubio"])
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("analyze", help="extract a pitch curve from a recording")
    s.add_argument("file")
    s.add_argument("--tonic", default=None,
                   help="tonic in Hz, 'auto' (histogram peak) or 'final' (last note). "
                        "Default: tonic.teacher_hz from settings.yaml, else auto")
    s.add_argument("--scale", default=None, help="scale name from scales.yaml for guide lines")
    s.add_argument("--output", "-o", default=None, help="curve JSON path (default: next to file)")
    s.add_argument("--no-plot", action="store_true")
    s.add_argument("--save-plot", default=None, help="also save the plot as PNG")
    s.set_defaults(func=cmd_analyze)

    s = sub.add_parser("histogram", help="folded pitch histogram and suggested scale positions")
    s.add_argument("file", help="audio file or .pitch.json curve")
    s.add_argument("--tonic", default=None, help="tonic in Hz, 'auto' or 'final'")
    s.add_argument("--scale", default=None, help="scale to draw for comparison")
    s.add_argument("--bin", type=float, default=10.0, help="bin width in cents")
    s.add_argument("--smooth", type=int, default=3, help="smoothing width in bins")
    s.add_argument("--min-separation", type=float, default=60.0,
                   help="minimum distance between peaks in cents")
    s.add_argument("--min-height", type=float, default=0.08,
                   help="minimum peak height as a fraction of the tallest peak")
    s.add_argument("--reanalyze", action="store_true", help="ignore the cached curve")
    s.add_argument("--no-plot", action="store_true")
    s.add_argument("--save-plot", default=None)
    s.set_defaults(func=cmd_histogram)

    s = sub.add_parser("separate", help="split a recording into vocals and accompaniment (Demucs)")
    s.add_argument("file")
    s.add_argument("--model", default="htdemucs")
    s.add_argument("--force", action="store_true", help="redo even if the vocals file exists")
    s.set_defaults(func=cmd_separate)

    s = sub.add_parser("slice", help="cut a recording into phrases at pauses")
    s.add_argument("file", help="audio file (use the .vocals.wav from avaz separate if "
                                "the recording has accompaniment)")
    s.add_argument("--labels", default=None, help="use this Audacity label file instead of detecting")
    s.add_argument("--silence-db", type=float, default=None, help="silence threshold in dBFS")
    s.add_argument("--min-pause", type=float, default=None, help="minimum pause length in seconds")
    s.add_argument("--min-phrase", type=float, default=None, help="drop phrases shorter than this")
    s.add_argument("--pad", type=float, default=None, help="padding before and after each phrase")
    s.add_argument("--tonic", default=None, help="tonic for the phrase pitch curves")
    s.add_argument("--out-dir", default=None, help="default: data/phrases/<recording name>/")
    s.add_argument("--no-curves", action="store_true", help="skip pitch curves, only audio")
    s.add_argument("--clean", action="store_true",
                   help="delete phrase files already in the output folder first")
    s.add_argument("--plot", action="store_true", help="show the segmentation")
    s.add_argument("--save-plot", default=None)
    s.set_defaults(func=cmd_slice)

    s = sub.add_parser("callresponse", help="build a track with silence after every phrase")
    s.add_argument("file")
    s.add_argument("--labels", default=None, help="label file (default: labels.txt from avaz slice)")
    s.add_argument("--margin", type=float, default=None, help="extra seconds after each response gap")
    s.add_argument("--lead-in", type=float, default=1.0, help="seconds of silence before the first phrase")
    s.add_argument("--out-dir", default=None)
    s.add_argument("--output", "-o", default=None, help="output WAV (default: <out-dir>/call_response.wav)")
    s.set_defaults(func=cmd_callresponse)

    s = sub.add_parser("live", help="scrolling live pitch view from the microphone")
    s.add_argument("--scale", default=None, help="scale name from scales.yaml for guide lines")
    s.add_argument("--tonic", default=None, help="my tonic in Hz (default: tonic.mine_hz, "
                                                 "then tonic.teacher_hz from settings)")
    s.add_argument("--device", default=None, help="input device index or name substring")
    s.add_argument("--input-file", default=None,
                   help="play this file instead of using the mic (for testing the display)")
    s.add_argument("--once", action="store_true", help="with --input-file: do not loop")
    s.add_argument("--sample-rate", type=int, default=None)
    s.add_argument("--hop", type=int, default=None, help="samples between pitch estimates")
    s.add_argument("--block", type=int, default=None, help="sound card block size (default: hop)")
    s.add_argument("--smooth", type=int, default=None, help="median smoothing frames (1 = off)")
    s.add_argument("--backend", default="auto", choices=["auto", "numpy", "aubio"])
    s.add_argument("--screenshot", default=None, help=argparse.SUPPRESS)
    s.add_argument("--quit-after", type=float, default=None, help=argparse.SUPPRESS)
    s.set_defaults(func=cmd_live)

    s = sub.add_parser("practice", help="play a teacher phrase, record and draw my attempt")
    s.add_argument("phrase", help="phrase WAV (or .pitch.json) from data/phrases/...")
    s.add_argument("--scale", default=None, help="scale name from scales.yaml for guide lines")
    s.add_argument("--tonic", default=None, help="MY tonic in Hz (default: tonic.mine_hz, "
                                                 "then the phrase's teacher tonic)")
    s.add_argument("--mode", default="after", choices=["after", "along"],
                   help="after: listen then sing; along: sing with the teacher")
    s.add_argument("--same-key", action=argparse.BooleanOptionalAction, default=None,
                   help="compare my pitch as it is (the teacher sang in my range). "
                        "Default: same_key in the phrase folder's song.yaml")
    s.add_argument("--speed", type=float, default=1.0, help="playback speed 0.5 to 1.0")
    s.add_argument("--loop", action="store_true", help="repeat automatically")
    s.add_argument("--device", default=None, help="input device index or name substring")
    s.add_argument("--output", default=None, help="output device index or name substring")
    s.add_argument("--gain", type=float, default=1.0, help="teacher playback gain")
    s.add_argument("--sample-rate", type=int, default=None)
    s.add_argument("--block", type=int, default=None)
    s.add_argument("--autostart", action="store_true", help=argparse.SUPPRESS)
    s.add_argument("--screenshot", default=None, help=argparse.SUPPRESS)
    s.add_argument("--quit-after", type=float, default=None, help=argparse.SUPPRESS)
    s.set_defaults(func=cmd_practice)

    s = sub.add_parser("song", help="play a whole recording, pause anywhere to sing, "
                                    "no pre-cut phrases needed")
    s.add_argument("file", help="the recording to practice with (use the .vocals.wav if it "
                                "has accompaniment)")
    s.add_argument("--scale", default=None, help="scale name from scales.yaml for guide lines")
    s.add_argument("--my-tonic", default=None,
                   help="my tonic in Hz (default: tonic.mine_hz, then tonic.teacher_hz)")
    s.add_argument("--teacher-tonic", default=None,
                   help="the recording's tonic in Hz, 'auto' or 'final'. A number is remembered "
                        "for this song (default: song.yaml, then tonic.teacher_hz)")
    s.add_argument("--same-key", action=argparse.BooleanOptionalAction, default=None,
                   help="the teacher sang this in my range: compare my pitch as it is, no "
                        "transposing or octave folding. Remembered for this song")
    s.add_argument("--out-dir", default=None,
                   help="where stretches I pause on are saved as phrases (default: "
                        "data/phrases/<recording name>/)")
    s.add_argument("--device", default=None, help="input device index or name substring")
    s.add_argument("--output", default=None, help="output device index or name substring")
    s.add_argument("--gain", type=float, default=1.0, help="teacher playback gain")
    s.add_argument("--sample-rate", type=int, default=None)
    s.add_argument("--block", type=int, default=None)
    s.add_argument("--script", default=None, help=argparse.SUPPRESS)
    s.add_argument("--screenshot", default=None, help=argparse.SUPPRESS)
    s.add_argument("--quit-after", type=float, default=None, help=argparse.SUPPRESS)
    s.set_defaults(func=cmd_song)

    s = sub.add_parser("score", help="score an attempt against its teacher phrase")
    s.add_argument("attempt", help="attempt WAV, or an attempt folder to score every WAV in it")
    s.add_argument("--reference", default=None, help="phrase .pitch.json (default: from the meta file)")
    s.add_argument("--live", action="store_true", help="use the live curve instead of re-analyzing")
    s.add_argument("--my-tonic", default=None,
                   help="my tonic in Hz for the attempt (default: the one stored with the attempt)")
    s.add_argument("--new", action="store_true", help="folder mode: only attempts not scored offline yet")
    s.add_argument("--same-key", action=argparse.BooleanOptionalAction, default=None,
                   help="compare my pitch as it is, no transposing or octave folding "
                        "(default: what the attempt recorded, then the song's song.yaml)")
    s.add_argument("--tolerance", type=float, default=None, help="cents counted as in tune")
    s.add_argument("--band", type=float, default=0.2, help="DTW band as a fraction of the length")
    s.add_argument("--scale", default=None, help="draw guide lines of this scale")
    s.add_argument("--plot", action="store_true")
    s.add_argument("--save-plot", default=None)
    s.set_defaults(func=cmd_score)

    s = sub.add_parser("history", help="show scores of all attempts of a phrase")
    s.add_argument("phrase", help="attempt folder (data/attempts/<song>/<phrase>) or a file in it")
    s.add_argument("--plot", action="store_true")
    s.add_argument("--save-plot", default=None)
    s.set_defaults(func=cmd_history)

    return p


def _force_utf8_console() -> None:
    """Windows consoles often default to cp1252, which cannot print Persian filenames."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv=None) -> int:
    _force_utf8_console()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

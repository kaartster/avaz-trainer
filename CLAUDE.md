# Avaz Trainer

A personal practice tool for Persian classical singing (avaz). It listens to my voice, shows my pitch live in cents relative to my tonic, and compares it with pitch curves extracted from my teacher's training recordings. It started as a laptop app in Python. Because I usually practice on my Android phone, the practice side now also gets a phone version: a web app (PWA) in `web/` that runs in Chrome on the phone, while the laptop keeps doing the heavy offline analysis. A small open hardware device (Raspberry Pi) is still a possible later step.

## About me and how to work with me

- I'm Amir, a geodata engineer with a civil engineering and GIS background. I'm comfortable with Python, C#, and data pipelines, but I'm new to audio and DSP.
- I take online Persian classical singing classes. My teacher sends recordings of phrases and exercises for practice.
- Explain audio concepts briefly when you first use them (sample rate, frames, hop size, YIN, cents, DTW). Keep it short and practical.
- Work in small steps. At the end of each milestone, show me how to run it and what I should see or hear.
- Write tests for the pure logic (cents conversion, scales, slicing, scoring). Audio I/O and UI can be tested by hand.
- Don't use em dashes in any text, docs, or comments you write for this project.

## Goals

1. **Analyze** a teacher recording offline and extract a clean pitch curve.
2. **Slice** long recordings into phrases, and build call-and-response practice tracks where each phrase is followed by silence of exactly the same length.
3. **Show my pitch live** from the microphone as a scrolling curve in cents relative to my tonic, with guide lines for the notes of the current dastgah, including koron and sori positions.
4. **Practice mode**: play a teacher phrase, draw the teacher's curve and my live curve on the same chart, and record my attempt.
5. **Score** my attempt against the reference, tolerant of small timing differences.
6. **Later**: run the same code on a Raspberry Pi with a mic, a small screen, and headphones.

## Non-goals (for now)

- Automatic dastgah or gusheh recognition.
- Western note names as the main display. Western names may appear as a secondary label only.
- Native mobile apps (Kotlin, Flutter, app stores). The phone version is a web app.
- Offline analysis on the phone (pyin, Demucs, slicing). That stays on the laptop.

## Domain notes (important)

- **Cents**: `cents = 1200 * log2(f0 / tonic_hz)`. 100 cents is one semitone. All display and comparison happens in cents, never in note names.
- **Persian intervals are not equal tempered.** Koron and sori are not exactly 50 cents. Scale positions must be configurable in a YAML file, and the defaults below are only approximate starting points.
- **Calibration from the teacher**: build a pitch histogram of a teacher recording (cents relative to tonic, folded into one octave). The peaks show where the teacher actually places each note. Provide a tool that suggests scale positions from these peaks so the guide lines match my teacher's intonation, not a textbook.
- **Tonic**: the teacher's tonic (shahed or finalis) can be any frequency. Allow setting it manually in Hz, or estimate it from the recording (for example, the strongest histogram peak, or the final sustained note).
- **Different voices**: the teacher and I may sing in different keys or octaves. Compare relative to each singer's own tonic, and fold octave differences (plus or minus 1200 cents) before scoring.
- **Ornaments (tahrir)** are fast pitch oscillations. Offline analysis should preserve them. Live display may smooth lightly, but keep smoothing configurable.

### Default scale positions (approximate, cents above tonic)

```yaml
shur:   [0, 150, 300, 500, 700, 800, 1000, 1200]
mahur:  [0, 200, 400, 500, 700, 900, 1100, 1200]
```

These are placeholders to replace after calibration against my teacher's recordings.

## Tech stack

- Python 3.11+
- `numpy`, `scipy`
- `librosa` for offline analysis (`librosa.pyin` for pitch, onset and silence helpers)
- `soundfile` for WAV/FLAC; `ffmpeg` installed on the system so teacher files in MP3, M4A, or OPUS (WhatsApp) can be converted
- `sounddevice` for live microphone input and playback
- Live pitch detection: a YIN implementation behind a small interface. Try `aubio` first; if it doesn't install cleanly on my OS, write a numpy YIN. The rest of the code must not depend on which one is used.
- UI: `PySide6` + `pyqtgraph` (fast enough for real-time plotting, and it runs on a Raspberry Pi)
- `PyYAML` for config
- `pytest` for tests
- Use a virtual environment and `pyproject.toml`. The code must run on Windows and Linux.

### Phone web app (`web/`)

- Plain HTML, CSS and JavaScript ES modules. No build step and no npm, so it can be served as static files (locally with `avaz web`, or from GitHub Pages).
- A Progressive Web App: installable from Chrome ("Add to Home screen"), works offline through a service worker, keeps the screen awake while listening.
- Microphone through `getUserMedia` with echo cancellation, noise suppression and auto gain turned off (they distort pitch), and an `AudioWorklet` that hands audio blocks to the main thread.
- Live pitch: a JavaScript port of the numpy YIN in `pitch_live.py`, same parameters.
- Pure logic lives in modules without DOM or audio access (`cents.js`, `yin.js`, `scales.js`, `notes.js`, `stream.js`, `feedback.js`) and is tested in `web/tests.html`, which runs in any browser. Keep their behavior identical to the Python modules of the same name.
- Scale positions come from `config/scales.yaml`, exported to `web/scales.json` by `avaz web`. A pytest checks the two stay in sync.
- Per-user choices (key, dastgah, feedback level) are stored in the browser (`localStorage`), so each classmate keeps their own.

### Phone UI/UX principles

The phone is not a small laptop screen. Design for one hand, portrait first, and a singer who is not looking closely:

- One big answer at a time: the note I'm on (solfege name, with koron and sori) and plain words ("in tune", "a bit low, go up"). Cents only in the detailed level.
- Calm screen: note lanes by default, the detailed curve as an option. The view follows my voice vertically, so no zooming or scrolling by hand.
- Big touch targets (at least 48 px), the main button at the bottom within thumb reach, settings in a bottom sheet.
- Dark theme by default (practice often happens in the evening), readable from arm's length.
- Works in landscape too (phone on a stand): readout on the left, chart on the right.

## Audio parameters (starting values, keep in config)

- Sample rate: 44100 Hz (or 48000 if that's the device default)
- Frame length: 2048 samples; hop: 256 to 512 samples
- Voice range: fmin 70 Hz, fmax 1000 Hz
- Target live latency: under 100 ms from voice to screen
- Unvoiced frames (breath, silence) are stored as NaN and drawn as gaps, never as zero

## Project structure

```
avaz-trainer/
  CLAUDE.md
  README.md
  pyproject.toml
  config/
    settings.yaml        # audio params, tonic, smoothing, colors
    scales.yaml          # dastgah scale positions in cents
  src/avaz/
    audio_io.py          # load/convert files, mic stream, playback
    pitch_offline.py     # pyin analysis -> pitch curve files
    pitch_live.py        # real-time YIN on mic blocks
    cents.py             # Hz <-> cents, octave folding, tonic estimation
    scales.py            # load scales, calibration from histogram
    slicer.py            # silence-based phrase detection, call-and-response tracks
    compare.py           # DTW alignment and scoring
    ui/
      live_view.py       # scrolling live pitch chart with guide lines
      practice_view.py   # reference + live curves, record attempt
    cli.py               # command-line entry points
  web/                   # phone web app (PWA), static files
    index.html
    tests.html           # browser test runner for the pure JS logic
    scales.json          # exported from config/scales.yaml
    js/                  # cents, yin, scales, notes, stream, feedback, audio, chart, app
  data/                  # gitignored
    teacher/             # original recordings from my teacher
    phrases/             # sliced phrases (audio + pitch curve)
    attempts/            # my recorded attempts + scores
  tests/
```

### Pitch curve file format

One JSON (or CSV) file per phrase, next to its audio:

```json
{
  "source": "phrase_03.wav",
  "sample_rate": 44100,
  "hop_seconds": 0.0058,
  "tonic_hz": 196.0,
  "times": [...],
  "f0_hz": [...],
  "cents": [...],
  "voiced": [...]
}
```

## Milestones

Each milestone ends with something I can run.

### M0: Setup
- Repo, virtual environment, `pyproject.toml`, config files, empty package, one passing test.
- Check that `ffmpeg`, `sounddevice` (list input and output devices), and the YIN backend all work.
- **Done when**: `avaz devices` lists my mic and headphones.

### M1: Offline analysis
- `avaz analyze <file> --tonic <hz|auto>` loads any teacher recording, runs pyin, saves the pitch curve file, and shows a plot of cents over time with scale guide lines.
- `avaz histogram <file>` shows the folded pitch histogram and suggests scale positions.
- **Done when**: I can see a clean curve of a teacher recording, and the histogram peaks line up with the notes I hear.

### M2: Phrase slicer and call-and-response tracks
- `avaz slice <file>` detects phrases at silences (configurable threshold and minimum pause), exports each phrase as audio plus its pitch curve, and writes an Audacity-compatible label file so I can fix cuts by hand and re-import them.
- `avaz callresponse <file>` writes one track where every phrase is followed by silence of exactly that phrase's length (with an optional extra margin setting).
- **Done when**: I can practice along with the call-and-response track with no manual editing.

### M3: Live pitch view
- `avaz live --scale shur --tonic <hz>` opens a window with a scrolling curve of my voice in cents, horizontal guide lines for the scale, and a readout of the current deviation from the nearest scale note.
- **Done when**: latency feels immediate and the curve is stable on sustained notes.

### M4: Practice mode
- `avaz practice <phrase>` plays the teacher phrase in my headphones while drawing its curve, then (or simultaneously, as a setting) draws my live curve on the same chart and records my attempt to `data/attempts/`.
- Supports looping one phrase and slowing playback without changing pitch.
- **Done when**: I can practice one phrase ten times in a row without touching anything but the keyboard.

### M5: Scoring
- Align my attempt to the reference with DTW on voiced frames (after octave folding), then report: mean absolute deviation in cents, percentage of frames within plus or minus 25 cents, and the worst sections.
- Show an overlay of both aligned curves with the problem areas highlighted.
- Keep a simple history per phrase so I can see progress over days.
- **Done when**: the score clearly improves when I sing a phrase better, and the highlighted sections match what my ear tells me.

### P1: Phone live view
- `avaz web` exports the scales and serves `web/` on the laptop. The phone opens it in Chrome (or it is published on GitHub Pages).
- Pick my key by solfege name and the dastgah in a settings sheet, then tap the mic button: scrolling note lanes with my voice, the current note name, and plain words for in tune, low or high. Optional drone on the tonic. A demo mode (`?demo`) feeds a synthetic voice for testing without a mic.
- **Done when**: on my phone the curve follows my voice with no visible delay, sustained notes are stable, and the note name matches what my teacher calls it.

### P2: Phone practice mode
- `avaz export-phone <song>` bundles a song's phrases (audio, pitch curves, tonic, scale positions) into one pack the phone can load.
- Play, loop and slow down a phrase (pitch preserved), see the teacher's lanes with mine on top, record attempts on the phone. A latency offset setting for Bluetooth headphones.
- **Done when**: I can practice a lesson on the phone without the laptop.

### P3: Phone scoring and history
- Port the numpy DTW scoring and the gentle feedback to JavaScript, tested against the same cases as the Python version. Keep progress per phrase on the phone, with a way to copy attempts back to the laptop.
- **Done when**: the phone gives the same score and tips as the laptop for the same attempt.

### M6 (later): Hardware
- Run the app on a Raspberry Pi 4/5 or Zero 2 W with a USB or I2S (INMP441) mic, a small screen, and headphones.
- Optional: a physical button to replay or loop the current phrase.
- Optional stretch: vocal separation (for example, Demucs) run on the PC for teacher recordings that include tar or setar accompaniment.

## Start here (first session)

1. Read this file and ask me which OS I'm on and what mic I'm using.
2. Do M0.
3. Then start M1 using one of the teacher recordings I put in `data/teacher/`.

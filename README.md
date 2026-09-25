# Avaz Trainer

A personal practice tool for Persian classical singing (avaz). It extracts pitch
curves from teacher recordings, shows my own pitch live in cents relative to a
tonic, and (later) scores my attempts against the reference.

## Setup

Windows (PowerShell) or Linux, Python 3.11 or newer:

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux
source .venv/bin/activate

pip install -e .[dev]
```

On Windows, PowerShell may refuse to run `Activate.ps1` with "running scripts is
disabled on this system". Either skip activation and call the venv directly
(`.venv\Scripts\avaz.exe check`), or allow local scripts for your user once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

ffmpeg: the app looks for `ffmpeg` on PATH first and otherwise uses the binary
bundled with the `imageio-ffmpeg` package, so nothing else needs to be installed.
Installing a system ffmpeg (`winget install Gyan.FFmpeg` on Windows,
`sudo apt install ffmpeg` on Debian or Ubuntu) also works.

Vocal separation (optional, needed when the teacher plays an instrument while
singing) uses Demucs, which pulls in PyTorch:

```bash
pip install demucs
```

## Workflow for a new teacher recording

```bash
avaz separate data/teacher/song.m4a            # only if there is accompaniment
avaz analyze data/teacher/song.vocals.wav      # pitch curve + plot
avaz histogram data/teacher/song.vocals.wav    # where the teacher places each note
avaz slice data/teacher/song.vocals.wav --plot # cut into phrases, write labels.txt
avaz callresponse data/teacher/song.vocals.wav # phrase, gap, phrase, gap, ...
```

Without accompaniment, skip `separate` and run the rest on the original file.

`avaz slice` writes `data/phrases/<song>/phrase_NN.wav`, a pitch curve JSON next
to each one, and `labels.txt` in Audacity's label format. Add `--clean` to remove
phrase files from an earlier run first. To fix cuts by hand:
open the audio in Audacity, File > Import > Labels, drag the boundaries, File >
Export > Labels, then rerun `avaz slice ... --labels <exported file>`.

`avaz callresponse` writes `call_response.wav`, where each phrase is followed by
silence of exactly the phrase's length plus a margin (`slicer.response_margin_seconds`
in settings, or `--margin`). A label file next to it marks every call and response.

## Live pitch view

```bash
avaz live --scale dashti                  # mic in, scrolling curve in cents, guide lines
avaz live --scale dashti --tonic 185      # override the tonic
avaz live --scale dashti --device headset # pick an input by index or name fragment
avaz live --scale dashti --input-file data/phrases/song/phrase_04.wav   # test with a file
```

The window shows the last few seconds of your pitch in cents relative to your tonic,
dashed guide lines for every scale note (solid green for the tonic in each octave),
and a readout of the nearest note and your deviation from it: green within 25 cents,
yellow within 50, red beyond. Keys: Esc quits, Space pauses, R clears the trace.

Tuning knobs live under `live:` and `audio:` in `config/settings.yaml`
(`smoothing_frames`, `history_seconds`, `cents_range`, `hop_length`). Command line
overrides: `--smooth`, `--hop`, `--block`, `--sample-rate`.

## Practice mode

```bash
avaz practice "data/phrases/song/phrase 1.wav" --scale dashti
avaz practice "data/phrases/song/phrase 1.wav" --scale dashti --mode along --speed 0.8 --loop
```

The teacher curve is drawn in blue. Press Space: in `after` mode the phrase plays
("LISTEN"), then the app waits for your voice ("SING WHEN READY") and the moment
you start, the cursor runs over the teacher curve again while your curve is drawn
in red on top ("YOUR TURN"). In `along` mode you sing with the teacher. Every
attempt is saved automatically to `data/attempts/<song>/<phrase>/<timestamp>.wav`
with its live pitch curve and a small meta file (mode, speed, tonics). If you stay
silent for `practice.wait_timeout_seconds`, the attempt is dropped.

Keys: Space start or stop, L loop on/off, `[` and `]` slower or faster (0.5 to 1.0,
pitch unchanged), M switch mode, N and P next or previous phrase in the folder,
O toggle octave folding of your curve, V toggle voice start (off = the cursor starts
right after the phrase), Esc quit.

Your tonic defaults to `tonic.mine_hz` in settings, then the teacher's. If you sing
an octave lower than the teacher, the red curve is shifted up by an octave so the
shapes line up (`practice.fold_octave`). Use headphones if the mic picks up the
speakers, or set `--gain` lower.

## Scoring

```bash
avaz score "data/attempts/song/phrase 1/20260925_121107.wav" --plot --scale dashti
avaz score "data/attempts/song/phrase 1" --new     # score every attempt not scored offline yet
avaz history "data/attempts/song/phrase 1" --plot
```

Practice mode already scores every attempt from the live curve and shows the
result in the status bar. `avaz score` re-analyzes the recording with pyin, which
is more accurate, and replaces that entry in `history.json` next to the attempts.

How the score works: both curves are cut into 20 ms bins, unvoiced bins are
dropped, my curve is shifted by whole octaves onto the teacher's, and the two are
aligned with dynamic time warping (DTW) so small timing differences do not count.
The report gives the percentage of aligned frames within the tolerance
(`scoring.tolerance_cents`, 25 by default), the mean and median absolute deviation
in cents, the overall offset (flat or sharp on average), the timing ratio, and the
worst sections in the teacher's timeline with "flat", "sharp" or "unsteady" and the
amount. The plot shades those sections in red and shows the deviation track
underneath.

The attempt is measured against the tonic stored in its meta file (the one the
practice session used). Pass `--my-tonic <hz>` to rescore against another tonic,
for example after changing `tonic.mine_hz` in settings.

## Other commands

```bash
avaz check      # ffmpeg, audio devices and pitch backend all working?
avaz devices    # list microphones and outputs
```

The tonic defaults to `tonic.teacher_hz` in `config/settings.yaml`. Override per
command with `--tonic <hz>`, `--tonic auto` (strongest histogram peak) or
`--tonic final` (last sustained note).

## Tests

```bash
pytest
```

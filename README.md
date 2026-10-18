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

## The main window

```bash
avaz gui
```

Everything below can be done from one window, without command line arguments:

- **Songs** on the left are the recordings in `data/teacher/`, with the key
  you sing each one in and how many attempts you have made.
- **Add recording...** copies a file from your teacher into the library. If
  the recording has an instrument besides the voice, the voice is separated
  first (Demucs, a few minutes); then the pitch is analyzed.
- **Teacher's tonic**: read from the file name when the teacher wrote the key
  in it ("... دشتی می بمل" is Mi bemol, "... فا دیز" is Fa diez, "... ر" is
  Re). The name gives the note; the octave is picked from where the voice sits
  (in Dashti the melody centers about a whole tone under the tonic). Without
  a key in the name the analysis only guesses, so check it. If you have the
  same song in another key, pick it under "compare with" and press
  **Measure**: the two recordings are lined up note by note, which is much more
  reliable than the guess. A tonic typed here always wins.
- **I sing in**: either the teacher's key (your pitch is compared exactly as
  you sing it) or your own key, picked by note name (Do, Re, Mi ... with the
  Western name and octave next to it) and fine tuned in Hz. Each song remembers
  its own choice, and the last key you chose becomes your default for new songs.
- **Scale**, **Practice** (the whole song, or the phrases saved from it),
  the **Intro** cut, your sound devices, and **Progress** per song.

Song choices are saved in `data/phrases/<song>/song.yaml` and your own
preferences in `data/user.yaml`, the same files the command line reads. `data/`
is not in git, so every classmate who clones the project keeps their own
recordings, keys and scores.

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
D notes or detailed curve, O toggle octave folding of your curve, V toggle voice start (off = the cursor starts
right after the phrase), Esc quit.

Your tonic defaults to `tonic.mine_hz` in settings, then the teacher's. If you sing
an octave lower than the teacher, the red curve is shifted up by an octave so the
shapes line up (`practice.fold_octave`). Use headphones if the mic picks up the
speakers, or set `--gain` lower.

## Note blocks or detailed curve

Both practice windows start in the simple look: one shaded lane per note of the
dastgah, named after the real note in the key you sing in (for Dashti on Mi:
Mi, Fa sori, Sol, La, Si, Do, Re). While a voice stays on a note, its lane
lights up: blue blocks for the teacher, and for you green when you are within
`scoring.tolerance_cents` (25) of the note and orange when you are further off.
Thin lines on top still show the ornaments. Press **D** for the detailed curve
in cents with dashed guide lines; `display.style` in settings picks the start.

## Song mode (no pre-cut phrases needed)

```bash
avaz song data/teacher/song.vocals.wav --scale dashti
```

An alternative to slicing in Audacity first: play the whole recording and
choose where to pause and sing as you go. One key walks forward through the
whole thing:

- **Space** (or **Enter**): start the recording playing. Press it again whenever you want to
  stop and sing back what you just heard. Press it a third time when you are
  done singing to save your attempt and let the teacher continue from there.
- **R**: instead of moving on, replay the stretch you just sang and try it
  again.
- **Backspace**: replay the last stretch you sang, even after the teacher has
  already moved on to the next one. It pauses by itself at the end of the
  stretch, so you can sing straight away without pressing Space.
- **Delete**: everything before this point is intro. Press it the first time
  you hear a song, right where the singing you want to practice begins (or
  while paused after the intro, which drops that whole stretch). The cut is
  saved as `intro_end_seconds` in the song's `song.yaml`, shaded grey on the
  chart, and every later session starts there. **Shift+Delete** removes it.
- **D**: switch between note blocks and the detailed curve (see below).
- **T**: drone on or off: a soft steady tone on your home note to sing
  against, which helps the ear hear when a note is too high or too low. Use
  headphones: through the speakers the microphone hears the drone too. When you
  sing in another key than the teacher it stays quiet while the teacher plays.
  Its loudness is `practice.drone_gain`.
- **Esc**: stop.

### Tips in plain words

After each stretch, the panel under the chart says how it went, without numbers.
**Tips** in the main window picks how strict it is (saved per person in
`data/user.yaml`):

- **Gentle** (the default): only the teacher's long, steady notes are judged;
  fast ornaments are left out. A note counts as hit when you held its pitch,
  within a quarter tone, for about a third of its length, up to half a second
  early or late. You get stars and "You hit 6 of 9 long notes", a cheer when
  it is better than your last try of that stretch, and **one** tip for next
  time, the most general first: "aim a bit higher overall", then the one note
  that was furthest off, then holding notes steady, then timing. Only notes off
  by half a tone or more are shaded on the chart (at most two). While you sing,
  "a bit higher" or "a bit lower" appears under the chart only when you stay
  clearly off for half a second; being on the note shows nothing.
- **Detailed**: every moment within 25 cents, up to three problem spots with
  arrows on the chart, a line per kind of problem, and a live arrow next to
  your line.

The thresholds are in the `feedback` section of `config/settings.yaml`. Phrase
practice shows the same tips.

Every stretch you sing along to is saved the first time as a normal phrase,
`data/phrases/<song>/live_01.wav`, `live_02.wav`, and so on, with its own
pitch curve and an entry in `labels.txt`, exactly as if you had labeled it in
Audacity. That means `avaz score`, `avaz history` and ordinary
`avaz practice live_01.wav` all work on it afterwards. Every repeat is scored
and saved too, so `avaz history` shows your repeats of the same stretch
alongside first attempts sliced by hand.

After a pause the app waits for your voice ("SING WHEN READY"), so the time you
need to breathe does not count. Your curve is drawn so that the moment you start
singing lines up with the moment the teacher starts singing in that stretch. The
first `practice.onset_grace_seconds` after the pause are ignored, because the
speakers are still ringing with the teacher's last note. Press V to turn voice
start off. Voice start listens for `practice.onset_rms_db` (-50 dBFS), and live
pitch detection ignores anything under `audio.pitch_silence_db` (-55 dBFS). Both
sit well above the Surface's room noise (about -76 dBFS) and below soft singing.

`--out-dir` changes where phrases are saved. Speed control is not available in
this mode yet.

## Same key or transposed

By default your curve is measured from your own tonic and the teacher's from
theirs, so you can sing a recording in your own key and still compare shapes.
Your tonic is the key chosen for the song (`my_tonic_hz` in its song.yaml, set
in `avaz gui` or with `--my-tonic`), otherwise `tonic.mine_hz` in settings.
When you sing in the teacher's key, compare absolute pitch instead:

```bash
avaz song data/teacher/song.vocals.wav --same-key --teacher-tonic 132
avaz song data/teacher/song.vocals.wav --no-same-key --my-tonic 164.8   # sing it in Mi
```

These choices are remembered in `data/phrases/<song>/song.yaml`, and practice
mode and `avaz score` read the same file for that song's phrases. In the same
key nothing is transposed or octave folded: singing a third or an octave off
shows up as exactly that. `--no-same-key` switches back.

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
in cents, the overall key offset, the timing ratio, and the worst sections in the
teacher's timeline with "flat", "sharp" or "unsteady" and the amount. The plot
shades those sections in red and shows the deviation track underneath.

The key offset says where your notes sit against the teacher's, whatever the
timing. Both curves become histograms of where the voice spends its time, and
yours is slid up and down until it lines up best with the teacher's. It does not
depend on how long you hold each note, and it cannot be fooled by DTW pairing a
flat note with the teacher's neighbouring note a step lower. When an attempt has
too little singing to tell, no offset is reported.

The attempt is measured against the tonic stored in its meta file (the one the
practice session used). Pass `--my-tonic <hz>` to rescore against another tonic,
for example after changing `tonic.mine_hz` in settings.

## Phone app

`web/` is a version for Android phones: a web app that runs in Chrome and can
be added to the home screen. Pick your key and dastgah in the sheet that opens
on first use.

**Free singing** shows the note you are on (Re, Mi koron, Fa sori ...), plain
words (in tune, a bit low, go up) and your voice lighting up the note lanes.
The view follows your voice up and down by itself. The top right buttons
switch on a drone on your tonic (use headphones, or the mic hears it) and
switch between note lanes and the detailed curve. "Detailed" feedback in the
settings adds cents and Hz.

**Teacher's recordings**: tap **Add recording** and pick the file your teacher
sent (m4a, opus, mp3, wav). Once the app is installed you can also share a
recording from WhatsApp straight to Avaz. The phone finds the teacher's notes
itself (about ten seconds for a four minute song) and reads the key from the
file name ("... دشتی فا دیز" is Fa diez). If the name has no key, tap the song
name at the top and pick it. The same sheet chooses whether you sing in the
teacher's key or your own; a recording in your own key ("... دشتی ر" when you
sing in Re) is set to the teacher's key by itself.

Then: **Play**, and tap **My turn** wherever you want to sing back what you
just heard. The app waits for your voice, so breathing time does not count,
and draws you (green on the note, orange off it) over the teacher (blue). It
stops by itself when you finish. **Continue** goes on with the song, **Sing
again** tries the same stretch, **Hear again** replays it first. While the
teacher plays, **Back 5 s** jumps back, and the bar under the chart seeks.
Everything stays on the phone; your curves are kept per stretch for scoring
later.

On the laptop:

```bash
avaz web
```

Then open http://localhost:8765 (add `?demo` for a synthetic singer, no mic
needed, and `&mute` to play recordings silently) and http://localhost:8765/tests.html for the logic tests.

On the phone, Chrome only allows the microphone on https pages or on
localhost. Two ways:

- **GitHub Pages** (for daily use): on github.com, Settings > Pages > Source:
  "GitHub Actions". Every push to main that changes `web/` publishes the app at
  `https://<user>.github.io/avaz-trainer/`. Open it in Chrome on the phone and
  choose "Add to Home screen". After the first visit it also works offline.
- **USB cable** (for trying changes): enable USB debugging on the phone, plug
  it in, open `chrome://inspect/#devices` in Chrome on the laptop, turn on "Port
  forwarding" for `8765` to `localhost:8765`, and open http://localhost:8765 in
  Chrome on the phone while `avaz web` runs.

`avaz web --lan` makes the page reachable over Wi-Fi too, but there the mic
stays off (no https), so only the demo works.

After editing `config/scales.yaml`, run `avaz web --export-only` (or just
`avaz web`) so the phone gets the same scale positions; a test checks this.

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

The phone app's logic (YIN, cents, scales, note names) is tested in the browser:
run `avaz web` and open http://localhost:8765/tests.html.

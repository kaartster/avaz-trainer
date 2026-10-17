"""Note names for choosing a key: Hz <-> "Re (D3)".

Each student sings a song in their own key, so the key is picked by note name
rather than typed in Hz. Names use solfege (Do, Re, Mi ...) first because that is
how keys are named in class ("Dashti in Fa diez"); the Western name with its
octave number follows as a secondary label. Positions are equal tempered
relative to A4 = 440 Hz. That is only for naming the tonic: the notes of the
dastgah itself always come from scales.yaml in cents.
"""

from __future__ import annotations

import math
import re

SOLFEGE = ["Do", "Do diez", "Re", "Mi bemol", "Mi", "Fa", "Fa diez", "Sol", "Sol diez",
           "La", "Si bemol", "Si"]
WESTERN = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B"]
A4_HZ = 440.0


def note_to_hz(index: int, octave: int, a4_hz: float = A4_HZ) -> float:
    """Frequency of note ``index`` (0 = Do/C ... 11 = Si/B) in ``octave`` (C4 = middle C)."""
    midi = 12 * (octave + 1) + int(index)
    return a4_hz * 2.0 ** ((midi - 69) / 12.0)


def hz_to_note(hz: float, a4_hz: float = A4_HZ) -> tuple[int, int, float]:
    """Nearest note to ``hz``: ``(index, octave, cents_off)``, cents_off in [-50, 50]."""
    midi = 69 + 12 * math.log2(float(hz) / a4_hz)
    nearest = int(round(midi))
    return nearest % 12, nearest // 12 - 1, 100.0 * (midi - nearest)


def note_label(hz: float, show_cents: bool = True) -> str:
    """``"Mi (E3) +23"``: solfege name, Western name with octave, and the offset in cents
    when it is 5 cents or more."""
    index, octave, off = hz_to_note(hz)
    label = f"{SOLFEGE[index]} ({WESTERN[index]}{octave})"
    if show_cents and abs(off) >= 5:
        label += f" {off:+.0f}"
    return label


def key_choices(low_octave: int = 2, high_octave: int = 4) -> list[tuple[str, float]]:
    """Every note from Do of ``low_octave`` to Si of ``high_octave`` as ``(label, hz)``."""
    return [(note_label(note_to_hz(i, o), show_cents=False), note_to_hz(i, o))
            for o in range(low_octave, high_octave + 1) for i in range(12)]


# Natural notes (white keys). A quarter tone just above one of these is its "sori"
# (Fa sori); a quarter tone just below one is its "koron" (Si koron).
_NATURAL = {0, 2, 4, 5, 7, 9, 11}


def scale_note_name(tonic_hz: float, cents: float) -> str:
    """Solfege name of the note ``cents`` above ``tonic_hz``, with koron and sori.

    Notes within 25 cents of an equal tempered semitone get that name ("Sol",
    "Fa diez"). Notes in between are named the Persian way: sori on the natural
    note below (Mi + 150 cents is "Fa sori"), otherwise koron on the natural note
    above (La + 150 cents is "Si koron").
    """
    index, _, off = hz_to_note(float(tonic_hz) * 2.0 ** (float(cents) / 1200.0))
    if abs(off) <= 25:
        return SOLFEGE[index]
    lower = index if off > 0 else (index - 1) % 12
    upper = (lower + 1) % 12
    if lower in _NATURAL:
        return f"{SOLFEGE[lower]} sori"
    if upper in _NATURAL:
        return f"{SOLFEGE[upper]} koron"
    return SOLFEGE[index]


# ---------------------------------------------------------------- key from a file name
#
# The teacher names recordings after their key: "دشتی فا دیز" (Dashti in Fa diez),
# "دشتی ر", "دشتی می بمل". The name gives the note but not the octave, so the
# octave is picked from where the voice actually sits (see tonic_from_name).

_PERSIAN_NOTES = {"دو": 0, "ره": 2, "ر": 2, "ری": 2, "می": 4, "فا": 5, "سل": 7, "سول": 7,
                  "لا": 9, "سی": 11}
_LATIN_NOTES = {"do": 0, "re": 2, "mi": 4, "fa": 5, "sol": 7, "la": 9, "si": 11}
_SHARP = ("دیز", "diez", "dies", "sharp", "#")
_FLAT = ("بمل", "bemol", "flat")

# Longest names first, so "سول" is tried before "سل" and "ره" before "ر".
_NOTE_ALTERNATIVES = "|".join(sorted(list(_PERSIAN_NOTES) + list(_LATIN_NOTES), key=len, reverse=True))
_KEY_PATTERN = re.compile(
    rf"(?<![^\W_])({_NOTE_ALTERNATIVES})[ _-]?({'|'.join(_SHARP + _FLAT)})?(?![^\W_#])",
    re.IGNORECASE)


def key_from_name(name: str) -> int | None:
    """Note index (0 = Do ... 11 = Si) of the key written in a recording's name, or None.

    The last note name in the text wins, because the key is written at the end
    ("کعبه دلها _ دشتی ر"), and words earlier in a title can look like note
    names ("می" is also a common verb prefix in Persian).
    """
    text = str(name).replace("\u200c", "")            # zero width non-joiner
    for suffix in (".vocals", ".accompaniment"):
        text = text.replace(suffix, " ")
    text = re.sub(r"\.\w+$", "", text)                       # file extension
    text = re.sub(r"[\"'«»“”]", " ", text)
    matches = list(_KEY_PATTERN.finditer(text))
    if not matches:
        return None
    note, accidental = matches[-1].group(1).lower(), (matches[-1].group(2) or "").lower()
    index = _PERSIAN_NOTES.get(note, _LATIN_NOTES.get(note))
    if accidental in _SHARP:
        index += 1
    elif accidental in _FLAT:
        index -= 1
    return index % 12


# In Dashti the melody sits mostly below the tonic: across the teacher's recordings the
# median pitch is 200 to 250 cents (about a whole tone) under it.
TONIC_ABOVE_MEDIAN_CENTS = 250.0


def tonic_from_name(name: str, median_hz: float | None) -> float | None:
    """The tonic in Hz from the key in ``name``, in the octave that fits the voice.

    ``median_hz`` is the median pitch of the recording's voiced frames. The tonic
    is the octave of the named note closest to ``TONIC_ABOVE_MEDIAN_CENTS`` above it.
    None when the name has no key or there is no pitch to place it.
    """
    index = key_from_name(name)
    if index is None or not median_hz or not math.isfinite(median_hz) or median_hz <= 0:
        return None
    target = 69 + 12 * math.log2(median_hz / A4_HZ) + TONIC_ABOVE_MEDIAN_CENTS / 100.0
    midi = index + 12 * round((target - index) / 12)
    return A4_HZ * 2.0 ** ((midi - 69) / 12.0)

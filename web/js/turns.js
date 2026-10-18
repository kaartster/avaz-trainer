// Singing after the teacher, with pauses I choose. Port of FreeformSession and
// OnsetDetector in src/avaz/practice.py, in seconds instead of samples. No DOM,
// no audio APIs, so all of it is tested in tests.html.
//
//   idle --Play--> play --My turn--> wait --voice--> sing --Done/auto--> review
//   review --Continue--> play (from where I paused)
//   review --Sing again--> wait          any --Hear again--> play the stretch, then wait

import { firstVoicedTime } from "./offline.js";

export class SongSession {
  constructor(duration, startAt = 0) {
    this.duration = duration;
    this.pos = Math.min(Math.max(0, startAt), duration);
    this.phase = "idle";
    this.segStart = this.pos;
    this.segEnd = this.pos;
    this.autoPauseAt = null;
    this.reachedEnd = false;
  }

  /** Playback position update while playing. Returns true when it just paused. */
  tick(pos) {
    if (this.phase !== "play") return false;
    this.pos = pos;
    if (this.autoPauseAt !== null && pos >= this.autoPauseAt) {
      this.pos = this.autoPauseAt;
      this.pause();
      return true;
    }
    if (pos >= this.duration) {
      this.pos = this.duration;
      this.pause(true);
      return true;
    }
    return false;
  }

  pause(reachedEnd = false) {
    this.segEnd = this.pos;
    this.reachedEnd = reachedEnd;
    this.autoPauseAt = null;
    this.phase = "wait";
  }

  /** The one big button: Play, My turn, Done, Continue. */
  primary() {
    if (this.phase === "idle") {
      if (this.pos >= this.duration) this.pos = 0;
      this.segStart = this.pos;
      this.phase = "play";
    } else if (this.phase === "play") {
      this.pause();
    } else if (this.phase === "wait" || this.phase === "sing") {
      this.phase = "review";
    } else if (this.phase === "review") {
      this.segStart = this.pos = this.segEnd;
      this.phase = this.reachedEnd ? "idle" : "play";
    }
  }

  voiceStarted() {
    if (this.phase === "wait") this.phase = "sing";
  }

  singAgain() {
    if (this.phase === "review" || this.phase === "sing") this.phase = "wait";
  }

  /** Replay the stretch I'm working on, then pause at its end for me to sing. */
  hearAgain() {
    if (this.phase === "idle" || this.phase === "play") return;
    this.pos = this.segStart;
    this.autoPauseAt = this.segEnd;
    this.reachedEnd = false;
    this.phase = "play";
  }

  /** Jump to `t` seconds. While playing, the stretch starts again there. */
  seek(t) {
    t = Math.min(Math.max(0, t), this.duration);
    if (this.phase === "play") {
      this.pos = this.segStart = t;
      this.autoPauseAt = null;
    } else {
      this.pos = this.segStart = this.segEnd = t;
      this.phase = "idle";
    }
  }
}

/**
 * Decides when I start singing: loud enough and pitched for a few frames in a
 * row, after a short grace time in which the speaker is still ringing with the
 * teacher's last note.
 */
export class OnsetDetector {
  constructor({ graceUntil = 0, rmsDb = -50, voicedFrames = 6 } = {}) {
    this.graceUntil = graceUntil;
    this.rmsDb = rmsDb;
    this.voicedFrames = voicedFrames;
    this.run = [];
  }

  /** Feed one pitch point and the loudness of its block. Returns the onset time or null. */
  feed(t, cents, loudDb) {
    if (t < this.graceUntil) return null;
    if (Number.isFinite(cents) && loudDb > this.rmsDb) this.run.push(t);
    else this.run = [];
    return this.run.length >= this.voicedFrames ? this.run[0] : null;
  }
}

/**
 * One try at singing a stretch back. Mic points arrive in mic time; they are
 * shifted so the moment I start singing lines up with the moment the teacher
 * started singing in the stretch. Breathing time before I start does not count.
 */
export class Take {
  constructor(teacherTimes, teacherCents, segStart, segEnd, prerollSeconds = 0.15) {
    this.segStart = segStart;
    this.segEnd = segEnd;
    this.prerollSeconds = prerollSeconds;
    // Where the teacher starts singing in this stretch (or its start if never).
    const t = [], c = [];
    for (let i = 0; i < teacherTimes.length; i++) {
      if (teacherTimes[i] >= segStart && teacherTimes[i] <= segEnd) { t.push(teacherTimes[i]); c.push(teacherCents[i]); }
    }
    const onset = firstVoicedTime(t, c, 4);
    this.teacherOnset = Number.isFinite(onset) ? onset : segStart;
    // When the teacher's singing in the stretch ends, for finishing on my own.
    let last = segStart;
    for (let i = 0; i < t.length; i++) if (Number.isFinite(c[i])) last = t[i];
    this.teacherEnd = last;
    this.offset = null;            // song time = mic time + offset, once I started
    this.recent = [];              // mic points before the onset, for the preroll
    this.times = [];               // in song time
    this.cents = [];
    this.lastVoiced = -Infinity;   // mic time
    this.micNow = 0;
  }

  get started() {
    return this.offset !== null;
  }

  /** Mic point while waiting for my voice. */
  listen(t, cents) {
    this.micNow = t;
    this.recent.push([t, cents]);
    while (this.recent.length && this.recent[0][0] < t - 1) this.recent.shift();
  }

  /** I started singing at mic time `onset`: keep a little before it, line it up. */
  begin(onset) {
    this.offset = this.teacherOnset - onset;
    for (const [t, c] of this.recent) if (t >= onset - this.prerollSeconds) this.add(t, c);
    this.recent = [];
  }

  add(t, cents) {
    this.micNow = Math.max(this.micNow, t);
    if (!this.started) return this.listen(t, cents);
    this.times.push(t + this.offset);
    this.cents.push(cents);
    if (Number.isFinite(cents)) this.lastVoiced = t;
  }

  /** Song time that matches "now" in my singing. */
  get cursor() {
    return this.started ? this.micNow + this.offset : this.segStart;
  }

  /** Finished by itself: past the teacher's last note and quiet for a moment. */
  finished(silence = 1.0) {
    if (!this.started) return false;
    const pastEnd = this.cursor > this.teacherEnd;
    const quiet = this.micNow - this.lastVoiced >= silence;
    return (pastEnd && quiet) || this.cursor > this.segEnd + 4;
  }
}

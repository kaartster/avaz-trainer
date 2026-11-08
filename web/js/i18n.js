// The app's words in English and Farsi. Pure logic, no DOM: the screens ask for
// text with t("key", {vars}), and ui.js fills the static page from data-i18n.
//
// Farsi is written right to left, uses Persian digits (۰۱۲۳) and Persian note
// names (ر، می بمل، سی کرن). Western names like D3 stay as a secondary label.

import { SOLFEGE, WESTERN, hzToNote, scaleNote } from "./notes.js";

export const LANGS = { en: "English", fa: "فارسی" };

const SOLFEGE_FA = ["دو", "دو دیز", "ر", "می بمل", "می", "فا", "فا دیز", "سل", "سل دیز", "لا",
  "سی بمل", "سی"];
const MARKS = { en: { sori: "sori", koron: "koron" }, fa: { sori: "سری", koron: "کرن" } };
const DASTGAH_FA = {
  shur: "شور", mahur: "ماهور", dashti: "دشتی", homayoun: "همایون", homayun: "همایون",
  segah: "سه‌گاه", chahargah: "چهارگاه", nava: "نوا", rastpanjgah: "راست‌پنجگاه",
  abuata: "ابوعطا", afshari: "افشاری", bayat_tork: "بیات ترک", bayat_esfahan: "بیات اصفهان",
  esfahan: "اصفهان",
};

const plural = (n, one, many) => `${n} ${Number(n) === 1 ? one : many}`;

const STRINGS = {
  en: {
    appTitle: "Avaz Trainer",
    brand: "Avaz",
    language: "Language",
    back: "Back",
    done: "Done",
    octave: "Octave",
    // home
    homeSettingsAria: "Your key and settings",
    freeTitle: "Free singing",
    freeSub: "See your voice on the notes, no recording",
    recordingsTitle: "Teacher's recordings",
    emptySongs: "Add a recording your teacher sent you. After installing the app you can also share a recording from WhatsApp straight to Avaz.",
    addRecording: "Add recording",
    tries: ({ n }) => plural(n, "try", "tries"),
    keyLineSame: "{teacher}, the teacher's key",
    keyLineOther: "Teacher in {teacher}, you in {mine}",
    adding: "Adding {name}",
    addingTitle: "Adding recording",
    noStorage: "This browser does not allow storing recordings (private window?).",
    noKeyInName: "The file name doesn't say the key. Check the teacher's key at the top of the song.",
    addFailed: "Could not add this recording.",
    stepOpening: "Opening the recording",
    stepFinding: "Finding the teacher's notes",
    stepSaving: "Saving",
    progress: "{step}, {p}%",
    notAudio: "This file could not be opened as audio.",
    noSinging: "No singing found in this recording.",
    sharedRecording: "shared recording",
    // free singing
    keyChipAria: "Key and dastgah settings",
    droneAria: "Drone on the tonic",
    viewAria: "Switch between notes and curve",
    ready: "Ready",
    low: "low",
    high: "high",
    tapMicAndSing: "Tap the mic and sing",
    liveChartAria: "Your pitch over the last seconds",
    startListening: "Start listening",
    stopListening: "Stop listening",
    tapToSing: "Tap to sing",
    listeningTapStop: "Listening, tap to stop",
    demoTapStop: "Demo voice, tap to stop",
    listening: "Listening",
    singLongNote: "Sing a long note",
    inTune: "In tune",
    bitLow: "A bit low, go up",
    low2: "Low, go up",
    bitHigh: "A bit high, go down",
    high2: "High, go down",
    detail: "{dev} cents · {hz} Hz",
    hintDemo: "Demo mode: tap the button to see a synthetic singer on the chart.",
    hintVoice: "Your voice will draw here. Hold a note and watch its lane light up.",
    hintHeadphones: "Use headphones with the drone, or the mic hears it too.",
    notesView: "Notes view",
    curveView: "Curve view",
    couldNotStart: "Could not start: {msg}",
    micInsecure: "The microphone only works over https or on localhost.",
    micBlocked: "Microphone access is blocked. Allow it for this site in Chrome's settings.",
    micMissing: "No microphone found.",
    // song
    songKeyAria: "Keys for this song",
    song: "Song",
    songChartAria: "The teacher's notes and yours",
    positionAria: "Position in the song",
    loading: "Loading",
    endOfSong: "End of the song",
    endOfSongSub: "Tap Play to start again from the beginning.",
    listenTeacher: "Listen to the teacher",
    listenTeacherSub: "Tap My turn whenever you want to sing back what you heard.",
    fromStart: "From the start",
    play: "Play",
    playingSub: "Tap My turn to sing back what you just heard.",
    myTurn: "My turn",
    back5: "Back 5 s",
    yourTurn: "Your turn",
    yourTurnSub: "Sing when you are ready.",
    hearAgain: "Hear again",
    singing: "Singing",
    singingSub: "It stops by itself when you finish.",
    notesOnChart: "Your notes are on the chart",
    notesOnChartSub: "Blue is the teacher, green and orange is you.",
    nothingHeard: "Nothing heard",
    nothingHeardSub: "Sing again, or go on.",
    finish: "Finish",
    continue: "Continue",
    singAgain: "Sing again",
    keyIsGuess: "The teacher's key is only a guess. Tap the song name to set it.",
    songMissing: "This recording is not on this phone any more.",
    songOpenFailed: "Could not open this recording.",
    micStartFailed: "Could not start the microphone: {msg}",
    // song sheet
    teacherKey: "Teacher's key",
    change: "Change",
    teacherOctaveAria: "Teacher's octave",
    iSingIn: "I sing it in",
    myKeyAria: "My key",
    myOctaveAria: "My octave",
    asRecorded: "as recorded",
    myOwnKey: "My own key",
    transposed: "transposed",
    keyFromName: "{key}, read from the file name.",
    keyByYou: "{key}, set by you.",
    keyGuess: "{key} is only a guess. Pick the key your teacher sang in.",
    singSame: "You sing exactly the teacher's notes, from {note}.",
    singOwn: "You sing from {key}. The teacher's notes are moved to your key on the chart.",
    songStart: "Start of the song",
    startWhole: "Plays from the very beginning. To skip an intro, go to where the singing starts (Play, or drag the bar), then tap Start here.",
    startAt: "Starts at {time} of the recording; everything before it is skipped.",
    startHere: "Start here ({time})",
    earlier: "1 s earlier",
    later: "1 s later",
    keepWhole: "Keep the whole recording",
    removeSong: "Remove this recording",
    removeConfirm: "Remove \"{name}\" from this phone?",
    // settings sheet
    yourKey: "Your key",
    keyIntro: "The note your teacher told you to sing in.",
    keyAria: "Key",
    fineTune: "Fine tune",
    fineTuneAria: "Fine tune in cents",
    fineCents: "{n} cents",
    keyHz: "{key}{fine}, {hz} Hz",
    octaveLow: "low",
    octaveMiddle: "middle",
    octaveHigh: "high",
    dastgah: "Dastgah",
    feedback: "Feedback",
    feedbackAria: "Feedback level",
    gentle: "Gentle",
    plainWords: "plain words",
    detailed: "Detailed",
    withCents: "with cents",
    moreSettings: "More settings",
    smoothing: "Smoothing",
    off: "Off",
    light: "Light",
    strong: "Strong",
    secondsShown: "Seconds shown",
    seconds: "{n} s",
    micGate: "Mic gate",
    micGateAria: "Mic gate in dB",
    gateHelp: "Sounds quieter than {db} dB are ignored. Raise it in a noisy room, lower it if soft singing is missed.",
    pictureTiming: "Picture timing",
    pictureTimingAria: "Picture timing in milliseconds",
    syncAhead: "Picture moved {ms} ms ahead. ",
    syncBack: "Picture moved {ms} ms back. ",
    syncHelp: "For the teacher's recordings: if the notes on screen come after what you hear, slide right; if they come before it, slide left. Bluetooth headphones usually need it.",
  },

  fa: {
    appTitle: "آواز",
    brand: "آواز",
    language: "زبان",
    back: "بازگشت",
    done: "تمام",
    octave: "اکتاو",
    // home
    homeSettingsAria: "کوک شما و تنظیمات",
    freeTitle: "آواز آزاد",
    freeSub: "صدایتان را روی نت‌ها ببینید، بدون ضبط",
    recordingsTitle: "فایل‌های استاد",
    emptySongs: "فایلی را که استادتان فرستاده اضافه کنید. بعد از نصب برنامه می‌توانید فایل را مستقیم از واتس‌اپ با آواز به اشتراک بگذارید.",
    addRecording: "افزودن فایل",
    tries: "{n} بار تمرین",
    keyLineSame: "{teacher}، کوک استاد",
    keyLineOther: "استاد در {teacher}، شما در {mine}",
    adding: "افزودن {name}",
    addingTitle: "افزودن فایل",
    noStorage: "این مرورگر اجازه‌ی ذخیره‌ی فایل نمی‌دهد (پنجره‌ی خصوصی؟).",
    noKeyInName: "کوک در نام فایل نیامده. کوک استاد را بالای صفحه‌ی آهنگ بررسی کنید.",
    addFailed: "افزودن این فایل ممکن نشد.",
    stepOpening: "باز کردن فایل",
    stepFinding: "پیدا کردن نت‌های استاد",
    stepSaving: "ذخیره",
    progress: "{step}، {p}٪",
    notAudio: "این فایل به‌عنوان صدا باز نشد.",
    noSinging: "در این فایل آوازی پیدا نشد.",
    sharedRecording: "فایل به‌اشتراک‌گذاشته",
    // free singing
    keyChipAria: "تنظیم کوک و دستگاه",
    droneAria: "صدای ممتد روی نت پایه",
    viewAria: "جابه‌جایی بین نت‌ها و منحنی",
    ready: "آماده",
    low: "پایین",
    high: "بالا",
    tapMicAndSing: "میکروفون را بزنید و بخوانید",
    liveChartAria: "صدای شما در چند ثانیه‌ی اخیر",
    startListening: "شروع شنیدن",
    stopListening: "توقف شنیدن",
    tapToSing: "بزنید و بخوانید",
    listeningTapStop: "در حال شنیدن، برای توقف بزنید",
    demoTapStop: "صدای نمایشی، برای توقف بزنید",
    listening: "در حال شنیدن",
    singLongNote: "یک نت کشیده بخوانید",
    inTune: "درست روی نت",
    bitLow: "کمی پایین، بالاتر بخوانید",
    low2: "پایین، بالاتر بخوانید",
    bitHigh: "کمی بالا، پایین‌تر بخوانید",
    high2: "بالا، پایین‌تر بخوانید",
    detail: "{dev} سنت · {hz} هرتز",
    hintDemo: "حالت نمایشی: دکمه را بزنید تا یک خواننده‌ی ساختگی را روی نمودار ببینید.",
    hintVoice: "صدایتان اینجا کشیده می‌شود. یک نت را نگه دارید تا ردیفش روشن شود.",
    hintHeadphones: "با صدای ممتد از هدفون استفاده کنید، وگرنه میکروفون آن را هم می‌شنود.",
    notesView: "نمای نت‌ها",
    curveView: "نمای منحنی",
    couldNotStart: "شروع ممکن نشد: {msg}",
    micInsecure: "میکروفون فقط روی https یا localhost کار می‌کند.",
    micBlocked: "دسترسی به میکروفون بسته است. در تنظیمات Chrome آن را برای این سایت مجاز کنید.",
    micMissing: "میکروفونی پیدا نشد.",
    // song
    songKeyAria: "کوک‌های این آهنگ",
    song: "آهنگ",
    songChartAria: "نت‌های استاد و شما",
    positionAria: "جای فعلی در آهنگ",
    loading: "در حال بارگذاری",
    endOfSong: "پایان آهنگ",
    endOfSongSub: "برای شروع دوباره از اول، پخش را بزنید.",
    listenTeacher: "به استاد گوش کنید",
    listenTeacherSub: "هر وقت خواستید «نوبت من» را بزنید و آنچه شنیدید را بخوانید.",
    fromStart: "از اول",
    play: "پخش",
    playingSub: "«نوبت من» را بزنید و آنچه شنیدید را بخوانید.",
    myTurn: "نوبت من",
    back5: "۵ ثانیه عقب",
    yourTurn: "نوبت شما",
    yourTurnSub: "هر وقت آماده بودید بخوانید.",
    hearAgain: "دوباره بشنو",
    singing: "در حال خواندن",
    singingSub: "وقتی تمام کنید خودش می‌ایستد.",
    notesOnChart: "نت‌های شما روی نمودار است",
    notesOnChartSub: "آبی استاد است، سبز و نارنجی شما.",
    nothingHeard: "صدایی شنیده نشد",
    nothingHeardSub: "دوباره بخوانید یا ادامه دهید.",
    finish: "پایان",
    continue: "ادامه",
    singAgain: "دوباره بخوان",
    keyIsGuess: "کوک استاد فقط یک حدس است. برای تعیین آن روی نام آهنگ بزنید.",
    songMissing: "این فایل دیگر روی این گوشی نیست.",
    songOpenFailed: "باز کردن این فایل ممکن نشد.",
    micStartFailed: "میکروفون روشن نشد: {msg}",
    // song sheet
    teacherKey: "کوک استاد",
    change: "تغییر",
    teacherOctaveAria: "اکتاو استاد",
    iSingIn: "من می‌خوانم در",
    myKeyAria: "کوک من",
    myOctaveAria: "اکتاو من",
    asRecorded: "همان‌طور که ضبط شده",
    myOwnKey: "کوک خودم",
    transposed: "جابه‌جا شده",
    keyFromName: "{key}، از نام فایل.",
    keyByYou: "{key}، انتخاب شما.",
    keyGuess: "{key} فقط یک حدس است. کوکی را که استاد در آن خوانده انتخاب کنید.",
    singSame: "دقیقاً نت‌های استاد را می‌خوانید، از {note}.",
    singOwn: "از {key} می‌خوانید. نت‌های استاد روی نمودار به کوک شما برده می‌شوند.",
    songStart: "شروع آهنگ",
    startWhole: "از همان ابتدا پخش می‌شود. برای رد کردن مقدمه، به جایی بروید که آواز شروع می‌شود (با پخش یا کشیدن نوار) و «شروع از اینجا» را بزنید.",
    startAt: "از {time} فایل شروع می‌شود و قبل از آن رد می‌شود.",
    startHere: "شروع از اینجا ({time})",
    earlier: "۱ ثانیه زودتر",
    later: "۱ ثانیه دیرتر",
    keepWhole: "کل فایل را نگه دار",
    removeSong: "حذف این فایل",
    removeConfirm: "«{name}» از این گوشی حذف شود؟",
    // settings sheet
    yourKey: "کوک شما",
    keyIntro: "نتی که استادتان گفته در آن بخوانید.",
    keyAria: "کوک",
    fineTune: "تنظیم دقیق",
    fineTuneAria: "تنظیم دقیق به سنت",
    fineCents: "{n} سنت",
    keyHz: "{key}{fine}، {hz} هرتز",
    octaveLow: "بم",
    octaveMiddle: "میانه",
    octaveHigh: "زیر",
    dastgah: "دستگاه",
    feedback: "بازخورد",
    feedbackAria: "سطح بازخورد",
    gentle: "ساده",
    plainWords: "با کلمات",
    detailed: "دقیق",
    withCents: "با سنت",
    moreSettings: "تنظیمات بیشتر",
    smoothing: "نرم کردن",
    off: "خاموش",
    light: "کم",
    strong: "زیاد",
    secondsShown: "ثانیه‌های نمایش",
    seconds: "{n} ثانیه",
    micGate: "آستانه‌ی میکروفون",
    micGateAria: "آستانه‌ی میکروفون به دسی‌بل",
    gateHelp: "صداهای آرام‌تر از {db} دسی‌بل نادیده گرفته می‌شوند. در اتاق پرسروصدا آن را بالا ببرید، اگر آواز آرام شنیده نمی‌شود پایین بیاورید.",
    pictureTiming: "زمان‌بندی تصویر",
    pictureTimingAria: "زمان‌بندی تصویر به میلی‌ثانیه",
    syncAhead: "تصویر {ms} میلی‌ثانیه جلو رفته. ",
    syncBack: "تصویر {ms} میلی‌ثانیه عقب رفته. ",
    syncHelp: "برای فایل‌های استاد: اگر نت‌های روی صفحه بعد از صدایی که می‌شنوید می‌آیند، به راست بکشید؛ اگر قبل از آن می‌آیند، به چپ. هدفون بلوتوث معمولاً به این نیاز دارد.",
  },
};

let current = "en";

export const lang = () => current;
export const isRtl = (l = current) => l === "fa";

export function setLang(l) {
  current = l in STRINGS ? l : "en";
}

/** The app starts in Farsi until the singer picks a language in the settings sheet. */
export const DEFAULT_LANG = "fa";

/** Digits in the current language: "3:07" stays, "۳:۰۷" in Farsi. */
export function num(x) {
  const s = String(x);
  if (current !== "fa") return s;
  return s.replace(/[0-9]/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]).replace(/\./g, "٫").replace(/^-/, "−");
}

/** Text for `key`, with {name} placeholders filled from `vars`. Numbers get the language's digits. */
export function t(key, vars = {}) {
  const entry = STRINGS[current][key] ?? STRINGS.en[key] ?? key;
  const shown = Object.fromEntries(Object.entries(vars).map(([k, v]) => [k, typeof v === "number" ? num(v) : v]));
  if (typeof entry === "function") return entry(shown);
  return entry.replace(/\{(\w+)\}/g, (m, k) => (k in shown ? String(shown[k]) : m));
}

/** All keys of a language, for the tests. */
export const keysOf = (l) => Object.keys(STRINGS[l]);

/** Solfege name of note index 0..11: "Re", "ر". */
export const noteName = (index) => (current === "fa" ? SOLFEGE_FA : SOLFEGE)[index];

/** Name of the scale note `cents` above `tonicHz`: "Si koron", "سی کرن". */
export function scaleNoteLabel(tonicHz, cents) {
  const { index, mark } = scaleNote(tonicHz, cents);
  return mark ? `${noteName(index)} ${MARKS[current][mark]}` : noteName(index);
}

/** "Re (D3)", "ر (D3)". The Western name stays in Latin letters. */
export function keyText(hz) {
  const { index, octave } = hzToNote(hz);
  return `${noteName(index)} (${WESTERN[index]}${octave})`;
}

/** "Dashti", "دشتی". Unknown dastgahs keep their own name. */
export function dastgahName(name) {
  if (current === "fa" && DASTGAH_FA[name]) return DASTGAH_FA[name];
  return name.charAt(0).toUpperCase() + name.slice(1);
}

/** Words for a tuneWords() result. */
export function tuneText(tune) {
  if (tune.state === "silent") return t("listening");
  if (tune.state === "in") return t("inTune");
  if (tune.state === "low") return t(tune.bit ? "bitLow" : "low2");
  return t(tune.bit ? "bitHigh" : "high2");
}

// Songs and attempts kept on the phone, in the browser's IndexedDB.
//
// A song is the teacher's original file plus its analyzed pitch curve and the key
// choices for it. Attempts keep my pitch curve for each stretch I sang (no audio),
// for scoring and progress later.

const DB = "avaz";
const VERSION = 1;

let opening = null;

function db() {
  if (!opening) {
    opening = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB, VERSION);
      req.onupgradeneeded = () => {
        const d = req.result;
        d.createObjectStore("songs", { keyPath: "id" });
        const attempts = d.createObjectStore("attempts", { keyPath: "id", autoIncrement: true });
        attempts.createIndex("songId", "songId");
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }
  return opening;
}

async function run(store, mode, fn) {
  const d = await db();
  return new Promise((resolve, reject) => {
    const tx = d.transaction(store, mode);
    const req = fn(tx.objectStore(store));
    tx.oncomplete = () => resolve(req && req.result);
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error || new Error("storage full or blocked"));
  });
}

export const putSong = (song) => run("songs", "readwrite", (s) => s.put(song));
export const getSong = (id) => run("songs", "readonly", (s) => s.get(id));
export const deleteSong = (id) => run("songs", "readwrite", (s) => s.delete(id));

/** All songs without their audio and curves, newest first. */
export async function listSongs() {
  const all = await run("songs", "readonly", (s) => s.getAll());
  return all.map(({ blob, f0, ...rest }) => rest).sort((a, b) => b.added - a.added);
}

/** Change some fields of a song. */
export async function updateSong(id, fields) {
  const song = await getSong(id);
  if (song) await putSong({ ...song, ...fields });
}

export const addAttempt = (attempt) => run("attempts", "readwrite", (s) => s.add(attempt));

export const countAttempts = (songId) =>
  run("attempts", "readonly", (s) => s.index("songId").count(songId));

/** Ask the browser not to clear our storage when the phone runs low on space. */
export function keepStorage() {
  if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});
}

// Progress lives entirely in this browser. Everything that reads or writes it
// goes through here so the shape stays enforceable and a future schema change
// has a version number to migrate from.

const KEY = 'ifr-study.v1';
const VERSION = 1;

const EMPTY = {
  version: VERSION,
  lastPlace: {},   // "ifh:10" -> page within that chapter PDF
  topics: {},      // topic id -> { lastReviewed, reviewCount, checkpoints, notes }
  sessions: [],    // { date, topicIds, completed }
  settings: { staleDays: 30, freshDays: 14 },
};

let state = load();
const listeners = new Set();

function load() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return structuredClone(EMPTY);
    const parsed = JSON.parse(raw);
    if (parsed.version !== VERSION) return structuredClone(EMPTY);
    return { ...structuredClone(EMPTY), ...parsed };
  } catch {
    // private windows and blocked site data both land here
    return structuredClone(EMPTY);
  }
}

function save() {
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // out of quota or storage blocked; the session still works in memory
  }
  listeners.forEach((fn) => fn(state));
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function getState() {
  return state;
}

// ---- reading position -------------------------------------------------

export function placeKey(doc, chapter) {
  return `${doc}:${chapter}`;
}

export function rememberPlace(doc, chapter, page) {
  state.lastPlace[placeKey(doc, chapter)] = page;
  save();
}

export function recallPlace(doc, chapter) {
  return state.lastPlace[placeKey(doc, chapter)] || 1;
}

// ---- topic progress ---------------------------------------------------

export function topicState(id) {
  return state.topics[id] || { lastReviewed: null, reviewCount: 0, checkpoints: {}, notes: '' };
}

export function toggleCheckpoint(id, index, done) {
  const t = { ...topicState(id) };
  t.checkpoints = { ...t.checkpoints, [index]: done };
  state.topics[id] = t;
  save();
}

export function markReviewed(id) {
  const t = { ...topicState(id) };
  t.lastReviewed = new Date().toISOString();
  t.reviewCount = (t.reviewCount || 0) + 1;
  state.topics[id] = t;
  save();
}

export function clearTopic(id) {
  delete state.topics[id];
  save();
}

export function setNotes(id, notes) {
  state.topics[id] = { ...topicState(id), notes };
  save();
}

// ---- freshness --------------------------------------------------------

export function daysSince(iso) {
  if (!iso) return null;
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
}

export function freshness(id) {
  const days = daysSince(topicState(id).lastReviewed);
  if (days === null) return { level: 'never', days: null, label: 'Not reviewed' };
  const { freshDays, staleDays } = state.settings;
  const label = days === 0 ? 'Today' : days === 1 ? 'Yesterday' : `${days} days ago`;
  if (days < freshDays) return { level: 'fresh', days, label };
  if (days < staleDays) return { level: 'aging', days, label };
  return { level: 'stale', days, label };
}

// ---- sessions ---------------------------------------------------------

export function recordSession(topicIds, completed) {
  state.sessions.unshift({ date: new Date().toISOString(), topicIds, completed });
  state.sessions = state.sessions.slice(0, 50);
  save();
}

// ---- export / import --------------------------------------------------
// The answer to "my progress is on the iPad and I'm on the laptop".

export function exportJSON() {
  return JSON.stringify({ ...state, exportedAt: new Date().toISOString() }, null, 2);
}

export function importJSON(text) {
  const incoming = JSON.parse(text);
  if (incoming.version !== VERSION) {
    throw new Error(`That file is version ${incoming.version}, this app reads version ${VERSION}.`);
  }
  // merge rather than replace, keeping whichever review of a topic is newer
  const merged = structuredClone(state);
  Object.assign(merged.lastPlace, incoming.lastPlace || {});
  for (const [id, theirs] of Object.entries(incoming.topics || {})) {
    const mine = merged.topics[id];
    const newer = !mine || !mine.lastReviewed
      || (theirs.lastReviewed && theirs.lastReviewed > mine.lastReviewed);
    merged.topics[id] = newer ? theirs : mine;
  }
  const seen = new Set();
  merged.sessions = [...(incoming.sessions || []), ...merged.sessions]
    .filter((s) => !seen.has(s.date) && seen.add(s.date))
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, 50);
  state = merged;
  save();
}

export function resetAll() {
  state = structuredClone(EMPTY);
  save();
}

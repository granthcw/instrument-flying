// Turns a set of chosen topics into an ordered agenda.

import * as store from './store.js';

// Fundamentals before procedures, so a multi-topic session builds rather than
// jumps around. Topics are authored in this order; the group order is the
// teaching order.
const GROUP_ORDER = [
  'Foundations',
  'Flying the Aircraft',
  'Navigation Systems',
  'Clearances and Departures',
  'En Route',
  'Approaches',
  'Weather and Judgment',
  'Emergencies',
];

export function orderTopics(topics, ids) {
  const wanted = new Set(ids);
  return topics
    .filter((t) => wanted.has(t.id))
    .sort((a, b) => {
      const ga = GROUP_ORDER.indexOf(a.group);
      const gb = GROUP_ORDER.indexOf(b.group);
      if (ga !== gb) return ga - gb;
      return topics.indexOf(a) - topics.indexOf(b);
    });
}

export function estimate(topics) {
  const minutes = topics.reduce((sum, t) => sum + (t.estMinutes || 0), 0);
  const pages = topics.reduce((sum, t) => sum + (t.pageCount || 0), 0);
  return { minutes, pages };
}

export function formatMinutes(total) {
  if (total < 60) return `${total} min`;
  const h = Math.floor(total / 60);
  const m = total % 60;
  return m ? `${h} hr ${m} min` : `${h} hr`;
}

/** Topics never reviewed or past the stale threshold, most overdue first. */
export function dueForReview(topics, limit = 6) {
  return topics
    .map((t) => ({ topic: t, fresh: store.freshness(t.id) }))
    .filter(({ fresh }) => fresh.level === 'never' || fresh.level === 'stale')
    .sort((a, b) => (b.fresh.days ?? Infinity) - (a.fresh.days ?? Infinity))
    .slice(0, limit);
}

export function groupsOf(topics) {
  const map = new Map();
  for (const t of topics) {
    if (!map.has(t.group)) map.set(t.group, []);
    map.get(t.group).push(t);
  }
  return [...map.entries()].sort(
    (a, b) => GROUP_ORDER.indexOf(a[0]) - GROUP_ORDER.indexOf(b[0]),
  );
}

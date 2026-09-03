import * as store from '../store.js';
import { dueForReview, formatMinutes, estimate } from '../session.js';
import { el, topicCard } from './ui.js';

export function render(ctx) {
  const { topics } = ctx.data;
  const due = dueForReview(topics);
  const reviewed = topics.filter((t) => store.topicState(t.id).lastReviewed).length;
  const totalMinutes = estimate(topics).minutes;

  const root = el('div', { class: 'stack' });

  root.append(el('section', { class: 'hero' }, [
    el('h1', {}, ['Build a study session']),
    el('p', { class: 'lede' }, [
      'Pick the topics your next lesson covers and get the pages to read, ',
      'in order, from both handbooks.',
    ]),
    el('div', { class: 'hero-actions' }, [
      el('a', { class: 'btn primary', href: '#/topics' }, ['Choose topics']),
      el('a', { class: 'btn', href: '#/acs' }, ['Start from the ACS']),
      el('a', { class: 'btn', href: '#/browse' }, ['Browse the handbooks']),
    ]),
  ]));

  root.append(el('section', { class: 'stats' }, [
    stat(String(topics.length), 'topics'),
    stat(String(reviewed), 'reviewed at least once'),
    stat(String(due.length), 'due for review'),
    stat(formatMinutes(totalMinutes), 'to cover everything'),
  ]));

  if (due.length) {
    const ids = due.map((d) => d.topic.id);
    root.append(el('section', { class: 'panel' }, [
      el('div', { class: 'panel-head' }, [
        el('h2', {}, ['Due for review']),
        el('a', {
          class: 'btn small primary',
          href: `#/session?topics=${ids.join(',')}`,
        }, ['Review these']),
      ]),
      el('div', { class: 'card-grid' },
        due.map(({ topic }) => topicCard(topic, { href: `#/topic/${topic.id}` }))),
    ]));
  }

  const recent = store.getState().sessions.slice(0, 5);
  if (recent.length) {
    root.append(el('section', { class: 'panel' }, [
      el('h2', {}, ['Recent sessions']),
      el('ul', { class: 'plain-list' }, recent.map((s) => {
        const names = s.topicIds
          .map((id) => topics.find((t) => t.id === id)?.title)
          .filter(Boolean);
        return el('li', {}, [
          el('span', { class: 'when' }, [new Date(s.date).toLocaleDateString(undefined,
            { month: 'short', day: 'numeric' })]),
          el('span', {}, [names.join(', ') || '—']),
          el('a', { class: 'btn tiny', href: `#/session?topics=${s.topicIds.join(',')}` }, ['Repeat']),
        ]);
      })),
    ]));
  }

  return root;
}

function stat(value, label) {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-value' }, [value]),
    el('div', { class: 'stat-label' }, [label]),
  ]);
}

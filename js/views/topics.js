import { el, topicCard } from './ui.js';
import { groupsOf, estimate, formatMinutes, orderTopics } from '../session.js';

export function render(ctx) {
  const { topics } = ctx.data;
  const selected = new Set(ctx.query.get('topics')?.split(',').filter(Boolean) || []);
  let filter = '';

  const root = el('div', { class: 'stack' });
  const list = el('div', { class: 'stack' });
  const bar = el('div', { class: 'sticky-bar' });

  function refreshBar() {
    const chosen = orderTopics(topics, [...selected]);
    const { minutes, pages } = estimate(chosen);
    bar.replaceChildren(
      el('div', { class: 'bar-info' }, [
        el('strong', {}, [`${chosen.length} topic${chosen.length === 1 ? '' : 's'}`]),
        chosen.length ? el('span', {}, [`${formatMinutes(minutes)} · ${pages} pages`]) : el('span', {}, ['Nothing selected yet']),
      ]),
      el('div', { class: 'bar-actions' }, [
        chosen.length ? el('button', {
          class: 'btn', onclick: () => { selected.clear(); draw(); },
        }, ['Clear']) : null,
        el('a', {
          class: `btn primary${chosen.length ? '' : ' disabled'}`,
          href: chosen.length ? `#/session?topics=${[...selected].join(',')}` : '#/topics',
        }, ['Start session']),
      ]),
    );
  }

  function toggle(id, on) {
    if (on) selected.add(id); else selected.delete(id);
    draw();
  }

  function draw() {
    const match = (t) => {
      if (!filter) return true;
      const hay = `${t.title} ${t.summary} ${t.group} ${t.acs.join(' ')} ${t.checkpoints.join(' ')}`.toLowerCase();
      return filter.toLowerCase().split(/\s+/).every((w) => hay.includes(w));
    };
    const shown = topics.filter(match);
    list.replaceChildren(...groupsOf(shown).map(([group, items]) => el('section', { class: 'panel' }, [
      el('div', { class: 'panel-head' }, [
        el('h2', {}, [group]),
        el('button', {
          class: 'btn tiny',
          onclick: () => {
            const allOn = items.every((t) => selected.has(t.id));
            items.forEach((t) => (allOn ? selected.delete(t.id) : selected.add(t.id)));
            draw();
          },
        }, [items.every((t) => selected.has(t.id)) ? 'Deselect group' : 'Select group']),
      ]),
      el('div', { class: 'card-grid' },
        items.map((t) => topicCard(t, { selected: selected.has(t.id), onToggle: toggle }))),
    ])));
    if (!shown.length) list.replaceChildren(el('p', { class: 'empty' }, ['No topics match that search.']));
    refreshBar();
  }

  root.append(
    el('div', { class: 'page-head' }, [
      el('h1', {}, ['Choose topics']),
      el('input', {
        type: 'search', class: 'search', placeholder: 'Search topics, ACS codes, checkpoints…',
        oninput: (e) => { filter = e.target.value; draw(); },
      }),
    ]),
    list,
    bar,
  );
  draw();
  return root;
}

import { el, readingLine, freshnessDot } from './ui.js';
import * as store from '../store.js';

export function render(ctx) {
  const topic = ctx.data.topics.find((t) => t.id === ctx.params.id);
  if (!topic) return el('p', { class: 'empty' }, ['No such topic.']);
  const st = store.topicState(topic.id);
  const f = store.freshness(topic.id);

  return el('div', { class: 'stack' }, [
    el('div', { class: 'page-head' }, [
      el('div', {}, [
        el('div', { class: 'crumb' }, [
          el('a', { href: '#/topics' }, ['Topics']), ' / ', topic.group,
        ]),
        el('h1', {}, [freshnessDot(topic.id), ' ', topic.title]),
        el('p', { class: 'lede' }, [topic.summary]),
      ]),
      el('a', { class: 'btn primary', href: `#/session?topics=${topic.id}` }, ['Study this']),
    ]),

    el('section', { class: 'panel' }, [
      el('h2', {}, ['Reading']),
      el('ul', { class: 'reading-list' }, topic.readings.map((r) => {
        const line = readingLine(ctx.data, r);
        return el('li', {}, [
          el('a', { href: `#/read/${r.doc}/${r.chapter}/${r.startPage}` }, [
            el('strong', {}, [line.label]),
            el('span', { class: 'muted' }, [` — ${line.book} ${line.span} (${r.pages} pages)`]),
          ]),
          r.note ? el('div', { class: 'note' }, [r.note]) : null,
        ]);
      })),
    ]),

    el('section', { class: 'panel' }, [
      el('h2', {}, ['What to know']),
      el('ul', { class: 'checklist' }, topic.checkpoints.map((c, i) => el('li', {}, [
        el('label', {}, [
          el('input', {
            type: 'checkbox', checked: Boolean(st.checkpoints[i]),
            onchange: (e) => store.toggleCheckpoint(topic.id, i, e.target.checked),
          }),
          el('span', {}, [c]),
        ]),
      ]))),
    ]),

    el('section', { class: 'panel' }, [
      el('h2', {}, ['ACS tasks']),
      el('div', { class: 'chips' }, topic.acs.map((code) => {
        const task = ctx.data.acs.areas.flatMap((a) => a.tasks).find((t) => t.code === code);
        return el('a', { class: 'chip', href: '#/acs' }, [`${code} — ${task ? task.title : ''}`]);
      })),
      el('p', { class: 'muted' }, [
        f.level === 'never' ? 'You have not reviewed this topic yet.'
          : `Reviewed ${st.reviewCount} time${st.reviewCount === 1 ? '' : 's'}, most recently ${f.label.toLowerCase()}.`,
      ]),
    ]),
  ]);
}

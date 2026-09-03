// The running study session: agenda on the left, the handbook page itself in
// the middle, and the topic's checkpoints under it.

import { el, readingLine } from './ui.js';
import { orderTopics, estimate, formatMinutes } from '../session.js';
import * as store from '../store.js';
import { Reader } from '../reader.js';

export function render(ctx) {
  const ids = ctx.query.get('topics')?.split(',').filter(Boolean) || [];
  const agenda = orderTopics(ctx.data.topics, ids);
  if (!agenda.length) {
    return el('div', { class: 'stack' }, [
      el('p', { class: 'empty' }, ['That session has no topics. ']),
      el('a', { class: 'btn primary', href: '#/topics' }, ['Choose topics']),
    ]);
  }

  let ti = Math.min(Number(ctx.query.get('t') || 0), agenda.length - 1);
  let ri = Number(ctx.query.get('r') || 0);

  const agendaEl = el('nav', { class: 'agenda' });
  const readerEl = el('div', { class: 'reader' });
  const headEl = el('div', { class: 'reader-head' });
  const checksEl = el('aside', { class: 'checks' });
  const reader = new Reader(readerEl);
  ctx.onLeave(() => reader.destroy());

  function topic() { return agenda[ti]; }
  function reading() { return topic().readings[Math.min(ri, topic().readings.length - 1)]; }

  function go(nextTi, nextRi) {
    ti = Math.max(0, Math.min(nextTi, agenda.length - 1));
    ri = Math.max(0, Math.min(nextRi, agenda[ti].readings.length - 1));
    draw();
  }

  function advance() {
    if (ri + 1 < topic().readings.length) return go(ti, ri + 1);
    store.markReviewed(topic().id);
    if (ti + 1 < agenda.length) return go(ti + 1, 0);
    store.recordSession(ids, true);
    location.hash = '#/';
    return undefined;
  }

  function drawAgenda() {
    const { minutes } = estimate(agenda);
    agendaEl.replaceChildren(
      el('div', { class: 'agenda-head' }, [
        el('h2', {}, ['Session']),
        el('span', { class: 'muted' }, [`${agenda.length} topic${agenda.length === 1 ? '' : 's'} · ${formatMinutes(minutes)}`]),
      ]),
      el('ol', { class: 'agenda-list' }, agenda.map((t, i) => el('li', {
        class: i === ti ? 'current' : (i < ti ? 'done' : ''),
      }, [
        el('button', { class: 'agenda-topic', onclick: () => go(i, 0) }, [t.title]),
        el('ul', { class: 'agenda-readings' }, t.readings.map((r, j) => el('li', {
          class: i === ti && j === ri ? 'current' : '',
        }, [
          el('button', {
            onclick: () => go(i, j),
          }, [readingLine(ctx.data, r).label]),
        ]))),
      ]))),
      el('div', { class: 'agenda-foot' }, [
        el('button', {
          class: 'btn small',
          onclick: () => { store.recordSession(ids, false); location.hash = '#/'; },
        }, ['End session']),
      ]),
    );
  }

  function drawChecks() {
    const t = topic();
    const st = store.topicState(t.id);
    checksEl.replaceChildren(
      el('h3', {}, ['What to know']),
      el('ul', { class: 'checklist' }, t.checkpoints.map((c, i) => el('li', {}, [
        el('label', {}, [
          el('input', {
            type: 'checkbox', checked: Boolean(st.checkpoints[i]),
            onchange: (e) => { store.toggleCheckpoint(t.id, i, e.target.checked); drawChecks(); },
          }),
          el('span', {}, [c]),
        ]),
      ]))),
      el('div', { class: 'checks-foot' }, [
        el('button', { class: 'btn primary', onclick: advance }, [
          ri + 1 < t.readings.length ? 'Next reading'
            : ti + 1 < agenda.length ? 'Mark reviewed & next topic'
              : 'Mark reviewed & finish',
        ]),
      ]),
    );
  }

  function drawHead() {
    const t = topic();
    const r = reading();
    const line = readingLine(ctx.data, r);
    headEl.replaceChildren(
      el('div', {}, [
        el('div', { class: 'crumb' }, [`${t.group} · Topic ${ti + 1} of ${agenda.length}`]),
        el('h1', {}, [t.title]),
        el('p', { class: 'reading-label' }, [
          el('strong', {}, [line.label]),
          el('span', { class: 'muted' }, [` — ${line.book} ${line.span}`]),
          r.note ? el('span', { class: 'note-inline' }, [` ${r.note}`]) : null,
        ]),
      ]),
      el('div', { class: 'reader-nav' }, [
        el('button', { class: 'btn tiny', onclick: () => reader.step(-1), title: 'Previous page' }, ['←']),
        el('span', { class: 'page-indicator' }, ['']),
        el('button', { class: 'btn tiny', onclick: () => reader.step(1), title: 'Next page' }, ['→']),
      ]),
    );
  }

  function draw() {
    drawAgenda();
    drawHead();
    drawChecks();
    const r = reading();
    const part = ctx.data.docs[r.doc].parts.find((p) => p.key === r.chapter);
    reader.onPageChange = (page) => {
      const folio = `${r.chapter}-${page + part.firstFolio - 1}`;
      headEl.querySelector('.page-indicator').textContent = folio;
    };
    reader.show({
      doc: r.doc, chapter: r.chapter, file: part.file,
      startPage: r.startPage, endPage: r.endPage, focus: r.startPage,
    });
  }

  draw();
  return el('div', { class: 'session-layout' }, [
    agendaEl,
    el('main', { class: 'reader-pane' }, [headEl, readerEl]),
    checksEl,
  ]);
}

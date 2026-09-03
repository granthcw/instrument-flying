// The running study session.
//
// Wide screens put the agenda, the handbook page and the checkpoints side by
// side. Below that there is not enough height to give all three a slice and
// still leave the page readable, so the checkpoints become a drawer over the
// reader, and on a phone the session drops the embedded reader entirely and
// leads with what is usable small -- the readings and the checkpoints -- with
// the page one tap away in the full-screen reader.

import { el, readingLine } from './ui.js';
import { orderTopics, estimate, formatMinutes } from '../session.js';
import * as store from '../store.js';
import { Reader } from '../reader.js';

const PHONE = '(max-width: 600px)';

export function render(ctx) {
  const ids = ctx.query.get('topics')?.split(',').filter(Boolean) || [];
  const agenda = orderTopics(ctx.data.topics, ids);
  if (!agenda.length) {
    return el('div', { class: 'stack' }, [
      el('p', { class: 'empty' }, ['That session has no topics.']),
      el('a', { class: 'btn primary', href: '#/topics' }, ['Choose topics']),
    ]);
  }

  const state = {
    ti: Math.min(Number(ctx.query.get('t') || 0), agenda.length - 1),
    ri: Number(ctx.query.get('r') || 0),
  };
  const host = el('div', { class: 'session-host' });
  const phone = window.matchMedia(PHONE);

  const draw = () => {
    const view = phone.matches ? prepMode(ctx, agenda, ids, state, draw)
      : readingMode(ctx, agenda, ids, state, draw);
    host.replaceChildren(view);
    document.body.classList.toggle('wide', !phone.matches);
  };

  const onChange = () => draw();
  phone.addEventListener('change', onChange);
  ctx.onLeave(() => {
    phone.removeEventListener('change', onChange);
    document.body.classList.remove('wide');
  });

  draw();
  return host;
}

// ---------------------------------------------------------------------------
// shared
// ---------------------------------------------------------------------------

function advance(agenda, ids, state, redraw) {
  const topic = agenda[state.ti];
  if (state.ri + 1 < topic.readings.length) {
    state.ri += 1;
    redraw();
    return;
  }
  store.markReviewed(topic.id);
  if (state.ti + 1 < agenda.length) {
    state.ti += 1;
    state.ri = 0;
    redraw();
    return;
  }
  store.recordSession(ids, true);
  location.hash = '#/';
}

function advanceLabel(agenda, state) {
  const topic = agenda[state.ti];
  if (state.ri + 1 < topic.readings.length) return 'Next reading';
  return state.ti + 1 < agenda.length ? 'Mark reviewed & next topic' : 'Mark reviewed & finish';
}

function checklist(topic, redraw) {
  const st = store.topicState(topic.id);
  return el('ul', { class: 'checklist' }, topic.checkpoints.map((c, i) => el('li', {}, [
    el('label', {}, [
      el('input', {
        type: 'checkbox', checked: Boolean(st.checkpoints[i]),
        onchange: (e) => { store.toggleCheckpoint(topic.id, i, e.target.checked); redraw?.(); },
      }),
      el('span', {}, [c]),
    ]),
  ])));
}

function checkedCount(topic) {
  const st = store.topicState(topic.id);
  return Object.values(st.checkpoints || {}).filter(Boolean).length;
}

function agendaNav(ctx, agenda, ids, state, redraw) {
  const { minutes } = estimate(agenda);
  return [
    el('div', { class: 'agenda-head' }, [
      el('h2', {}, ['Session']),
      el('span', { class: 'muted' }, [
        `${agenda.length} topic${agenda.length === 1 ? '' : 's'} · ${formatMinutes(minutes)}`,
      ]),
    ]),
    el('ol', { class: 'agenda-list' }, agenda.map((t, i) => el('li', {
      class: i === state.ti ? 'current' : (i < state.ti ? 'done' : ''),
    }, [
      el('button', {
        class: 'agenda-topic',
        onclick: () => { state.ti = i; state.ri = 0; redraw(); },
      }, [t.title]),
      el('ul', { class: 'agenda-readings' }, t.readings.map((r, j) => el('li', {
        class: i === state.ti && j === state.ri ? 'current' : '',
      }, [
        el('button', {
          onclick: () => { state.ti = i; state.ri = j; redraw(); },
        }, [readingLine(ctx.data, r).label]),
      ]))),
    ]))),
    el('div', { class: 'agenda-foot' }, [
      el('button', {
        class: 'btn small',
        onclick: () => { store.recordSession(ids, false); location.hash = '#/'; },
      }, ['End session']),
    ]),
  ];
}

// ---------------------------------------------------------------------------
// phone: prep mode, no embedded reader
// ---------------------------------------------------------------------------

function prepMode(ctx, agenda, ids, state, redraw) {
  const topic = agenda[state.ti];
  const done = checkedCount(topic);

  return el('div', { class: 'prep' }, [
    el('div', { class: 'prep-head' }, [
      el('div', { class: 'prep-crumb' }, [
        el('button', {
          class: 'btn tiny', disabled: state.ti === 0,
          onclick: () => { state.ti -= 1; state.ri = 0; redraw(); },
        }, ['←']),
        el('span', {}, [`Topic ${state.ti + 1} of ${agenda.length}`]),
        el('button', {
          class: 'btn tiny', disabled: state.ti === agenda.length - 1,
          onclick: () => { state.ti += 1; state.ri = 0; redraw(); },
        }, ['→']),
      ]),
      el('h1', {}, [topic.title]),
      el('p', { class: 'lede' }, [topic.summary]),
    ]),

    el('section', { class: 'panel' }, [
      el('h2', {}, ['Reading']),
      el('ul', { class: 'reading-list' }, topic.readings.map((r, j) => {
        const line = readingLine(ctx.data, r);
        return el('li', {}, [
          el('a', {
            class: 'reading-row',
            href: `#/read/${r.doc}/${r.chapter}/${r.startPage}`
              + `?back=session&topics=${ids.join(',')}&t=${state.ti}&r=${j}`,
          }, [
            el('span', { class: 'reading-main' }, [
              el('strong', {}, [line.label]),
              el('span', { class: 'muted' }, [`${line.book} ${line.span} · ${r.pages} pages`]),
              r.note ? el('span', { class: 'note' }, [r.note]) : null,
            ]),
            el('span', { class: 'reading-go' }, ['Read']),
          ]),
        ]);
      })),
    ]),

    el('section', { class: 'panel' }, [
      el('div', { class: 'panel-head' }, [
        el('h2', {}, ['What to know']),
        el('span', { class: 'muted' }, [`${done} of ${topic.checkpoints.length}`]),
      ]),
      checklist(topic, redraw),
    ]),

    el('details', { class: 'panel prep-agenda' }, [
      el('summary', {}, [`Session — ${agenda.length} topics`]),
      el('div', { class: 'agenda' }, agendaNav(ctx, agenda, ids, state, redraw)),
    ]),

    el('div', { class: 'sticky-bar' }, [
      el('button', {
        class: 'btn primary wide-btn',
        onclick: () => advance(agenda, ids, state, redraw),
      }, [advanceLabel(agenda, state)]),
    ]),
  ]);
}

// ---------------------------------------------------------------------------
// tablet and desktop: the page is the point
// ---------------------------------------------------------------------------

function readingMode(ctx, agenda, ids, state, redraw) {
  const topic = agenda[state.ti];
  const reading = topic.readings[Math.min(state.ri, topic.readings.length - 1)];
  const line = readingLine(ctx.data, reading);
  const part = ctx.data.docs[reading.doc].parts.find((p) => p.key === reading.chapter);

  const readerEl = el('div', { class: 'reader' });
  const reader = new Reader(readerEl);
  ctx.onLeave(() => reader.destroy());

  const indicator = el('span', { class: 'page-indicator' });
  reader.onPageChange = (page) => {
    indicator.textContent = `${reading.chapter}-${page + part.firstFolio - 1}`;
  };
  reader.show({
    doc: reading.doc, chapter: reading.chapter, file: part.file,
    startPage: reading.startPage, endPage: reading.endPage, focus: reading.startPage,
  });

  const drawer = el('aside', { class: 'checks' }, [
    el('button', {
      class: 'checks-handle',
      onclick: (e) => e.currentTarget.parentElement.classList.toggle('open'),
    }, [
      el('span', {}, ['What to know']),
      el('span', { class: 'muted' }, [
        `${checkedCount(topic)} of ${topic.checkpoints.length}`,
      ]),
    ]),
    el('div', { class: 'checks-body' }, [
      checklist(topic, null),
      el('div', { class: 'checks-foot' }, [
        el('button', {
          class: 'btn primary',
          onclick: () => advance(agenda, ids, state, redraw),
        }, [advanceLabel(agenda, state)]),
      ]),
    ]),
  ]);

  return el('div', { class: 'session-layout' }, [
    el('nav', { class: 'agenda' }, agendaNav(ctx, agenda, ids, state, redraw)),
    el('main', { class: 'reader-pane' }, [
      el('div', { class: 'reader-head' }, [
        el('div', { class: 'reader-head-text' }, [
          el('div', { class: 'crumb' }, [`${topic.group} · Topic ${state.ti + 1} of ${agenda.length}`]),
          el('h1', {}, [topic.title]),
          el('p', { class: 'reading-label' }, [
            el('strong', {}, [line.label]),
            el('span', { class: 'muted' }, [` — ${line.book} ${line.span}`]),
            reading.note ? el('span', { class: 'note-inline' }, [` · ${reading.note}`]) : null,
          ]),
        ]),
        el('div', { class: 'reader-nav' }, [
          el('button', { class: 'btn tiny', onclick: () => reader.step(-1), title: 'Previous page' }, ['←']),
          indicator,
          el('button', { class: 'btn tiny', onclick: () => reader.step(1), title: 'Next page' }, ['→']),
        ]),
      ]),
      readerEl,
    ]),
    drawer,
  ]);
}

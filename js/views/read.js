// Full-screen reader: one chapter, opened at a page.
//
// This is the phone's reading surface as well as the Browse reader, so it
// carries the zoom control -- at fit-width a handbook page renders its 9pt
// text around 5px tall on a phone, which no amount of layout fixes.

import { el } from './ui.js';
import * as store from '../store.js';
import { Reader, ZOOM_STEPS } from '../reader.js';

export function render(ctx) {
  const { doc, chapter, page } = ctx.params;
  const meta = ctx.data.docs[doc];
  const isACS = doc === 'acs';
  const part = isACS ? null : meta?.parts.find((p) => p.key === chapter);
  if (!isACS && !part) return el('p', { class: 'empty' }, ['No such chapter.']);

  const readerEl = el('div', { class: 'reader' });
  const reader = new Reader(readerEl);
  ctx.onLeave(() => reader.destroy());

  const indicator = el('span', { class: 'page-indicator' });
  reader.onPageChange = (n) => {
    indicator.textContent = part ? `${chapter}-${n + part.firstFolio - 1}` : `p${n}`;
  };

  reader.show({
    doc, chapter, file: isACS ? ctx.data.acs.file : part.file,
    focus: Number(page) || (isACS ? 1 : store.recallPlace(doc, chapter)),
  });

  // Coming from a phone session, going back returns to that topic and reading.
  const back = ctx.query.get('back') === 'session'
    ? `#/session?topics=${ctx.query.get('topics') || ''}`
      + `&t=${ctx.query.get('t') || 0}&r=${ctx.query.get('r') || 0}`
    : (isACS ? '#/acs' : '#/browse');

  const zoomLabel = el('span', { class: 'zoom-label' }, [`${Math.round(reader.zoom * 100)}%`]);
  reader.onZoomChange = (z) => { zoomLabel.textContent = `${Math.round(z * 100)}%`; };

  const chrome = el('div', { class: 'reader-head compact' }, [
    el('a', { class: 'btn tiny', href: back }, ['←']),
    el('div', { class: 'reader-head-text' }, [
      el('h1', {}, [isACS ? ctx.data.acs.title : part.title]),
      el('span', { class: 'muted' }, [isACS ? ctx.data.acs.code : meta.code]),
    ]),
    el('div', { class: 'reader-nav' }, [
      el('button', {
        class: 'btn tiny', title: 'Zoom out',
        onclick: () => reader.stepZoom(-1),
      }, ['−']),
      zoomLabel,
      el('button', {
        class: 'btn tiny', title: 'Zoom in',
        onclick: () => reader.stepZoom(1),
      }, ['+']),
      indicator,
    ]),
  ]);

  const sections = isACS ? [] : ctx.data.outline[doc].filter((s) => s.chapter === chapter);
  const contents = sections.length ? el('nav', { class: 'agenda' }, [
    el('div', { class: 'agenda-head' }, [
      el('h2', {}, [part.title]),
      el('span', { class: 'muted' }, [`${meta.code} · ${part.pages} pages`]),
    ]),
    el('ul', { class: 'toc scrollable' }, sections.map((s) => el('li', { class: `depth-${s.depth}` }, [
      el('button', {
        onclick: () => {
          reader.goTo(s.page);
          document.querySelector('.read-layout')?.classList.remove('contents-open');
        },
      }, [s.title]),
      el('span', { class: 'folio' }, [s.folio]),
    ]))),
    el('div', { class: 'agenda-foot' }, [
      el('a', { class: 'btn small', href: back }, ['Back']),
    ]),
  ]) : null;

  const layout = el('div', {
    class: `read-layout${contents ? '' : ' single'}`,
  }, [
    contents,
    el('main', { class: 'reader-pane' }, [chrome, readerEl]),
    contents ? el('button', {
      class: 'contents-toggle',
      onclick: () => layoutToggle(),
    }, ['Contents']) : null,
  ]);

  function layoutToggle() {
    layout.classList.toggle('contents-open');
  }

  // The full-screen reader is exactly that: the app's own top bar is hidden
  // and the compact head carries the back button, so the page gets the screen.
  document.body.classList.add('wide', 'reading');
  ctx.onLeave(() => document.body.classList.remove('wide', 'reading'));

  // The head slides away as you read down and comes back the moment you
  // scroll up or reach the top, the way Safari's own chrome behaves.
  let lastY = 0;
  let userDriven = false;
  // Opening at a page scrolls the pane, and each lazily rendered canvas
  // shifts it again. Neither is the reader scrolling away, so the head only
  // reacts once the scrolling is actually coming from the person reading.
  for (const ev of ['wheel', 'touchmove', 'keydown']) {
    readerEl.addEventListener(ev, () => { userDriven = true; }, { passive: true });
  }
  readerEl.addEventListener('scroll', () => {
    const y = readerEl.scrollTop;
    if (!userDriven) { lastY = y; return; }
    if (y < 40 || y < lastY - 6) layout.classList.remove('head-hidden');
    else if (y > lastY + 6) layout.classList.add('head-hidden');
    lastY = y;
  }, { passive: true });

  return layout;
}

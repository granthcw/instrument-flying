// Plain reader: one chapter, opened at a page, for browsing outside a session.

import { el } from './ui.js';
import * as store from '../store.js';
import { Reader } from '../reader.js';

export function render(ctx) {
  const { doc, chapter, page } = ctx.params;
  if (doc === 'acs') return acsReader(ctx, Number(page) || 1);

  const meta = ctx.data.docs[doc];
  const part = meta?.parts.find((p) => p.key === chapter);
  if (!part) return el('p', { class: 'empty' }, ['No such chapter.']);

  const readerEl = el('div', { class: 'reader' });
  const reader = new Reader(readerEl);
  ctx.onLeave(() => reader.destroy());

  const indicator = el('span', { class: 'page-indicator' });
  const sections = ctx.data.outline[doc].filter((s) => s.chapter === chapter);

  reader.onPageChange = (n) => {
    indicator.textContent = `${chapter}-${n + part.firstFolio - 1}`;
  };
  reader.show({
    doc, chapter, file: part.file, focus: Number(page) || store.recallPlace(doc, chapter),
  });

  return el('div', { class: 'read-layout' }, [
    el('nav', { class: 'agenda' }, [
      el('div', { class: 'agenda-head' }, [
        el('h2', {}, [part.title]),
        el('span', { class: 'muted' }, [`${meta.code} · ${part.pages} pages`]),
      ]),
      el('ul', { class: 'toc scrollable' }, sections.map((s) => el('li', { class: `depth-${s.depth}` }, [
        el('button', { onclick: () => reader.goTo(s.page) }, [s.title]),
        el('span', { class: 'folio' }, [s.folio]),
      ]))),
      el('div', { class: 'agenda-foot' }, [
        el('a', { class: 'btn small', href: '#/browse' }, ['Back to browse']),
      ]),
    ]),
    el('main', { class: 'reader-pane' }, [
      el('div', { class: 'reader-head' }, [
        el('div', {}, [
          el('div', { class: 'crumb' }, [meta.title]),
          el('h1', {}, [part.title]),
        ]),
        el('div', { class: 'reader-nav' }, [
          el('button', { class: 'btn tiny', onclick: () => reader.step(-1) }, ['←']),
          indicator,
          el('button', { class: 'btn tiny', onclick: () => reader.step(1) }, ['→']),
        ]),
      ]),
      readerEl,
    ]),
  ]);
}

function acsReader(ctx, page) {
  const readerEl = el('div', { class: 'reader' });
  const reader = new Reader(readerEl);
  ctx.onLeave(() => reader.destroy());
  reader.show({ doc: 'acs', chapter: 'acs', file: ctx.data.acs.file, focus: page });
  return el('div', { class: 'read-layout single' }, [
    el('main', { class: 'reader-pane' }, [
      el('div', { class: 'reader-head' }, [
        el('div', {}, [
          el('div', { class: 'crumb' }, [el('a', { href: '#/acs' }, ['ACS'])]),
          el('h1', {}, [ctx.data.acs.title]),
        ]),
        el('div', { class: 'reader-nav' }, [
          el('button', { class: 'btn tiny', onclick: () => reader.step(-1) }, ['←']),
          el('button', { class: 'btn tiny', onclick: () => reader.step(1) }, ['→']),
        ]),
      ]),
      readerEl,
    ]),
  ]);
}

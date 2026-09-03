import { el } from './ui.js';
import * as store from '../store.js';

export function render(ctx) {
  const { docs, outline } = ctx.data;
  const root = el('div', { class: 'stack' });
  let filter = '';
  const list = el('div', { class: 'stack' });

  function draw() {
    const needle = filter.trim().toLowerCase();
    list.replaceChildren(...Object.entries(docs).map(([doc, meta]) => el('section', { class: 'panel' }, [
      el('div', { class: 'panel-head' }, [
        el('h2', {}, [meta.title]),
        el('span', { class: 'muted' }, [meta.code]),
      ]),
      el('div', { class: 'stack tight' }, meta.parts.map((part) => {
        const sections = outline[doc].filter((s) => s.chapter === part.key
          && (!needle || s.title.toLowerCase().includes(needle)));
        if (needle && !sections.length) return null;
        const place = store.recallPlace(doc, part.key);
        return el('details', { class: 'chapter', open: Boolean(needle) }, [
          el('summary', {}, [
            el('span', { class: 'chapter-title' }, [part.title]),
            el('span', { class: 'muted' }, [`${part.pages} pages`]),
            place > 1 ? el('span', { class: 'resume-chip' }, [`resume p${place}`]) : null,
          ]),
          el('div', { class: 'chapter-body' }, [
            el('a', {
              class: 'btn tiny', href: `#/read/${doc}/${part.key}/${place}`,
            }, [place > 1 ? `Resume at page ${place}` : 'Open chapter']),
            el('ul', { class: 'toc' }, sections.map((s) => el('li', {
              class: `depth-${s.depth}`,
            }, [
              el('a', { href: `#/read/${doc}/${part.key}/${s.page}` }, [s.title]),
              el('span', { class: 'folio' }, [s.folio]),
            ]))),
          ]),
        ]);
      })),
    ])));
  }

  root.append(
    el('div', { class: 'page-head' }, [
      el('h1', {}, ['Browse the handbooks']),
      el('input', {
        type: 'search', class: 'search', placeholder: 'Find a section…',
        oninput: (e) => { filter = e.target.value; draw(); },
      }),
    ]),
    list,
  );
  draw();
  return root;
}

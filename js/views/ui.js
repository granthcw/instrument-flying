// Small DOM helpers shared by the views.

import * as store from '../store.js';

export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? '' : String(v));
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function freshnessDot(id) {
  const f = store.freshness(id);
  return el('span', {
    class: `dot ${f.level}`,
    title: f.level === 'never' ? 'Not reviewed yet' : `Last reviewed ${f.label.toLowerCase()}`,
  });
}

export function topicCard(topic, { href, selected, onToggle } = {}) {
  const f = store.freshness(topic.id);
  const done = Object.values(store.topicState(topic.id).checkpoints || {}).filter(Boolean).length;
  const body = [
    el('div', { class: 'card-head' }, [
      freshnessDot(topic.id),
      el('h3', {}, [topic.title]),
    ]),
    el('p', { class: 'card-summary' }, [topic.summary]),
    el('div', { class: 'card-meta' }, [
      el('span', {}, [`${topic.estMinutes} min`]),
      el('span', {}, [`${topic.pageCount} pages`]),
      topic.acs.length ? el('span', { class: 'acs-chip' }, [topic.acs.join(' · ')]) : null,
      done ? el('span', { class: 'done-chip' }, [`${done}/${topic.checkpoints.length} checked`]) : null,
      el('span', { class: `fresh-chip ${f.level}` }, [f.label]),
    ]),
  ];
  if (onToggle) {
    return el('label', { class: `card selectable${selected ? ' selected' : ''}` }, [
      el('input', {
        type: 'checkbox', class: 'card-check', checked: selected || false,
        onchange: (e) => onToggle(topic.id, e.target.checked),
      }),
      el('div', { class: 'card-body' }, body),
    ]);
  }
  return el('a', { class: 'card', href: href || '#' }, [el('div', { class: 'card-body' }, body)]);
}

export function docLabel(data, doc) {
  return data.docs[doc]?.title || doc;
}

export function chapterOf(data, doc, chapter) {
  return data.docs[doc]?.parts.find((p) => p.key === chapter);
}

export function readingLine(data, reading) {
  const part = chapterOf(data, reading.doc, reading.chapter);
  const span = reading.folio === reading.folioEnd
    ? reading.folio
    : `${reading.folio} to ${reading.folioEnd}`;
  return {
    part,
    span,
    book: data.docs[reading.doc].code,
    label: reading.title,
  };
}

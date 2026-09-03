import { el, freshnessDot } from './ui.js';
import * as store from '../store.js';
import { groupsOf } from '../session.js';

export function render(ctx) {
  const { topics } = ctx.data;
  const status = el('p', { class: 'muted' });

  function download() {
    const blob = new Blob([store.exportJSON()], { type: 'application/json' });
    const a = el('a', {
      href: URL.createObjectURL(blob),
      download: `ifr-study-progress-${new Date().toISOString().slice(0, 10)}.json`,
    });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  async function upload(file) {
    try {
      store.importJSON(await file.text());
      status.textContent = 'Progress merged. Newer reviews win where both files have a topic.';
      status.className = 'muted ok';
    } catch (err) {
      status.textContent = `Could not import: ${err.message}`;
      status.className = 'muted error';
    }
  }

  const reviewed = topics.filter((t) => store.topicState(t.id).lastReviewed);

  return el('div', { class: 'stack' }, [
    el('div', { class: 'page-head' }, [el('h1', {}, ['Progress'])]),

    el('section', { class: 'panel' }, [
      el('h2', {}, ['Move progress between devices']),
      el('p', { class: 'lede' }, [
        'Progress is stored in this browser only. Export it here and import ',
        'the file on your other device.',
      ]),
      el('div', { class: 'hero-actions' }, [
        el('button', { class: 'btn primary', onclick: download }, ['Export progress']),
        el('label', { class: 'btn' }, [
          'Import progress',
          el('input', {
            type: 'file', accept: 'application/json,.json', hidden: true,
            onchange: (e) => e.target.files[0] && upload(e.target.files[0]),
          }),
        ]),
        el('button', {
          class: 'btn danger',
          onclick: () => {
            if (confirm('Clear all review history and reading positions on this device?')) {
              store.resetAll();
              status.textContent = 'Cleared.';
            }
          },
        }, ['Reset']),
      ]),
      status,
    ]),

    el('section', { class: 'panel' }, [
      el('div', { class: 'panel-head' }, [
        el('h2', {}, ['Review history']),
        el('span', { class: 'muted' }, [`${reviewed.length} of ${topics.length} topics reviewed`]),
      ]),
      ...groupsOf(topics).map(([group, items]) => el('div', { class: 'progress-group' }, [
        el('h3', {}, [group]),
        el('ul', { class: 'progress-list' }, items.map((t) => {
          const st = store.topicState(t.id);
          const f = store.freshness(t.id);
          const done = Object.values(st.checkpoints || {}).filter(Boolean).length;
          return el('li', {}, [
            freshnessDot(t.id),
            el('a', { href: `#/topic/${t.id}` }, [t.title]),
            el('span', { class: 'spacer' }),
            done ? el('span', { class: 'muted' }, [`${done}/${t.checkpoints.length}`]) : null,
            el('span', { class: `fresh-chip ${f.level}` }, [f.label]),
          ]);
        })),
      ])),
    ]),
  ]);
}

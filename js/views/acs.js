import { el } from './ui.js';

const KIND = { K: 'Knowledge', R: 'Risk Management', S: 'Skills' };

export function render(ctx) {
  const { acs, topics } = ctx.data;
  const selected = new Set();
  const root = el('div', { class: 'stack' });
  const list = el('div', { class: 'stack' });
  const bar = el('div', { class: 'sticky-bar' });

  const topicsFor = (code) => topics.filter((t) => t.acs.includes(code));

  function refreshBar() {
    const ids = new Set();
    selected.forEach((code) => topicsFor(code).forEach((t) => ids.add(t.id)));
    bar.replaceChildren(
      el('div', { class: 'bar-info' }, [
        el('strong', {}, [`${selected.size} task${selected.size === 1 ? '' : 's'}`]),
        el('span', {}, [ids.size ? `${ids.size} topics to review` : 'Select tasks to build a session']),
      ]),
      el('div', { class: 'bar-actions' }, [
        selected.size ? el('button', { class: 'btn', onclick: () => { selected.clear(); draw(); } }, ['Clear']) : null,
        el('a', {
          class: `btn primary${ids.size ? '' : ' disabled'}`,
          href: ids.size ? `#/session?topics=${[...ids].join(',')}` : '#/acs',
        }, ['Start session']),
      ]),
    );
  }

  function draw() {
    list.replaceChildren(...acs.areas.map((area) => el('section', { class: 'panel' }, [
      el('h2', {}, [`Area ${area.num}. ${area.title}`]),
      el('div', { class: 'stack tight' }, area.tasks.map((task) => {
        const related = topicsFor(task.code);
        const open = selected.has(task.code);
        return el('div', { class: `task${open ? ' selected' : ''}` }, [
          el('div', { class: 'task-head' }, [
            el('label', { class: 'task-title' }, [
              el('input', {
                type: 'checkbox', checked: open,
                onchange: (e) => {
                  if (e.target.checked) selected.add(task.code); else selected.delete(task.code);
                  draw();
                },
              }),
              el('code', { class: 'task-code' }, [task.code]),
              el('span', {}, [task.title]),
            ]),
            el('a', {
              class: 'btn tiny',
              href: `#/read/acs/acs/${task.page}`,
            }, ['Open in ACS']),
          ]),
          el('div', { class: 'task-body' }, [
            ...Object.entries(KIND).map(([kind, label]) => {
              const items = task.elements[kind];
              if (!items.length) return null;
              return el('div', { class: 'elements' }, [
                el('h4', {}, [label]),
                el('ul', {}, items.map((e) => el('li', {}, [
                  el('code', {}, [e.code.split('.').slice(3).join('.')]),
                  ' ', e.text,
                ]))),
              ]);
            }),
            related.length ? el('div', { class: 'related' }, [
              el('h4', {}, ['Study topics']),
              el('div', { class: 'chips' }, related.map((t) => el('a', {
                class: 'chip', href: `#/topic/${t.id}`,
              }, [t.title]))),
            ]) : el('p', { class: 'empty' }, ['No topic maps to this task yet.']),
          ]),
        ]);
      })),
    ])));
    refreshBar();
  }

  root.append(
    el('div', { class: 'page-head' }, [
      el('h1', {}, ['Airman Certification Standards']),
      el('p', { class: 'lede' }, [`${acs.title} (${acs.code})`]),
    ]),
    list,
    bar,
  );
  draw();
  return root;
}

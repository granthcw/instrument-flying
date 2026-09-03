// Hash router and app shell. No build step: these are plain ES modules.

import * as home from './views/home.js';
import * as topicsView from './views/topics.js';
import * as topicView from './views/topic.js';
import * as acsView from './views/acs.js';
import * as browseView from './views/browse.js';
import * as sessionView from './views/session.js';
import * as readView from './views/read.js';
import * as progressView from './views/progress.js';
import { el } from './views/ui.js';

const ROUTES = [
  [/^\/?$/, home],
  [/^\/topics$/, topicsView],
  [/^\/topic\/([\w-]+)$/, topicView, ['id']],
  [/^\/acs$/, acsView],
  [/^\/browse$/, browseView],
  [/^\/session$/, sessionView],
  [/^\/read\/(\w+)\/([\w]+)\/(\d+)$/, readView, ['doc', 'chapter', 'page']],
  [/^\/progress$/, progressView],
];

const NAV = [
  ['#/', 'Home'],
  ['#/topics', 'Topics'],
  ['#/acs', 'ACS'],
  ['#/browse', 'Browse'],
  ['#/progress', 'Progress'],
];

let data = null;
let leaveHandlers = [];

async function loadData() {
  const [docs, outline, acs, topics] = await Promise.all([
    fetch('data/docs.json').then((r) => r.json()),
    fetch('data/outline.json').then((r) => r.json()),
    fetch('data/acs.json').then((r) => r.json()),
    fetch('data/topics.built.json').then((r) => r.json()),
  ]);
  return { docs, outline, acs, topics };
}

function parseHash() {
  const raw = location.hash.replace(/^#/, '') || '/';
  const [path, search = ''] = raw.split('?');
  return { path, query: new URLSearchParams(search) };
}

function route() {
  const { path, query } = parseHash();
  const outlet = document.getElementById('outlet');

  leaveHandlers.forEach((fn) => fn());
  leaveHandlers = [];

  for (const [pattern, view, names = []] of ROUTES) {
    const match = path.match(pattern);
    if (!match) continue;
    const params = {};
    names.forEach((n, i) => { params[n] = match[i + 1]; });
    const ctx = { data, params, query, onLeave: (fn) => leaveHandlers.push(fn) };
    document.body.classList.remove('wide');
    outlet.replaceChildren(view.render(ctx));
    window.scrollTo(0, 0);
    highlight(path);
    return;
  }
  outlet.replaceChildren(el('p', { class: 'empty' }, ['Page not found.']));
}

function highlight(path) {
  document.querySelectorAll('#nav a').forEach((a) => {
    const target = a.getAttribute('href').replace(/^#/, '');
    a.classList.toggle('active', target === path || (target !== '/' && path.startsWith(target)));
  });
}

function shell() {
  document.getElementById('nav').replaceChildren(
    ...NAV.map(([href, label]) => el('a', { href }, [label])),
  );
}

(async function start() {
  try {
    data = await loadData();
  } catch (err) {
    document.getElementById('outlet').replaceChildren(
      el('p', { class: 'empty error' }, [
        `Could not load the study data (${err.message}). `,
        'If you opened this file directly, serve the folder over HTTP instead.',
      ]),
    );
    return;
  }
  shell();
  window.addEventListener('hashchange', route);
  route();
}());

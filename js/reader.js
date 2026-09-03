// PDF.js wrapper. Renders a range of pages from one chapter file into a
// scrolling column, remembers where you stopped, and can jump to a page.
//
// The chapter PDFs are served same-origin: faa.gov sends no CORS headers, so
// fetching the originals from there would fail.

import * as store from './store.js';

const PDFJS_BASE = 'vendor/pdfjs/';
let pdfjsLib = null;

async function lib() {
  if (!pdfjsLib) {
    pdfjsLib = await import(`../${PDFJS_BASE}pdf.min.mjs`);
    pdfjsLib.GlobalWorkerOptions.workerSrc = `${PDFJS_BASE}pdf.worker.min.mjs`;
  }
  return pdfjsLib;
}

const docCache = new Map();

async function open(url) {
  if (!docCache.has(url)) {
    const pdfjs = await lib();
    docCache.set(url, pdfjs.getDocument({
      url,
      cMapUrl: `${PDFJS_BASE}cmaps/`,
      cMapPacked: true,
      standardFontDataUrl: `${PDFJS_BASE}standard_fonts/`,
    }).promise);
  }
  return docCache.get(url);
}

export class Reader {
  constructor(container) {
    this.el = container;
    this.pages = new Map();
    this.token = 0;
    this.onPageChange = null;
    this._observer = null;
  }

  /** Render pages [start..end] of a chapter, scrolled to `focus`. */
  async show({ doc, chapter, file, startPage, endPage, focus }) {
    const token = ++this.token;
    this.doc = doc;
    this.chapter = chapter;
    this.el.innerHTML = '<p class="reader-status">Loading…</p>';

    let pdf;
    try {
      pdf = await open(file);
    } catch (err) {
      this.el.innerHTML = `<p class="reader-status error">Could not open ${file}. ${err.message}</p>`;
      return;
    }
    if (token !== this.token) return;

    const first = Math.max(1, startPage || 1);
    const last = Math.min(pdf.numPages, endPage || pdf.numPages);
    this.range = { first, last };
    this.el.innerHTML = '';
    this.pages.clear();

    // Placeholders first so the scroll height is right immediately; each page
    // renders when it comes near the viewport.
    for (let n = first; n <= last; n += 1) {
      const holder = document.createElement('div');
      holder.className = 'pdf-page';
      holder.dataset.page = String(n);
      holder.innerHTML = `<div class="pdf-page-label">Page ${n} of ${pdf.numPages}</div>`;
      this.el.append(holder);
      this.pages.set(n, { holder, rendered: false });
    }

    this._watch(pdf, token);
    const target = Math.min(Math.max(focus || first, first), last);
    await this._render(pdf, target, token);
    this.goTo(target, 'auto');
  }

  _watch(pdf, token) {
    this._observer?.disconnect();
    this._observer = new IntersectionObserver((entries) => {
      if (token !== this.token) return;
      for (const entry of entries) {
        const n = Number(entry.target.dataset.page);
        if (entry.isIntersecting) {
          this._render(pdf, n, token);
          if (entry.intersectionRatio > 0.5) this._settleOn(n);
        }
      }
    }, { root: this.el, rootMargin: '200% 0px', threshold: [0, 0.5] });
    this.pages.forEach(({ holder }) => this._observer.observe(holder));
  }

  _settleOn(page) {
    if (this.current === page) return;
    this.current = page;
    if (this.doc && this.chapter) store.rememberPlace(this.doc, this.chapter, page);
    this.onPageChange?.(page);
  }

  async _render(pdf, n, token) {
    const entry = this.pages.get(n);
    if (!entry || entry.rendered) return;
    entry.rendered = true;
    const page = await pdf.getPage(n);
    if (token !== this.token) return;

    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d', { alpha: false });
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const width = entry.holder.clientWidth || this.el.clientWidth || 800;
    const base = page.getViewport({ scale: 1 });
    const scale = width / base.width;
    const viewport = page.getViewport({ scale: scale * dpr });

    canvas.width = Math.floor(viewport.width);
    canvas.height = Math.floor(viewport.height);
    canvas.style.width = '100%';
    canvas.style.aspectRatio = `${base.width} / ${base.height}`;
    entry.holder.prepend(canvas);
    entry.holder.classList.add('rendered');
    await page.render({ canvasContext: ctx, viewport }).promise;
  }

  goTo(page, behavior = 'smooth') {
    const entry = this.pages.get(page);
    if (!entry) return;
    entry.holder.scrollIntoView({ behavior, block: 'start' });
    this._settleOn(page);
  }

  step(delta) {
    if (!this.range) return;
    const next = Math.min(this.range.last, Math.max(this.range.first, (this.current || this.range.first) + delta));
    this.goTo(next);
  }

  destroy() {
    this.token += 1;
    this._observer?.disconnect();
    this.el.innerHTML = '';
  }
}

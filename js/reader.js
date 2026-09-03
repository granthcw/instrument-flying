// PDF.js wrapper. Renders a range of pages from one chapter file into a
// scrolling column, remembers where you stopped, and can jump to a page.
//
// The chapter PDFs are served same-origin: faa.gov sends no CORS headers, so
// fetching the originals from there would fail.

import * as store from './store.js';

const PDFJS_BASE = 'vendor/pdfjs/';

// A handbook page is two columns of 9pt text. At phone width that renders
// around 5px tall, so zooming past fit-width is the only way to read it -- and
// re-rendering rather than scaling up is what keeps it sharp.
export const ZOOM_STEPS = [1, 1.5, 2, 2.5, 3];

// Mobile Safari kills a tab that allocates too much canvas. A 3x zoom at
// devicePixelRatio 2 would be ~66 MB for a single page, so cap the pixels per
// canvas and let the pixel ratio fall as zoom rises.
const MAX_CANVAS_PX = 4e6;

// How many pages either side of the viewport keep their canvas. Beyond this
// the canvas is released and the placeholder takes over again, which is what
// makes scrolling a 92-page chapter at high zoom survivable.
const KEEP_RADIUS = 3;

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
    this.zoom = store.getZoom();
    this.onPageChange = null;
    this.onZoomChange = null;
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

    this.pdf = pdf;
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

    this._applyZoom();
    this._watch(token);
    this._trackScroll();
    const target = Math.min(Math.max(focus || first, first), last);
    await this._render(target, token);
    this.goTo(target, 'auto');
  }

  /** Width one page occupies, in CSS pixels, at the current zoom. */
  _pageWidth() {
    const styles = getComputedStyle(this.el);
    const pad = parseFloat(styles.paddingLeft) + parseFloat(styles.paddingRight);
    const avail = Math.max(240, this.el.clientWidth - pad);
    return Math.min(avail, 900) * this.zoom;
  }

  _applyZoom() {
    this.el.style.setProperty('--page-width', `${Math.round(this._pageWidth())}px`);
    this.el.classList.toggle('zoomed', this.zoom > 1);
  }

  setZoom(zoom) {
    const next = Math.min(ZOOM_STEPS[ZOOM_STEPS.length - 1], Math.max(ZOOM_STEPS[0], zoom));
    if (next === this.zoom) return;
    this.zoom = next;
    store.setZoom(next);
    this._applyZoom();
    // drop every canvas so pages re-render sharp at the new size
    const here = this.current || this.range?.first;
    this.pages.forEach((entry) => this._release(entry));
    this._render(here, this.token);
    this.onZoomChange?.(next);
  }

  stepZoom(delta) {
    const i = ZOOM_STEPS.indexOf(this.zoom);
    const at = i === -1 ? 0 : i;
    this.setZoom(ZOOM_STEPS[Math.min(ZOOM_STEPS.length - 1, Math.max(0, at + delta))]);
  }

  _watch(token) {
    this._observer?.disconnect();
    this._observer = new IntersectionObserver((entries) => {
      if (token !== this.token) return;
      for (const entry of entries) {
        if (entry.isIntersecting) this._render(Number(entry.target.dataset.page), token);
      }
    }, { root: this.el, rootMargin: '80% 0px', threshold: 0 });
    this.pages.forEach(({ holder }) => this._observer.observe(holder));
  }

  /** Which page you are on, from scroll position.

   *  Intersection ratio cannot answer this: zoomed in, or on a phone, a page
   *  is taller than the pane and never reaches half visibility.
   */
  _trackScroll() {
    if (this._onScroll) this.el.removeEventListener('scroll', this._onScroll);
    let queued = false;
    this._onScroll = () => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => {
        queued = false;
        const top = this.el.getBoundingClientRect().top;
        let best = null;
        let bestDist = Infinity;
        this.pages.forEach((entry, n) => {
          const dist = Math.abs(entry.holder.getBoundingClientRect().top - top);
          if (dist < bestDist) {
            bestDist = dist;
            best = n;
          }
        });
        if (best != null) {
          this._settleOn(best);
          this._reap();
        }
      });
    };
    this.el.addEventListener('scroll', this._onScroll, { passive: true });
  }

  _settleOn(page) {
    if (this.current === page) return;
    this.current = page;
    if (this.doc && this.chapter) store.rememberPlace(this.doc, this.chapter, page);
    this.onPageChange?.(page);
  }

  _release(entry) {
    // bump the generation so any render still in flight discards its result
    entry.gen = (entry.gen || 0) + 1;
    entry.holder.querySelectorAll('canvas').forEach((c) => c.remove());
    entry.holder.classList.remove('rendered');
    entry.rendered = false;
  }

  /** Keep a window of pages rendered around the current one, and free the rest.

   *  This has to render as well as release: an observer only fires when an
   *  element crosses a threshold, so a page released while still on screen
   *  would never be asked to draw itself again and would sit there blank.
   */
  _reap() {
    const here = this.current;
    if (here == null) return;
    this.pages.forEach((entry, n) => {
      if (Math.abs(n - here) > KEEP_RADIUS) this._release(entry);
      else if (!entry.rendered) this._render(n, this.token);
    });
  }

  async _render(n, token) {
    const entry = this.pages.get(n);
    if (!entry || entry.rendered) return;
    entry.rendered = true;
    const gen = entry.gen || 0;
    const stale = () => token !== this.token || gen !== (entry.gen || 0);
    let page;
    try {
      page = await this.pdf.getPage(n);
    } catch {
      if (!stale()) entry.rendered = false;
      return;
    }
    if (stale()) return;

    const base = page.getViewport({ scale: 1 });
    const cssWidth = this._pageWidth();
    const cssHeight = (cssWidth * base.height) / base.width;
    let dpr = Math.min(window.devicePixelRatio || 1, 2);
    const pixels = cssWidth * dpr * cssHeight * dpr;
    if (pixels > MAX_CANVAS_PX) dpr *= Math.sqrt(MAX_CANVAS_PX / pixels);

    const viewport = page.getViewport({ scale: (cssWidth / base.width) * dpr });
    const canvas = document.createElement('canvas');
    canvas.width = Math.floor(viewport.width);
    canvas.height = Math.floor(viewport.height);
    canvas.style.width = '100%';
    canvas.style.aspectRatio = `${base.width} / ${base.height}`;
    if (stale()) return;
    entry.holder.querySelectorAll('canvas').forEach((c) => c.remove());
    entry.holder.prepend(canvas);
    entry.holder.classList.add('rendered');
    await page.render({ canvasContext: canvas.getContext('2d', { alpha: false }), viewport }).promise;
  }

  goTo(page, behavior = 'smooth') {
    const entry = this.pages.get(page);
    if (!entry) return;
    this._render(page, this.token);
    entry.holder.scrollIntoView({ behavior, block: 'start', inline: 'nearest' });
    this._settleOn(page);
  }

  step(delta) {
    if (!this.range) return;
    const next = Math.min(this.range.last,
      Math.max(this.range.first, (this.current || this.range.first) + delta));
    this.goTo(next);
  }

  destroy() {
    this.token += 1;
    this._observer?.disconnect();
    if (this._onScroll) this.el.removeEventListener('scroll', this._onScroll);
    this.pages.forEach((entry) => this._release(entry));
    this.pages.clear();
    this.el.innerHTML = '';
  }
}

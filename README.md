# IFR Study Organizer

A small static site for building focused study sessions from the FAA
**Instrument Flying Handbook** (FAA-H-8083-15B) and **Instrument Procedures
Handbook** (FAA-H-8083-16B), with the **Instrument Rating – Airplane ACS**
(FAA-S-ACS-8C) alongside.

Pick the topics your next lesson covers — say holding patterns and nonprecision
approaches — and it gives you an ordered agenda: the exact page ranges to read
from both handbooks, the ACS tasks they map to, and a checklist of what to know.
It remembers your place in each chapter and when you last reviewed each topic.

## Using it

- **Topics** — free multi-select across 38 topics with search. Shows a running
  estimate of session length before you start.
- **ACS** — browse Areas of Operation down to individual Knowledge, Risk
  Management and Skill elements. Select tasks to pull their topics into a session.
- **Browse** — the full table of contents of both handbooks, every section
  deep-linked to its page.
- **Session** — agenda on the left, the actual handbook page in the middle,
  checkpoints on the right. "Mark reviewed & next" advances and stamps the topic.
- **Progress** — export and import your progress as JSON to move it between
  devices.

Freshness is colour-coded: green under 14 days, amber to 30, red past that or
never reviewed. The home page surfaces what is due.

### On a phone and a tablet

The layout follows the reading area, because a handbook page is the thing the
screen is for.

- **Desktop** — agenda, page and checkpoints side by side.
- **Tablet** — agenda beside the page, with the checkpoints as a drawer that
  opens *over* the page rather than shortening it. A whole page fits.
- **Phone** — the session drops the embedded reader and becomes prep mode: the
  topic, its readings with folio references, and the checkpoints. Tapping a
  reading opens the full-screen reader, and going back returns you to the same
  topic and reading.

The reader has a zoom control (100–300%), because at fit-width a two-column
handbook page puts 9pt text at about 5px on a phone. Zooming re-renders the
page rather than scaling the canvas up, so it stays sharp, and pans sideways.
Canvases are capped in size and released once you scroll away, which is what
keeps a 92-page chapter at full zoom from exhausting mobile Safari.

## Progress and privacy

Progress lives in `localStorage` in the browser you are using — nothing is sent
anywhere and there is no account. That means it is per-device: use **Progress →
Export** on one device and **Import** on the other to sync. Import merges rather
than replaces, keeping whichever review of a topic is newer.

## Publishing

The site is plain static files. On GitHub, enable **Settings → Pages → Deploy
from a branch**, pick this branch and `/ (root)`. It publishes to
`https://<user>.github.io/instrument-flying/`.

`.nojekyll` is committed so nothing gets filtered. The PDFs are committed as
plain files, not Git LFS — GitHub Pages serves LFS pointers as text rather than
resolving them.

## Rebuilding from the FAA sources

The chapter PDFs and everything in `data/` are generated. Rerun the pipeline
when the FAA revises a handbook or the ACS:

```sh
python3 -m venv .venv && .venv/bin/pip install pypdf
.venv/bin/python tools/build.py        # fetch, split, extract, verify, resolve
.venv/bin/python tools/validate.py     # must pass before committing
bash tools/vendor_pdfjs.sh             # only to change the pinned PDF.js
```

Then serve the folder over HTTP (`python3 -m http.server`) — opening
`index.html` from the filesystem will not work, because the app fetches its JSON
data.

### What the build does

1. **fetch** — downloads the two handbooks and the ACS into `.cache/` (gitignored).
2. **split** — cuts both handbooks into per-chapter PDFs. The FAA publishes
   standalone chapter files for the IPH, but they are unreliable — chapter 1
   contains a partial duplicate of itself — so both books are split locally from
   the combined PDFs. Chapter boundaries come from the printed folios (`10-1`,
   `10-2`, …) since neither PDF carries bookmarks.
3. **outline** — parses the printed two-column table of contents into a
   hierarchical section list, mapping each entry to a page in its chapter file.
4. **acs** — extracts the Areas, Tasks and every coded element (`IR.III.B.S1`)
   from the ACS.
5. **text** — dumps per-page text into `.cache/text/` for authoring and validation.
6. **verify** — reconciles the TOC against the pages themselves. Both handbooks
   index a few sections to the first page of a run of full-page figures rather
   than the page carrying the heading; those entries get moved.
7. **topics** — resolves the authored section references in `data/topics.json`
   into concrete page ranges, and fails loudly on anything that does not resolve.

`tools/validate.py` then re-reads the generated data against the PDFs: every
page range in bounds, every ACS code real, every ACS task covered by at least
one topic, and — the check that matters — the text of each range's first page
actually contains the section heading it resolved from. That is what catches a
page reference drifting off its material.

It also rejects a reading whose title is ambiguous within its chapter but not
pinned, and one that resolves to a chapter's cover page — "the heading is on
this page" is not enough to prove it is the right page when a heading repeats.

## Editing the topic map

`data/topics.json` is the hand-authored part and the reason the site is more
useful than a PDF reader. Each topic cites sections **by title**, not by page
number:

```json
{
  "id": "holding-patterns",
  "title": "Holding Patterns",
  "group": "En Route",
  "summary": "…",
  "acs": ["IR.III.B"],
  "estMinutes": 35,
  "readings": [
    { "doc": "ifh", "chapter": "10", "section": "Holding Procedures" },
    { "doc": "iph", "chapter": "2", "section": "En Route Holding Procedures" }
  ],
  "checkpoints": ["…"]
}
```

The build looks each title up in the extracted outline and works out the page
span, so page numbers never have to be typed or maintained by hand. A reading
can also use `"sections": [...]` to span several headings, or `"pages": [3, 7]`
where no heading lines up.

Both handbooks repeat headings inside a chapter — IPH chapter 1 has a
"Departure Procedures" cover page at 1-1 and the real section at 1-16, and IFH
chapter 7 runs its whole set of headings twice, once for analog panels and once
for electronic flight displays. An ambiguous title is a build error rather than
a silent guess; pin the one you mean with a folio:

```json
{ "doc": "iph", "chapter": "1", "section": "Departure Procedures", "folio": "1-16" }
```

`"sections"` entries take the same `{ "title", "folio" }` form when they need it.

## Layout

```
index.html          app shell
css/app.css
js/                 router, store, reader, session logic, views
data/               generated: docs, outline, acs; authored: topics.json
pdfs/ifh, pdfs/iph  per-chapter PDFs, plus the ACS
tools/              build pipeline and validator
vendor/pdfjs/       pinned PDF.js 4.10.38
```

No framework and no build step for the site itself — plain ES modules. PDF.js is
vendored and served same-origin, which is required: faa.gov sends no CORS
headers, so the browser cannot fetch the originals directly.

## Source documents

All three are FAA publications in the public domain.

| Document | Edition |
|---|---|
| Instrument Flying Handbook | FAA-H-8083-15B |
| Instrument Procedures Handbook | FAA-H-8083-16B |
| Instrument Rating – Airplane ACS | FAA-S-ACS-8C |

They are a study aid, not a source of navigation data. Fly the current charts.

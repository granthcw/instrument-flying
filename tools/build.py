#!/usr/bin/env python3
"""Build pipeline for the IFR Study Organizer.

Downloads the FAA source PDFs, splits them into per-chapter files, and
extracts the structural data (outline, ACS) the web app reads.

The FAA publishes standalone chapter PDFs for the IPH, but they are
unreliable -- chapter 1 contains a partial duplicate of itself -- so both
handbooks are split locally from the combined PDFs instead.

Usage:  python3 tools/build.py [fetch|split|outline|acs|text|all]
"""
import json
import os
import re
import shutil
import subprocess
import sys

from pypdf import PdfReader, PdfWriter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")
DATA = os.path.join(ROOT, "data")
PDFS = os.path.join(ROOT, "pdfs")

FAA = "https://www.faa.gov/sites/faa.gov/files/regulations_policies/handbooks_manuals/aviation"
SOURCES = {
    "ifh": f"{FAA}/FAA-H-8083-15B.pdf",
    "iph": f"{FAA}/instrument_procedures_handbook/FAA-H-8083-16B.pdf",
    "acs": "https://www.faa.gov/training_testing/testing/acs/instrument_rating_airplane_acs_8.pdf",
}

DOCS = {
    "ifh": {
        "title": "Instrument Flying Handbook",
        "code": "FAA-H-8083-15B",
        "toc_pages": range(12, 19),
        "chapters": {
            "1": "The National Airspace System",
            "2": "The Air Traffic Control System",
            "3": "Human Factors",
            "4": "Aerodynamic Factors",
            "5": "Flight Instruments",
            "6": "Airplane Attitude Instrument Flying",
            "7": "Airplane Basic Flight Maneuvers",
            "8": "Helicopter Attitude Instrument Flying",
            "9": "Navigation Systems",
            "10": "IFR Flight",
            "11": "Emergency Operations",
            "A": "Appendix A: Clearance Shorthand",
            "B": "Appendix B: Instrument Training Lesson Guide",
            "G": "Glossary",
            "I": "Index",
        },
    },
    "iph": {
        "title": "Instrument Procedures Handbook",
        "code": "FAA-H-8083-16B",
        "toc_pages": range(12, 17),
        "chapters": {
            "1": "Departure Procedures",
            "2": "En Route Operations",
            "3": "Arrivals",
            "4": "Approaches",
            "5": "Improvement Plans",
            "6": "Airborne Navigation Databases",
            "7": "Helicopter Instrument Procedures",
            "A": "Appendix A: Emergency Procedures",
            "B": "Appendix B: Acronyms",
            "G": "Glossary",
        },
    },
}

FOLIO_RE = re.compile(r"^([A-Z]{1,2}|\d{1,2})-(\d{1,3})$")


def log(*a):
    print(*a, flush=True)


# --------------------------------------------------------------------------
# fetch
# --------------------------------------------------------------------------
def fetch():
    os.makedirs(CACHE, exist_ok=True)
    for name, url in SOURCES.items():
        dest = os.path.join(CACHE, f"{name}.pdf")
        if os.path.exists(dest) and os.path.getsize(dest) > 100_000:
            log(f"  have {name}.pdf")
            continue
        log(f"  downloading {name} ...")
        subprocess.run(["curl", "-sSfL", "--max-time", "600", "-o", dest, url], check=True)


# --------------------------------------------------------------------------
# folios: pdf page -> printed page label ("9-12")
# --------------------------------------------------------------------------
def page_folio(page):
    """Return the printed folio on a page, or None for front matter."""
    text = page.extract_text() or ""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for cand in lines[:3] + lines[-3:]:
        if FOLIO_RE.match(cand):
            return cand
    return None


def repair_folios(folios):
    """Fix folios misread off the page and fill unlabelled body pages.

    Body pages run in a strict per-chapter sequence, so a value that breaks
    an otherwise continuous run -- a figure caption such as "A-109" sitting
    where the folio belongs -- is replaced by the one the sequence implies.
    """
    out = list(folios)
    for i in range(1, len(out) - 1):
        prev, nxt = out[i - 1], out[i + 1]
        if not prev or not nxt:
            continue
        pkey, pnum = prev.split("-")
        nkey, nnum = nxt.split("-")
        if pkey != nkey or int(nnum) - int(pnum) != 2:
            continue
        implied = f"{pkey}-{int(pnum) + 1}"
        if out[i] != implied:
            out[i] = implied
    return out


def folio_map(reader):
    return repair_folios([page_folio(p) for p in reader.pages])


def chapter_ranges(folios):
    """Group pages into chapters by the folio prefix, in document order.

    Returns [(chapter_key, first_page_index, last_page_index)] using 0-based
    inclusive page indices. Pages with no folio (front matter) are skipped,
    and an unlabelled page inside a chapter is absorbed into that chapter.
    """
    ranges = []
    for i, f in enumerate(folios):
        if f is None:
            if ranges:
                ranges[-1][2] = i  # absorb trailing unlabelled page
            continue
        key = f.split("-")[0]
        if ranges and ranges[-1][0] == key:
            ranges[-1][2] = i
        else:
            ranges.append([key, i, i])
    # An absorbed page at the tail of a chapter may really belong to the next
    # one; trim any trailing gap so ranges stay contiguous and non-overlapping.
    for a, b in zip(ranges, ranges[1:]):
        if a[2] >= b[1]:
            a[2] = b[1] - 1
    return [(k, s, e) for k, s, e in ranges]


def chapter_filename(key):
    return f"ch{int(key):02d}" if key.isdigit() else {"G": "glossary", "I": "index"}.get(key, f"app{key}")


# --------------------------------------------------------------------------
# split
# --------------------------------------------------------------------------
def split():
    manifest = {}
    for doc, meta in DOCS.items():
        src = os.path.join(CACHE, f"{doc}.pdf")
        reader = PdfReader(src)
        folios = folio_map(reader)
        json.dump(folios, open(os.path.join(CACHE, f"{doc}_folios.json"), "w"))
        outdir = os.path.join(PDFS, doc)
        os.makedirs(outdir, exist_ok=True)
        parts, seen = [], set()
        for key, start, end in chapter_ranges(folios):
            if key in seen:
                raise SystemExit(
                    f"{doc}: chapter {key!r} split into two ranges "
                    f"(pages {start+1}-{end+1}); folio detection needs a look")
            seen.add(key)
            if key not in meta["chapters"]:
                log(f"  !! {doc}: unexpected chapter key {key!r} (pages {start+1}-{end+1})")
                continue
            name = chapter_filename(key)
            writer = PdfWriter()
            for i in range(start, end + 1):
                writer.add_page(reader.pages[i])
            path = os.path.join(outdir, f"{name}.pdf")
            with open(path, "wb") as fh:
                writer.write(fh)
            # first folio in the range fixes the offset from folio -> pdf page
            first = next((folios[i] for i in range(start, end + 1) if folios[i]), None)
            firstnum = int(first.split("-")[1]) if first else 1
            parts.append({
                "key": key,
                "title": meta["chapters"][key],
                "file": f"pdfs/{doc}/{name}.pdf",
                "pages": end - start + 1,
                "firstFolio": firstnum,
                "sizeKB": round(os.path.getsize(path) / 1024),
            })
            log(f"  {doc}/{name}.pdf  {end-start+1:3d}p  {parts[-1]['sizeKB']:6d}KB  {meta['chapters'][key]}")
        manifest[doc] = {"title": meta["title"], "code": meta["code"], "parts": parts}
    shutil.copy(os.path.join(CACHE, "acs.pdf"), os.path.join(PDFS, "acs.pdf"))
    os.makedirs(DATA, exist_ok=True)
    json.dump(manifest, open(os.path.join(DATA, "docs.json"), "w"), indent=1)
    return manifest


# --------------------------------------------------------------------------
# outline: parse the printed table of contents
# --------------------------------------------------------------------------
def page_lines(page):
    """Group a page's text fragments into lines of (x, text), top to bottom."""
    frags = []

    def visitor(text, cm, tm, font, size):
        if text and text.strip():
            frags.append((round(tm[5], 1), round(tm[4], 1), text))

    page.extract_text(visitor_text=visitor)
    frags.sort(key=lambda f: (-f[0], f[1]))
    lines, cur, cury = [], [], None
    for y, x, t in frags:
        if cury is None:
            cur, cury = [(x, t)], y
        elif abs(y - cury) <= 3.0:
            cur.append((x, t))
        else:
            lines.append((cury, cur))
            cur, cury = [(x, t)], y
    if cur:
        lines.append((cury, cur))
    return lines


LEADER_RE = re.compile(r"\.{2,}")
# a folio ("9-27") or a roman front-matter page ("vii"), as a split point
SPLIT_RE = re.compile(r"((?:[A-Z]{1,2}|\d{1,2})-\d{1,3}|\b[ivxl]{1,6}\b)")
FOLIO_ONLY = re.compile(r"^(?:[A-Z]{1,2}|\d{1,2})-\d{1,3}$")
CHAPTER_HDR = re.compile(r"^(?:Chapter|Appendix)\s+([0-9A-Z]{1,2})\b\s*", re.I)
NOISE = ("table of contents",)


def run_starts(frags, gap=20.0):
    """x of each fragment that begins a run, i.e. follows a horizontal gap."""
    starts, prev = [], None
    for x, _t in sorted(frags):
        if prev is None or x - prev > gap:
            starts.append(x)
        prev = x
    return starts


def indent_ladders(lines):
    """Return the heading-indent ladders on a TOC page, left column first.

    Run starts on a TOC page fall into four x-groups: the left column's
    heading indents, its right-aligned page numbers, then the same two for
    the right column. Heading indents step by exactly 9pt, which separates
    them from the ragged page-number groups.
    """
    counts = {}
    for _y, frags in lines:
        for x in run_starts(frags):
            counts[round(x)] = counts.get(round(x), 0) + 1
    kept = sorted(x for x, c in counts.items() if c >= 2)
    if not kept:
        return []
    groups, cur = [], [kept[0]]
    for lo, hi in zip(kept, kept[1:]):
        if hi - lo > 20:
            groups.append(cur)
            cur = [hi]
        else:
            cur.append(hi)
    groups.append(cur)
    return [g for g in groups
            if len(g) >= 2 and all((hi - lo) % 9 == 0 for lo, hi in zip(g, g[1:]))]


def toc_entries(reader, toc_pages):
    """Yield (depth, title, folio) for every entry in a two-column TOC.

    The handbooks print their contents in two columns, so fragments from
    both columns share a text line. Rows are bucketed by x into columns and
    read left column then right; the left edge within a column, measured
    against that column's own margin, gives the heading depth.
    """
    out, pending = [], ""
    for pno in toc_pages:
        page = reader.pages[pno - 1]
        width = float(page.mediabox.width)
        lines = page_lines(page)
        ladders = indent_ladders(lines)
        # the divider sits just left of the right column's outermost indent,
        # so each column keeps its own right-aligned page numbers
        split = ladders[1][0] - 9 if len(ladders) > 1 else width / 2
        bases = [ladders[0][0] if ladders else 0,
                 ladders[1][0] if len(ladders) > 1 else split]
        cols = {0: [], 1: []}
        for y, frags in lines:
            for ci, (lo, hi) in enumerate(((0, split), (split, 10 ** 6))):
                sel = sorted((x, t) for x, t in frags if lo <= x < hi)
                if not sel:
                    continue
                text = re.sub(r"\s+", " ", "".join(t for _, t in sel)).strip()
                if text:
                    cols[ci].append((-y, sel[0][0], text))
        for ci in (0, 1):
            for _, x, text in sorted(cols[ci]):
                stripped = LEADER_RE.sub(" ", text).strip()
                if not stripped or stripped.lower() in NOISE:
                    continue
                depth = max(0, min(4, round((x - bases[ci]) / 9.0)))
                chunks = SPLIT_RE.split(stripped)
                # chunks alternate text, folio, text, folio, ... text
                for i in range(1, len(chunks), 2):
                    title = re.sub(r"\s+", " ", pending + " " + chunks[i - 1]).strip(" .")
                    pending = ""
                    title = CHAPTER_HDR.sub("", title).strip(" .")
                    folio = chunks[i]
                    if not FOLIO_ONLY.match(folio):
                        continue  # roman front-matter page, not in the split PDFs
                    if title and len(title) <= 90:
                        out.append((depth, title, folio))
                tail = chunks[-1].strip()
                pending = tail if len(tail) <= 80 else ""
            pending = ""  # never carry a fragment across a column or page
    return out


def outline():
    docs = json.load(open(os.path.join(DATA, "docs.json")))
    result = {}
    for doc, meta in DOCS.items():
        reader = PdfReader(os.path.join(CACHE, f"{doc}.pdf"))
        firstfolio = {p["key"]: p["firstFolio"] for p in docs[doc]["parts"]}
        sections = []
        for depth, title, folio in toc_entries(reader, meta["toc_pages"]):
            key, num = folio.split("-")
            if key not in firstfolio:
                continue
            sections.append({
                "depth": depth,
                "title": title,
                "chapter": key,
                "folio": folio,
                "page": int(num) - firstfolio[key] + 1,
            })
        # keep document order and drop entries the TOC repeats verbatim
        order = {k: i for i, k in enumerate(meta["chapters"])}
        sections.sort(key=lambda s: (order[s["chapter"]], s["page"]))
        seen, deduped = set(), []
        for s in sections:
            key = (s["chapter"], s["page"], s["title"].lower())
            if key not in seen:
                seen.add(key)
                deduped.append(s)
        result[doc] = deduped
        log(f"  {doc}: {len(deduped)} TOC entries ({len(sections)-len(deduped)} dupes dropped)")
    json.dump(result, open(os.path.join(DATA, "outline.json"), "w"), indent=1)
    return result


# --------------------------------------------------------------------------
# ACS: areas of operation, tasks, and their coded elements
# --------------------------------------------------------------------------
AREA_RE = re.compile(r"Area of Operation\s+([IVX]+)\.\s+(.*?)\s*$", re.M)
TASK_RE = re.compile(r"Task\s+([A-Z])\.\s+(.*?)\s*$", re.M)
ELEM_RE = re.compile(r"\b(IR\.([IVX]+)\.([A-Z])\.([KRS])(\d+)([a-z]?))\b")
SECTION_HDR = re.compile(
    r"(Knowledge:|Risk\s*Management:|Skills:)\s*The applicant[^:]*:", re.I)


def acs_page_text(reader, page_index):
    """Page text with the ACS's displaced drop caps put back."""
    text = reader.pages[page_index].extract_text() or ""
    text = re.sub(r"\beferences:\s*R\b", "References:", text)
    text = re.sub(r"\bbjective:\s*O\b", "Objective:", text)
    return text


def acs():
    reader = PdfReader(os.path.join(CACHE, "acs.pdf"))

    # bookmarks give the authoritative area/task titles and page numbers
    areas, current = [], None
    for item in reader.outline:
        if isinstance(item, list):
            for sub in item:
                if isinstance(sub, list) or current is None:
                    continue
                m = TASK_RE.match(sub.title.strip())
                if m:
                    current["tasks"].append({
                        "code": f"IR.{current['num']}.{m.group(1)}",
                        "letter": m.group(1),
                        "title": m.group(2).strip(),
                        "page": reader.get_destination_page_number(sub) + 1,
                        "elements": {"K": [], "R": [], "S": []},
                    })
            continue
        m = AREA_RE.match(item.title.strip())
        if m:
            current = {"num": m.group(1), "title": m.group(2).strip(), "tasks": []}
            areas.append(current)
        else:
            current = None

    # element text comes from the pages themselves
    full = "\n".join(acs_page_text(reader, i) for i in range(len(reader.pages)))
    hits = list(ELEM_RE.finditer(full))
    by_code = {}
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(full)
        body = full[m.end():end]
        body = SECTION_HDR.split(body)[0]
        body = re.sub(r"Task\s+[A-Z]\.\s.*$", "", body, flags=re.S)
        body = re.sub(r"Area of Operation\s+[IVX]+\..*$", "", body, flags=re.S)
        body = re.sub(r"\s+", " ", body).strip(" .;")
        body = re.sub(r"\s+\d{1,3}$", "", body).strip(" .;")  # trailing folio
        if body:
            by_code[m.group(1)] = body

    for area in areas:
        for task in area["tasks"]:
            for code, body in by_code.items():
                parts = code.split(".")
                if f"IR.{parts[1]}.{parts[2]}" != task["code"]:
                    continue
                kind = parts[3][0]
                task["elements"][kind].append({"code": code, "text": body})
            for kind in task["elements"]:
                task["elements"][kind].sort(
                    key=lambda e: (int(re.match(r"[KRS](\d+)", e["code"].split(".")[-1]).group(1)),
                                   e["code"][-1] if e["code"][-1].isalpha() else ""))

    total = sum(len(t["elements"][k]) for a in areas for t in a["tasks"] for k in "KRS")
    doc = {
        "code": "FAA-S-ACS-8C",
        "title": "Instrument Rating \u2013 Airplane ACS",
        "file": "pdfs/acs.pdf",
        "areas": areas,
    }
    json.dump(doc, open(os.path.join(DATA, "acs.json"), "w"), indent=1)
    log(f"  {len(areas)} areas, {sum(len(a['tasks']) for a in areas)} tasks, {total} elements")
    return doc


# --------------------------------------------------------------------------
# verify: reconcile TOC page numbers against the pages themselves
# --------------------------------------------------------------------------
def norm_text(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def page_text(doc, chapter, page):
    name = chapter_filename(chapter)
    path = os.path.join(CACHE, "text", doc, f"{name}_p{page:03d}.txt")
    try:
        return norm_text(open(path).read())
    except OSError:
        return ""


def verify(window=6):
    """Correct outline pages where the printed TOC disagrees with the book.

    Both handbooks index a few sections to the first page of a run of
    full-page figures rather than to the page carrying the heading. Where
    the heading is absent from its stated page but present a little further
    on, the outline is moved to the page that actually has it.
    """
    data = json.load(open(os.path.join(DATA, "outline.json")))
    docs = json.load(open(os.path.join(DATA, "docs.json")))
    npages = {d: {p["key"]: p["pages"] for p in docs[d]["parts"]} for d in docs}
    first = {d: {p["key"]: p["firstFolio"] for p in docs[d]["parts"]} for d in docs}
    moved = absent = 0
    for doc, sections in data.items():
        for sec in sections:
            want = norm_text(sec["title"])
            head = " ".join(want.split()[:4])
            if not head:
                continue
            if head in page_text(doc, sec["chapter"], sec["page"]):
                continue
            limit = npages[doc][sec["chapter"]]
            for offset in range(1, window + 1):
                nxt = sec["page"] + offset
                if nxt <= limit and head in page_text(doc, sec["chapter"], nxt):
                    sec["page"] = nxt
                    sec["folio"] = f"{sec['chapter']}-{nxt + first[doc][sec['chapter']] - 1}"
                    moved += 1
                    break
            else:
                absent += 1
    json.dump(data, open(os.path.join(DATA, "outline.json"), "w"), indent=1)
    log(f"  {moved} entries moved to the page carrying the heading, "
        f"{absent} headings not found as text (figures, wrapped titles)")
    return data


# --------------------------------------------------------------------------
# topics: resolve authored section references into concrete page ranges
# --------------------------------------------------------------------------
def find_section(sections, chapter, title, folio=None):
    """Locate an authored section reference within a chapter's outline.

    Both handbooks repeat headings within a chapter -- IPH chapter 1 has a
    "Departure Procedures" cover page at 1-1 and the section itself at 1-16,
    and IFH chapter 7 runs the same headings twice, once for analog panels
    and once for electronic flight displays. Picking the first match silently
    lands on the wrong one, so an ambiguous title is an error and the author
    pins it with an explicit folio.
    """
    inch = [s for s in sections if s["chapter"] == str(chapter)]
    want = title.strip().lower()
    matches = [s for s in inch if s["title"].lower() == want] \
        or [s for s in inch if want in s["title"].lower()]
    if folio:
        matches = [s for s in matches if s["folio"] == folio]
        if not matches:
            raise KeyError(f"no section {title!r} at folio {folio} in chapter {chapter}")
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        where = ", ".join(s["folio"] for s in matches)
        raise KeyError(f"section {title!r} appears {len(matches)} times in chapter "
                       f"{chapter} ({where}); pin one with an explicit folio")
    raise KeyError(f"no section {title!r} in chapter {chapter}")


def section_range(sections, section, npages):
    """Page span of a section, running to the next same-or-shallower heading."""
    idx = sections.index(section)
    end = npages
    for nxt in sections[idx + 1:]:
        if nxt["chapter"] != section["chapter"]:
            break
        if nxt["depth"] <= section["depth"] and nxt["page"] > section["page"]:
            # the boundary page carries the tail of this section as well as
            # the start of the next, so it belongs in both ranges
            end = nxt["page"]
            break
    return section["page"], max(section["page"], min(end, npages))


def topics():
    outline_data = json.load(open(os.path.join(DATA, "outline.json")))
    docs = json.load(open(os.path.join(DATA, "docs.json")))
    authored = json.load(open(os.path.join(DATA, "topics.json")))
    acs_doc = json.load(open(os.path.join(DATA, "acs.json")))
    known_tasks = {t["code"] for a in acs_doc["areas"] for t in a["tasks"]}

    npages = {d: {p["key"]: p["pages"] for p in docs[d]["parts"]} for d in docs}
    first = {d: {p["key"]: p["firstFolio"] for p in docs[d]["parts"]} for d in docs}
    errors = []
    built = []

    for topic in authored:
        readings = []
        for ref in topic["readings"]:
            doc, chapter = ref["doc"], str(ref["chapter"])
            # a section reference is a title, or {"title", "folio"} to pin
            # which occurrence when a chapter repeats the heading
            raw = ref.get("sections") or ([ref["section"]] if "section" in ref else [])
            titles = [r if isinstance(r, dict) else {"title": r} for r in raw]
            if "folio" in ref and len(titles) == 1:
                titles[0] = {**titles[0], "folio": ref["folio"]}
            try:
                resolved = []
                if titles:
                    spans = []
                    for t in titles:
                        sec = find_section(outline_data[doc], chapter,
                                           t["title"], t.get("folio"))
                        resolved.append({"title": sec["title"], "page": sec["page"],
                                         "folio": sec["folio"]})
                        spans.append(section_range(outline_data[doc], sec, npages[doc][chapter]))
                    start, end = min(s for s, _ in spans), max(e for _, e in spans)
                    label = (titles[0]["title"] if len(titles) == 1
                             else f"{titles[0]['title']} \u2013 {titles[-1]['title']}")
                else:
                    start, end = ref["pages"]
                    label = ref.get("label", "")
            except (KeyError, IndexError) as exc:
                errors.append(f"{topic['id']}: {exc}")
                continue
            base = first[doc][chapter]
            readings.append({
                "doc": doc,
                "chapter": chapter,
                "title": ref.get("label", label),
                "note": ref.get("note", ""),
                "startPage": start,
                "endPage": end,
                "folio": f"{chapter}-{start + base - 1}",
                "folioEnd": f"{chapter}-{end + base - 1}",
                "pages": end - start + 1,
                "sections": resolved,
            })
        for code in topic.get("acs", []):
            if code not in known_tasks:
                errors.append(f"{topic['id']}: unknown ACS task {code}")
        seen, unique = set(), []
        for r in readings:
            span = (r["doc"], r["chapter"], r["startPage"], r["endPage"])
            if span not in seen:
                seen.add(span)
                unique.append(r)
        readings = unique
        built.append({**topic, "readings": readings,
                      "pageCount": sum(r["pages"] for r in readings)})

    if errors:
        for e in errors:
            log("  !! " + e)
        raise SystemExit(f"{len(errors)} unresolved topic reference(s)")

    json.dump(built, open(os.path.join(DATA, "topics.built.json"), "w"), indent=1)
    log(f"  {len(built)} topics, {sum(len(t['readings']) for t in built)} readings, "
        f"{sum(t['pageCount'] for t in built)} pages referenced")
    return built


# --------------------------------------------------------------------------
# text dump (not shipped; used for authoring and validation)
# --------------------------------------------------------------------------
def text():
    for doc in DOCS:
        outdir = os.path.join(CACHE, "text", doc)
        os.makedirs(outdir, exist_ok=True)
        for part in json.load(open(os.path.join(DATA, "docs.json")))[doc]["parts"]:
            reader = PdfReader(os.path.join(ROOT, part["file"]))
            name = os.path.basename(part["file"])[:-4]
            for i, page in enumerate(reader.pages):
                with open(os.path.join(outdir, f"{name}_p{i+1:03d}.txt"), "w") as fh:
                    fh.write(page.extract_text() or "")
        log(f"  {doc}: text dumped")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    steps = {"fetch": fetch, "split": split, "outline": outline, "acs": acs,
             "text": text, "verify": verify, "topics": topics}
    order = (["fetch", "split", "outline", "acs", "text", "verify", "topics"]
             if cmd == "all" else [cmd])
    for name in order:
        log(f"== {name}")
        steps[name]()


if __name__ == "__main__":
    main()

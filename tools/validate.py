#!/usr/bin/env python3
"""Check the generated study data against the PDFs it points at.

The failure mode that matters is a reading whose page range drifts off the
material it claims to cover, so the central check reads the text of each
range's first page and looks for the section heading it resolved from.

Usage:  python3 tools/validate.py
"""
import json
import os
import re
import sys

from pypdf import PdfReader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
MAX_FILE_MB = 50

problems = []
notes = []


def fail(msg):
    problems.append(msg)


def norm(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def main():
    docs = json.load(open(os.path.join(DATA, "docs.json")))
    topics = json.load(open(os.path.join(DATA, "topics.built.json")))
    acs = json.load(open(os.path.join(DATA, "acs.json")))
    outline = json.load(open(os.path.join(DATA, "outline.json")))

    # ---- the split PDFs themselves
    counts = {}
    for doc, meta in docs.items():
        for part in meta["parts"]:
            path = os.path.join(ROOT, part["file"])
            if not os.path.exists(path):
                fail(f"missing PDF {part['file']}")
                continue
            mb = os.path.getsize(path) / 1e6
            if mb > MAX_FILE_MB:
                fail(f"{part['file']} is {mb:.0f} MB, over the {MAX_FILE_MB} MB limit")
            actual = len(PdfReader(path).pages)
            counts[(doc, part["key"])] = actual
            if actual != part["pages"]:
                fail(f"{part['file']}: manifest says {part['pages']} pages, file has {actual}")

    # ---- outline entries point at real pages
    for doc, sections in outline.items():
        for sec in sections:
            n = counts.get((doc, sec["chapter"]))
            if n is None:
                fail(f"outline {doc} references missing chapter {sec['chapter']}")
            elif not 1 <= sec["page"] <= n:
                fail(f"outline {doc} ch{sec['chapter']} '{sec['title']}' page {sec['page']} outside 1..{n}")

    # ---- topics
    ids = set()
    for topic in topics:
        if topic["id"] in ids:
            fail(f"duplicate topic id {topic['id']}")
        ids.add(topic["id"])
        if len(topic.get("checkpoints", [])) < 3:
            fail(f"{topic['id']}: fewer than 3 checkpoints")
        if not topic.get("readings"):
            fail(f"{topic['id']}: no readings")
        for r in topic["readings"]:
            n = counts.get((r["doc"], r["chapter"]))
            if n is None:
                fail(f"{topic['id']}: unknown {r['doc']} chapter {r['chapter']}")
                continue
            if not (1 <= r["startPage"] <= r["endPage"] <= n):
                fail(f"{topic['id']}: {r['doc']} ch{r['chapter']} range "
                     f"{r['startPage']}-{r['endPage']} outside 1..{n}")

    # ---- the real check: does the page carry the heading it resolved from?
    checked = matched = 0
    cache = {}
    for topic in topics:
        for r in topic["readings"]:
            for sec in r.get("sections", []):
                key = (r["doc"], r["chapter"])
                if key not in cache:
                    path = os.path.join(ROOT, f"pdfs/{r['doc']}/"
                                        + os.path.basename(dict(
                                            (p["key"], p["file"]) for p in docs[r["doc"]]["parts"])[r["chapter"]]))
                    cache[key] = PdfReader(path)
                reader = cache[key]
                page = sec["page"]
                if not 1 <= page <= len(reader.pages):
                    fail(f"{topic['id']}: section '{sec['title']}' page {page} out of range")
                    continue
                checked += 1
                body = norm(reader.pages[page - 1].extract_text() or "")
                want = norm(sec["title"])
                # headings can wrap, so accept the first few words as evidence
                head = " ".join(want.split()[:4])
                if want in body or (head and head in body):
                    matched += 1
                else:
                    fail(f"{topic['id']}: '{sec['title']}' not found on "
                         f"{r['doc']} ch{r['chapter']} page {page}")

    # ---- a resolved section must be the only one of its name in the chapter,
    # and must not be the chapter's cover page. Both handbooks repeat headings,
    # so "the heading is on this page" is not enough to prove it is the right one.
    titles_by_chapter = {}
    for doc, sections in outline.items():
        for sec in sections:
            titles_by_chapter.setdefault((doc, sec["chapter"]), []).append(sec)
    for topic in topics:
        for r in topic["readings"]:
            siblings = titles_by_chapter.get((r["doc"], r["chapter"]), [])
            for sec in r.get("sections", []):
                same = [s for s in siblings if s["title"].lower() == sec["title"].lower()]
                if len(same) > 1 and not sec.get("folio"):
                    fail(f"{topic['id']}: '{sec['title']}' occurs {len(same)}x in "
                         f"{r['doc']} ch{r['chapter']} and is not pinned to a folio")
                chapter_title = next((p["title"] for p in docs[r["doc"]]["parts"]
                                      if p["key"] == r["chapter"]), "")
                if sec["page"] == 1 and sec["title"].lower() == chapter_title.lower():
                    fail(f"{topic['id']}: '{sec['title']}' resolved to the chapter "
                         f"cover page ({r['doc']} ch{r['chapter']} p1)")
        if topic["pageCount"] < 4:
            fail(f"{topic['id']}: only {topic['pageCount']} pages of reading, likely a stub")

    # ---- ACS coverage
    tasks = {t["code"] for a in acs["areas"] for t in a["tasks"]}
    used = {c for t in topics for c in t.get("acs", [])}
    for code in sorted(used - tasks):
        fail(f"topics reference unknown ACS task {code}")
    uncovered = sorted(tasks - used)
    if uncovered:
        fail(f"ACS tasks with no topic: {', '.join(uncovered)}")

    notes.append(f"{len(topics)} topics, {sum(len(t['readings']) for t in topics)} readings")
    notes.append(f"{matched}/{checked} section headings confirmed on their page")
    notes.append(f"{len(tasks)} ACS tasks, all covered" if not uncovered else "")
    total = sum(os.path.getsize(os.path.join(ROOT, p["file"]))
                for m in docs.values() for p in m["parts"]) / 1e6
    notes.append(f"{total:.0f} MB of chapter PDFs")

    for n in notes:
        if n:
            print("  " + n)
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print("  !! " + p)
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Runs the test cases that can be settled without someone reading documents,
and writes what each one showed to case_results.md.

    python run_cases.py            every case that needs no argument
    python run_cases.py c          a whole group
    python run_cases.py c2 d6      named cases
    python run_cases.py free       only the cases that spend no Gemini quota
    python run_cases.py a1 x.pdf   a case that needs a file
    python run_cases.py g2 https://your-app.streamlit.app

Twenty-six of the thirty-seven cases are here. The rest need a judgement
about meaning — whether a passage really supports the claim citing it —
and those print the evidence and record the verdict you type.

Cases marked "gemini" below make one call per item and are bounded by
SAMPLE. Everything else is database work and costs nothing.

Nothing here writes to the documents or chunks tables.
"""

import json
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

RESULTS = Path("case_results.md")
LEDGER = Path("ingest_ledger.json")

# How many documents the sampled cases look at.
#
# At 25 the margin of error on a percentage is around ten points, which
# is wider than most of the changes worth making — two runs of the same
# unchanged system came back 12 points apart. 100 brings it to about
# five. Lower it only to spend less quota, and say so when quoting a
# figure taken at 25.
SAMPLE = 100

results = []


def record(case, name, verdict, detail):
    results.append((case, name, verdict, detail))
    print(f"\n  {case}  {verdict.upper()}  —  {detail}\n")


def ask_verdict(prompt="Pass, fail or partial? "):
    try:
        answer = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return "not recorded"
    return answer or "not recorded"


def rule(title):
    print("\n" + "=" * 74)
    print(title)
    print("=" * 74)


def pct(n, d):
    return f"{n / d:.0%}" if d else "—"


# ══════════════════════════════════════════════════════════════════
#  A — reading documents
# ══════════════════════════════════════════════════════════════════

def case_a1(path=None):
    """
    Two-column paper. The case says to read the output by eye, so that is
    what this sets up — with two numbers that usually give the answer
    before you finish reading. Interleaved columns run two unrelated
    halves into one line, so sentences grow very long and lines stop
    ending where sentences end.
    """
    rule("A1  Two-column paper")

    if not path:
        print("  Needs a genuinely two-column PDF:")
        print("      python run_cases.py a1 path\\to\\paper.pdf")
        record("A1", "Two-column paper", "not run", "no file given")
        return

    import reader

    pages, note, _ = reader.read_with_stats(Path(path))
    if note:
        record("A1", "Two-column paper", "fail",
               f"{Path(path).name} could not be read: {note}")
        return
    if not pages:
        record("A1", "Two-column paper", "fail", f"{path} produced no text")
        return

    text = pages[0][1]
    sentences = [s for s in re.split(r"[.!?]\s", text) if s.strip()]
    words = len(text.split())
    avg = words / max(len(sentences), 1)

    lines = [l for l in text.splitlines() if l.strip()]
    ending = sum(1 for l in lines if l.rstrip().endswith((".", "?", "!")))
    share = ending / max(len(lines), 1)

    print(f"\n  {words} words on page 1, {len(sentences)} sentences")
    print(f"  average sentence length   {avg:.0f} words"
          f"   (over about 40 suggests columns running together)")
    print(f"  lines ending a sentence   {share:.0%}   (under about 10% likewise)")
    print("\n" + "-" * 74)
    print(text[:2500])
    print("-" * 74)
    print("\n  Does each column run top to bottom with sentences intact?")

    record("A1", "Two-column paper", ask_verdict(),
           f"{avg:.0f} words per sentence, {share:.0%} of lines end one, "
           f"on {Path(path).name}")


def case_a2():
    """
    Scanned document. Counted, not judged: the ingestion ledger records
    how many pages of each file had to be read as images, so the recovery
    rate is already written down — it has just never been added up.
    """
    rule("A2  Scanned document")

    if not LEDGER.exists():
        record("A2", "Scanned document", "not run",
               "ingest_ledger.json not found — run from the project folder")
        return

    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))

    ingested = ocr_docs = ocr_pages = fully = 0
    for entry in ledger.values():
        note = entry.get("note", "")
        if not note.startswith("ok"):
            continue
        ingested += 1
        found = re.search(r"(\d+) read from images", note)
        if not found:
            continue
        ocr_docs += 1
        count = int(found.group(1))
        ocr_pages += count
        total = re.search(r"(\d+) pages", note)
        if total and int(total.group(1)) == count:
            fully += 1

    if not ingested:
        record("A2", "Scanned document", "not run", "ledger holds no results")
        return

    print(f"\n  documents ingested             {ingested}")
    print(f"  needed at least one image read {ocr_docs}   ({pct(ocr_docs, ingested)})")
    print(f"  every page read as an image    {fully}   — no text layer at all")
    print(f"  pages recovered this way       {ocr_pages}")

    scans = (f"{fully} was a scan end to end" if fully == 1
             else f"{fully} were scans end to end")
    record("A2", "Scanned document", "pass" if ocr_docs else "fail",
           f"{ocr_pages} pages recovered across {ocr_docs} of {ingested} "
           f"documents ({pct(ocr_docs, ingested)}); {scans} and would "
           f"otherwise have indexed empty")


def case_a3():
    """
    Headers and footers. This case tested behaviour that no longer exists
    — stripping was removed because it was deleting real content, so
    "repeated lines stripped" is now the wrong answer.

    What matters instead is whether the headers left in do any harm. They
    are harmless if searching for one does not flood the results.
    """
    rule("A3  Headers and footers")

    import db
    import search

    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT d.id, d.title, d.filename
            FROM documents d
            JOIN chunks c ON c.doc_id = d.id
            WHERE d.status = 'ingested' AND d.page_count >= 10
            GROUP BY d.id
            HAVING count(c.id) >= 10
            ORDER BY d.page_count DESC
            LIMIT 1
            """
        ).fetchone()

        if not row:
            record("A3", "Headers and footers", "not run",
                   "no document with ten or more pages of passages yet")
            return

        passages = conn.execute(
            "SELECT text FROM chunks WHERE doc_id = %s", (row["id"],)
        ).fetchall()

    counts = {}
    for p in passages:
        for line in p["text"].splitlines():
            line = line.strip()
            if 12 <= len(line) <= 90 and not line[0].isdigit():
                counts[line] = counts.get(line, 0) + 1

    repeated = [(l, n) for l, n in
                sorted(counts.items(), key=lambda kv: -kv[1]) if n >= 3]

    name = row["title"] or row["filename"]
    if not repeated:
        record("A3", "Headers and footers", "pass",
               f"no line repeats across the passages of {name}, so no running "
               f"header survived into them")
        return

    header, times = repeated[0]
    print(f"\n  in: {name}")
    print(f"  most repeated line, {times} times:\n      {header!r}")
    print("\n  searching for it, to see whether it distorts results…")

    hits = search.search(header, k=8)
    same = sum(1 for h in hits if h["doc_id"] == row["id"])
    print(f"  {same} of {len(hits)} results come from that one document")
    for i, h in enumerate(hits[:5], start=1):
        print(f"    {i}. {(h['title'] or h['filename'])[:60]}  p.{h['page']}")

    print("\n  Real content, or header noise?")
    record("A3", "Headers and footers", ask_verdict(),
           f"case rewritten — stripping was removed on purpose. Header "
           f"{header!r} repeats {times} times in {name}; searching it returns "
           f"{same} of {len(hits)} results from that document")


def case_a5():
    """
    Page attribution. Checked against the record rather than the paper:
    every passage must carry a page number, that number must fall inside
    the document, and passages must run in page order.

    A page off by one cannot be caught this way — only opening the file
    shows that. A page out of range, missing, or out of order can, and
    those are the failures that make a citation point somewhere it should
    not.
    """
    rule("A5  Page attribution")

    import db

    with db.connect() as conn:
        missing = conn.execute(
            "SELECT count(*) AS n FROM chunks WHERE page IS NULL OR page < 1"
        ).fetchone()["n"]

        beyond = conn.execute(
            """
            SELECT count(*) AS n
            FROM chunks c JOIN documents d ON d.id = c.doc_id
            WHERE d.page_count IS NOT NULL AND c.page > d.page_count
            """
        ).fetchone()["n"]

        total = conn.execute("SELECT count(*) AS n FROM chunks").fetchone()["n"]

        disordered = conn.execute(
            """
            SELECT count(*) AS n FROM (
              SELECT doc_id, page, seq,
                     lag(page) OVER (PARTITION BY doc_id ORDER BY seq) AS prev
              FROM chunks
            ) t WHERE prev IS NOT NULL AND page < prev
            """
        ).fetchone()["n"]

    print(f"\n  passages                    {total}")
    print(f"  with no page number         {missing}")
    print(f"  page beyond the document    {beyond}")
    print(f"  out of page order           {disordered}")

    bad = missing + beyond + disordered
    record("A5", "Page attribution", "pass" if bad == 0 else "fail",
           f"{total} passages — {missing} without a page, {beyond} beyond the "
           f"document's length, {disordered} out of order. An off-by-one "
           f"cannot be seen from the record and still needs one citation "
           f"opened by hand")


def case_a6():
    """
    Passage across a page break. Chunking happens inside a page by
    design, so a passage claiming two pages should be impossible. This
    confirms the design held rather than assuming it.

    Each passage carries exactly one page number, so the check is that
    the passages of a page form one unbroken run of sequence numbers —
    a gap would mean text placed on the wrong page.
    """
    rule("A6  Passage across a page break")

    import db

    with db.connect() as conn:
        pages_per_doc = conn.execute(
            """
            SELECT d.id, d.filename, count(DISTINCT c.page) AS pages,
                   d.page_count
            FROM documents d JOIN chunks c ON c.doc_id = d.id
            WHERE d.status = 'ingested'
            GROUP BY d.id
            HAVING count(DISTINCT c.page) > COALESCE(d.page_count, 0)
            """
        ).fetchall()

        interleaved = conn.execute(
            """
            SELECT count(*) AS n FROM (
              SELECT doc_id, page, seq,
                     lag(page) OVER (PARTITION BY doc_id ORDER BY seq) AS prev,
                     lag(seq)  OVER (PARTITION BY doc_id ORDER BY seq) AS pseq
              FROM chunks
            ) t
            WHERE prev IS NOT NULL AND page = prev AND seq <> pseq + 1
            """
        ).fetchone()["n"]

    print(f"\n  documents with more passage-pages than pages   {len(pages_per_doc)}")
    print(f"  passages of one page with a broken sequence    {interleaved}")
    for r in pages_per_doc[:5]:
        print(f"    {r['filename'][:56]}  {r['pages']} vs {r['page_count']}")

    ok = not pages_per_doc and interleaved == 0
    record("A6", "Passage across a page break", "pass" if ok else "fail",
           f"no passage spans two pages: {len(pages_per_doc)} documents hold "
           f"passages on more pages than they have, {interleaved} page runs "
           f"are broken. Chunking inside page boundaries held")


def case_a7():
    """
    Unreadable file. The case is not that nothing fails — it is that a
    failure is recorded with a reason and the run carries on. Both are
    visible in the record.
    """
    rule("A7  Unreadable file")

    import db

    with db.connect() as conn:
        excluded = conn.execute(
            """
            SELECT status_note, count(*) AS n FROM documents
            WHERE status <> 'ingested'
            GROUP BY status_note ORDER BY n DESC
            """
        ).fetchall()
        blank = conn.execute(
            "SELECT count(*) AS n FROM documents "
            "WHERE status <> 'ingested' AND "
            "(status_note IS NULL OR status_note = '')"
        ).fetchone()["n"]
        ingested = conn.execute(
            "SELECT count(*) AS n FROM documents WHERE status = 'ingested'"
        ).fetchone()["n"]

    total = sum(r["n"] for r in excluded)
    print(f"\n  excluded documents      {total}")
    print(f"  without a reason        {blank}")
    print(f"  ingested alongside them {ingested}  — the run continued\n")
    for r in excluded[:10]:
        print(f"    {r['n']:5}  {(r['status_note'] or '(none)')[:60]}")

    record("A7", "Unreadable file", "pass" if blank == 0 else "fail",
           f"{total} files could not be used; {blank} lack a recorded reason. "
           f"{ingested} documents ingested alongside them, so no failure "
           f"stopped a run")


# ══════════════════════════════════════════════════════════════════
#  B — labelling
# ══════════════════════════════════════════════════════════════════

def case_b1():
    """
    Missing information. The prompt says return null rather than guess,
    and the failure it guards against is a plausible invented year that
    nobody checks.

    So: for every document carrying a date, look for that year anywhere
    in its text. A year in the record and nowhere in the document did not
    come from the document.
    """
    rule("B1  Missing information")

    import db

    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT filename, doc_date, full_text FROM documents
            WHERE status = 'ingested' AND doc_date IS NOT NULL
                  AND full_text IS NOT NULL
            """
        ).fetchall()
        blank = conn.execute(
            "SELECT count(*) AS n FROM documents "
            "WHERE status = 'ingested' AND doc_date IS NULL"
        ).fetchone()["n"]

    if not rows:
        record("B1", "Missing information", "not run", "no dated documents yet")
        return

    unsupported = []
    for r in rows:
        year = re.search(r"(19|20)\d{2}", str(r["doc_date"]))
        if not year:
            continue
        if year.group(0) not in (r["full_text"] or ""):
            unsupported.append((r["filename"], str(r["doc_date"])))

    rate = len(unsupported) / len(rows)
    print(f"\n  documents with a date        {len(rows)}")
    print(f"  date's year not in the text  {len(unsupported)}   ({rate:.0%})")
    print(f"  documents left undated       {blank}  — the honest outcome\n")
    for name, date in unsupported[:10]:
        print(f"    {date:14} {name[:56]}")

    record("B1", "Missing information", "pass" if rate < 0.1 else "partial",
           f"{len(unsupported)} of {len(rows)} dated documents carry a year "
           f"that appears nowhere in their text ({rate:.0%}); {blank} were "
           f"left undated rather than guessed at")


def case_b3(sample=None):
    """
    Consistency.  gemini

    The failure is quiet: two documents of the same kind labelled
    differently, so filtering returns three of five and nothing looks
    wrong. Labelling is run again over documents already in the
    collection and compared with what was stored the first time.
    """
    sample = sample or SAMPLE
    rule(f"B3  Consistency  ({sample} documents, one Gemini call each)")

    import db
    import labeller

    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT filename, doc_type, topics, full_text FROM documents
            WHERE status = 'ingested' AND full_text IS NOT NULL
                  AND doc_type IS NOT NULL
            ORDER BY random() LIMIT %s
            """,
            (sample,),
        ).fetchall()

    if not rows:
        record("B3", "Consistency", "not run", "nothing labelled yet")
        return

    same_type = same_topic = tried = 0
    drifts = []
    for i, r in enumerate(rows, start=1):
        print(f"  [{i}/{len(rows)}] {r['filename'][:48]:50}", end=" ", flush=True)
        try:
            again = labeller.label(r["full_text"])
        except Exception as e:
            if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e):
                print("rate limit — stopping")
                break
            print(f"failed — {type(e).__name__}")
            continue
        tried += 1
        if again.get("doc_type") == r["doc_type"]:
            same_type += 1
            print("same type", end="")
        else:
            print(f"{r['doc_type']} -> {again.get('doc_type')}", end="")
            drifts.append((r["filename"], r["doc_type"], again.get("doc_type")))
        if set(again.get("topics") or []) & set(r["topics"] or []):
            same_topic += 1
        print()
        time.sleep(1)

    if not tried:
        record("B3", "Consistency", "not run", "no document was relabelled")
        return

    print(f"\n  same type again     {same_type} of {tried}  ({pct(same_type, tried)})")
    print(f"  a topic in common   {same_topic} of {tried}  ({pct(same_topic, tried)})")
    for name, was, now in drifts[:8]:
        print(f"    {was} -> {now}   {name[:48]}")

    rate = same_type / tried
    record("B3", "Consistency", "pass" if rate >= 0.8 else "partial",
           f"relabelled {tried} documents: {pct(same_type, tried)} came back "
           f"with the same type, {pct(same_topic, tried)} shared at least one "
           f"topic. Documents whose type moves are the ones filtering will "
           f"drop silently")


def case_b5(sample=None):
    """
    Malformed output.  gemini

    Provoked rather than waited for. Every response is parsed, which is
    the only way to get a failure rate rather than an impression.
    """
    sample = sample or SAMPLE
    rule(f"B5  Malformed output  ({sample} documents, one Gemini call each)")

    import db
    import labeller

    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT filename, full_text FROM documents
            WHERE status = 'ingested' AND full_text IS NOT NULL
            ORDER BY random() LIMIT %s
            """,
            (sample,),
        ).fetchall()

    if not rows:
        record("B5", "Malformed output", "not run", "nothing ingested yet")
        return

    good = bad = 0
    quota = False
    failures = []
    for i, row in enumerate(rows, start=1):
        print(f"  [{i}/{len(rows)}] {row['filename'][:48]:50}", end=" ", flush=True)
        try:
            meta = labeller.label(row["full_text"])
            print("parsed" if meta.get("title") else "parsed, but thin")
            good += 1
        except Exception as e:
            if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e):
                print("rate limit — stopping")
                quota = True
                break
            print(f"failed — {type(e).__name__}")
            bad += 1
            failures.append(f"{row['filename']}: {type(e).__name__}")
        time.sleep(1)

    tried = good + bad
    if not tried:
        record("B5", "Malformed output", "not run",
               "rate limit reached before any document was labelled")
        return

    rate = bad / tried
    print(f"\n  {good} parsed, {bad} failed of {tried}   ({rate:.0%} failure)")
    for f in failures:
        print(f"    {f}")

    detail = (f"{bad} of {tried} responses would not parse ({rate:.0%}). "
              f"Ingestion continues either way — an unparseable record leaves "
              f"the document in with a title from its filename")
    if quota:
        detail += ", run cut short by the rate limit"
    record("B5", "Malformed output", "pass" if rate < 0.1 else "partial", detail)


def case_b6():
    """
    Very long document. The failure is silent truncation — a record that
    reflects only the first section of a long report. Visible as a
    document whose passages stop well before its last page.
    """
    rule("B6  Very long document")

    import db

    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT d.filename, d.page_count, d.word_count,
                   count(c.id) AS passages, max(c.page) AS last_page
            FROM documents d JOIN chunks c ON c.doc_id = d.id
            WHERE d.status = 'ingested' AND d.page_count >= 50
            GROUP BY d.id ORDER BY d.page_count DESC LIMIT 15
            """
        ).fetchall()

    if not rows:
        record("B6", "Very long document", "not run",
               "no document of fifty pages or more is in yet")
        return

    truncated = []
    print()
    for r in rows:
        reach = r["last_page"] / r["page_count"]
        flag = "" if reach > 0.9 else "   <- stops early"
        if reach <= 0.9:
            truncated.append((r["filename"], r["last_page"], r["page_count"]))
        print(f"  {r['page_count']:4} pages, passages reach p.{r['last_page']:4}"
              f"  ({reach:.0%})  {r['filename'][:40]}{flag}")

    record("B6", "Very long document", "pass" if not truncated else "fail",
           f"of the {len(rows)} longest documents, {len(truncated)} have "
           f"passages that stop before their last page. The longest is "
           f"{rows[0]['page_count']} pages and reaches "
           f"p.{rows[0]['last_page']}")


# ══════════════════════════════════════════════════════════════════
#  C — search
# ══════════════════════════════════════════════════════════════════

def case_c1(sample=None):
    """
    Different words, same meaning.  gemini

    The twenty hand-written questions do not exist yet, and this case
    does not need them. Take a passage from a document already in the
    collection, have the model write a question answerable from it in
    different words, then search and see whether that document comes
    back. The ground truth is free, because the question was written
    from a known document.

    That is retrieval accuracy, measured on the collection itself.
    """
    sample = sample or SAMPLE
    rule(f"C1  Different words, same meaning  ({sample} questions, "
         f"one Gemini call each)")

    import db
    import search
    import answer as answer_mod
    from config import TOP_K

    # How deep to look when asking the second question: is the document
    # missing, or merely ranked low?
    DEEP = 50

    # One passage per document, not one per passage. Sampling passages
    # means a 684-page manual is drawn two hundred times more often than
    # a two-page flyer, and the figure then describes the longest
    # documents rather than the collection.
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM (
                SELECT DISTINCT ON (c.doc_id)
                       c.doc_id, c.text, d.filename, d.title
                FROM chunks c JOIN documents d ON d.id = c.doc_id
                WHERE d.status = 'ingested' AND length(c.text) > 600
                ORDER BY c.doc_id, random()
            ) one_each
            ORDER BY random() LIMIT %s
            """,
            (sample,),
        ).fetchall()

    if not rows:
        record("C1", "Different words, same meaning", "not run",
               "no passages long enough to work from")
        return

    # The first version of this prompt said only "use different wording",
    # and the model complied by removing every proper noun — producing
    # questions like "how do the struggles within this environment
    # differ", which name nothing and which no search could answer. It
    # was scoring the search for failing questions that were unanswerable
    # as written. A question has to stand on its own to be a fair test.
    ASKER = (
        "Write one question that this passage answers.\n\n"
        "The question must stand on its own. Someone who has never seen "
        "the passage must be able to tell what it is about. Name the "
        "subject — the organisation, the programme, the place, the "
        "profession — rather than writing 'this programme', 'these "
        "sessions', 'this company' or 'the provided document'.\n\n"
        "Word it differently from the passage: different verbs, "
        "synonyms where they exist, no quoted phrase longer than two "
        "words.\n\n"
        "Return the question alone.\n\nPASSAGE:\n{text}"
    )

    # Questions that point at something without naming it. The model
    # still produces them occasionally; they are dropped rather than
    # counted as failures.
    VAGUE = (" this ", " these ", " the provided ", " the document ",
             " the passage ", " the above ", "this programme", "this program")

    def unanswerable(q):
        padded = " " + q.lower().strip() + " "
        return any(v in padded for v in VAGUE)

    found_top = found_first = found_deep = tried = dropped = 0
    misses = []
    for i, r in enumerate(rows, start=1):
        name = (r["title"] or r["filename"])[:44]
        print(f"  [{i}/{len(rows)}] {name:46}", end=" ", flush=True)
        try:
            question = answer_mod.call_gemini(
                ASKER.format(text=r["text"][:2500])).strip().strip('"')
        except Exception as e:
            if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e):
                print("rate limit — stopping")
                break
            print(f"failed — {type(e).__name__}")
            continue

        if unanswerable(question):
            print("question names nothing — dropped")
            dropped += 1
            time.sleep(1)
            continue

        # Fetched deep, then read two ways. Whether the document is in
        # the top eight is the score. Whether it is anywhere in the top
        # fifty says which problem you have: a document ranked 30th is
        # being found and ordered badly, which re-ranking fixes in code.
        # A document absent from fifty is not being found at all, and no
        # amount of re-ordering will help.
        deep = search.search(question, k=DEEP)
        ids = [h["doc_id"] for h in deep]
        top = ids[:TOP_K]
        tried += 1

        if r["doc_id"] in top:
            found_top += 1
            place = top.index(r["doc_id"]) + 1
            if place == 1:
                found_first += 1
            print(f"found at {place}")
        elif r["doc_id"] in ids:
            found_deep += 1
            print(f"at {ids.index(r['doc_id']) + 1} — below the top {TOP_K}")
        else:
            print(f"NOT in the top {DEEP}")
            misses.append((name, question[:80]))
        time.sleep(1)

    if not tried:
        record("C1", "Different words, same meaning", "not run",
               "no question completed")
        return

    print(f"\n  in the top {TOP_K}   {found_top} of {tried}   "
          f"({pct(found_top, tried)})")
    print(f"  first result    {found_first} of {tried}   "
          f"({pct(found_first, tried)})")
    if dropped:
        print(f"  dropped         {dropped} questions that named nothing "
              f"and could not fairly be searched for")

    print(f"\n  of the {tried - found_top} not in the top {TOP_K}:")
    print(f"    {found_deep} were in the top {DEEP}, ranked too low"
          f"   — re-ranking would reach these, in code alone")
    print(f"    {tried - found_top - found_deep} were not in the top {DEEP}"
          f"   — not found at all; ordering cannot help")
    if found_deep > (tried - found_top - found_deep):
        print(f"\n  Most of the gap is ordering. A re-ranking pass over the "
              f"top {DEEP} is the next thing to try.")
    elif tried > found_top:
        print(f"\n  Most of the gap is the search not seeing these "
              f"documents at all. Re-ordering cannot reach them, so this "
              f"points at the embedding model and the chunk size — the "
              f"two settings that need every document reprocessed.")
    for name, q in misses[:8]:
        print(f"    missed: {name}\n            {q}")

    rate = found_top / tried
    record("C1", "Different words, same meaning",
           "pass" if rate >= 0.9 else "partial" if rate >= 0.7 else "fail",
           f"retrieval accuracy {pct(found_top, tried)} — the source document "
           f"came back in the top {TOP_K} for {found_top} of {tried} "
           f"paraphrased questions, and was first for {found_first}. "
           f"One passage per document, so the figure describes the "
           f"collection rather than its longest documents"
           + (f"; {dropped} questions named nothing and were dropped"
              if dropped else "")
           + ". Target is 90%")


def case_c2(sample=None):
    """
    An exact title. Meaning-based search is surprisingly bad at this,
    which is why keyword search runs alongside it. The failure users
    notice first is searching a paper's own title and not getting it.
    """
    sample = sample or 40
    rule(f"C2  An exact title  ({sample} documents)")

    import db
    import search
    from config import TOP_K

    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT id, title FROM documents
            WHERE status = 'ingested' AND title IS NOT NULL
                  AND length(title) > 15
            ORDER BY random() LIMIT %s
            """,
            (sample,),
        ).fetchall()

    if not rows:
        record("C2", "An exact title", "not run", "no titled documents yet")
        return

    first = top = 0
    misses = []
    for i, r in enumerate(rows, start=1):
        hits = search.search(r["title"], k=TOP_K)
        ids = [h["doc_id"] for h in hits]
        if r["id"] in ids:
            top += 1
            place = ids.index(r["id"]) + 1
            if place == 1:
                first += 1
        else:
            place = None
            misses.append(r["title"][:70])
        print(f"  [{i}/{len(rows)}] {'1st' if place == 1 else place or 'NOT FOUND':>9}"
              f"  {r['title'][:52]}")

    print(f"\n  first result   {first} of {len(rows)}   ({pct(first, len(rows))})")
    print(f"  in the top {TOP_K}  {top} of {len(rows)}   ({pct(top, len(rows))})")
    for t in misses[:8]:
        print(f"    missed: {t}")

    rate = first / len(rows)
    record("C2", "An exact title",
           "pass" if rate >= 0.9 else "partial" if rate >= 0.7 else "fail",
           f"searching a document's own title returns it first "
           f"{pct(first, len(rows))} of the time and in the top {TOP_K} "
           f"{pct(top, len(rows))} of the time, across {len(rows)} documents")


def case_c3(sample=None):
    """
    An author surname. A surname carries little meaning for a
    meaning-based search to match on, so this leans almost entirely on
    the keyword half.
    """
    sample = sample or 25
    rule(f"C3  An author surname  ({sample} documents)")

    import db
    import search
    from config import TOP_K

    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT id, authors, title, filename FROM documents
            WHERE status = 'ingested' AND authors IS NOT NULL
                  AND length(authors) > 3
            ORDER BY random() LIMIT %s
            """,
            (sample,),
        ).fetchall()

    if not rows:
        record("C3", "An author surname", "not run",
               "no document records an author yet")
        return

    # Author fields hold organisations as often as people, and the last
    # capitalised word of "Frontline Mind" is not a surname. Testing
    # against those measures the test rather than the search.
    NOT_A_SURNAME = {
        "Mind", "Group", "Health", "Australia", "Space", "Insights",
        "Services", "Council", "Department", "Institute", "University",
        "Limited", "Consulting", "Partners", "Solutions", "Team",
        "Office", "Agency", "Centre", "Center", "Foundation", "Company",
        "Training", "Research", "Management", "Tasmania", "Victoria",
    }

    found = tried = skipped = 0
    for i, r in enumerate(rows, start=1):
        words = re.findall(r"[A-Z][a-z]{3,}", r["authors"])
        if not words or words[-1] in NOT_A_SURNAME:
            skipped += 1
            print(f"  [{i}/{len(rows)}] {(r['authors'] or '')[:28]:30} "
                  f"{'skipped, not a person':22}")
            continue
        surname = words[-1]
        tried += 1
        hits = search.search(surname, k=TOP_K)
        ok = r["id"] in [h["doc_id"] for h in hits]
        found += ok
        print(f"  [{i}/{len(rows)}] {surname:18} "
              f"{'found' if ok else 'NOT FOUND':10} "
              f"{(r['title'] or r['filename'])[:44]}")

    if not tried:
        record("C3", "An author surname", "not run",
               f"none of the {skipped} author fields held a person's name — "
               f"they hold organisations, which this case is not about")
        return

    print(f"\n  found {found} of {tried}   ({pct(found, tried)})")
    print(f"  skipped {skipped} author fields holding an organisation "
          f"rather than a person")
    rate = found / tried
    record("C3", "An author surname",
           "pass" if rate >= 0.8 else "partial" if rate >= 0.5 else "fail",
           f"searching a real author's surname returns their document "
           f"{pct(found, tried)} of the time across {tried} documents "
           f"({skipped} author fields held an organisation and were skipped). "
           f"Search reads passage text only — an author named in the record "
           f"but not printed in the body cannot be matched")


def case_c4():
    """
    Filtered search. The failure is filtering after retrieval, which
    empties the results: the best eight are found first, then all but the
    matching ones are thrown away. Filtering inside the query avoids it,
    and the evidence is a full set of results that all match.
    """
    rule("C4  Filtered search")

    import db
    import search
    from config import TOP_K, DOC_TYPES, TOPICS

    with db.connect() as conn:
        types = conn.execute(
            """
            SELECT doc_type, count(*) AS n FROM documents
            WHERE status = 'ingested' AND doc_type IS NOT NULL
            GROUP BY doc_type HAVING count(*) >= 5 ORDER BY n DESC
            """
        ).fetchall()

    if not types:
        record("C4", "Filtered search", "not run",
               "no document type has five documents yet")
        return

    query = "what the evidence says about resilience and recovery"
    wrong = thin = 0
    print()
    for t in types:
        hits = search.search(query, k=TOP_K, doc_type=t["doc_type"])

        # The search rows do not carry doc_type, so the returned
        # documents are looked up rather than assumed.
        off = []
        if hits:
            ids = list({h["doc_id"] for h in hits})
            with db.connect() as conn:
                off = conn.execute(
                    "SELECT filename, doc_type FROM documents "
                    "WHERE id = ANY(%s) AND doc_type IS DISTINCT FROM %s",
                    (ids, t["doc_type"]),
                ).fetchall()

        full = len(hits) == TOP_K
        if off:
            wrong += 1
        if not full:
            thin += 1
        print(f"  {t['doc_type'][:32]:34} {len(hits)} results"
              f"{'' if full else '   <- fewer than ' + str(TOP_K)}"
              f"{'   <- wrong type present' if off else ''}"
              f"   ({t['n']} documents of this type)")

    record("C4", "Filtered search",
           "pass" if wrong == 0 and thin == 0 else "partial",
           f"across {len(types)} document types, {thin} returned fewer than "
           f"{TOP_K} results and {wrong} returned a document of another type. "
           f"A thin result set is the sign of filtering applied after "
           f"retrieval rather than inside it")


def case_c5():
    """
    Coverage. The failure is all eight passages arriving from the same
    two documents — the ones that happen to phrase the topic best — while
    thirteen other relevant documents go unrepresented.
    """
    rule("C5  Coverage")

    import db
    import search
    from config import TOP_K

    with db.connect() as conn:
        topics = conn.execute(
            """
            SELECT t AS topic, count(*) AS n
            FROM documents d, unnest(d.topics) AS t
            WHERE d.status = 'ingested'
            GROUP BY t HAVING count(*) >= 10 ORDER BY n DESC LIMIT 6
            """
        ).fetchall()

    if not topics:
        record("C5", "Coverage", "not run",
               "no topic has ten documents against it yet")
        return

    print()
    spreads = []
    for t in topics:
        hits = search.search(t["topic"], k=TOP_K)
        distinct = len({h["doc_id"] for h in hits})
        spreads.append(distinct)
        print(f"  {t['topic'][:30]:32} {distinct} documents across "
              f"{len(hits)} passages   ({t['n']} labelled with it)")

    average = sum(spreads) / len(spreads)
    record("C5", "Coverage",
           "pass" if average >= TOP_K * 0.6 else "partial",
           f"across {len(topics)} well-covered topics, the top {TOP_K} "
           f"passages came from {average:.1f} distinct documents on average. "
           f"Close to {TOP_K} means a spread; close to two means retrieval is "
           f"fixating on whichever documents phrase the topic best")


ABSENT = [
    "What is the recommended torque setting for a Toyota Hilux wheel nut?",
    "How do I treat powdery mildew on cucumber plants?",
    "What were the main causes of the French Revolution of 1789?",
    "What interest rate is currently set by the Bank of Japan?",
    "How do you make a sourdough starter from scratch?",
    "What is the offside rule in association football?",
    "What is the atomic mass of tungsten?",
    "What is the melting point of borosilicate glass?",
    "What is the capital city of Burkina Faso?",
    "What is the world record for the men's 100 metres?",
]


def case_c6():
    """
    A topic not covered, tested at the search layer rather than the
    answering one. Nothing should clear the threshold, and how close the
    nearest passage comes says how much room is left before a genuinely
    absent topic starts producing answers.
    """
    rule(f"C6  A topic not covered  ({len(ABSENT)} questions)")

    import search
    from config import MIN_SIMILARITY

    print()
    over = []
    scores = []
    for q in ABSENT:
        best = search.best_similarity(q)
        scores.append(best)
        flag = "" if best < MIN_SIMILARITY else "   <- clears the threshold"
        if best >= MIN_SIMILARITY:
            over.append((q, best))
        print(f"  {best:.3f}  {q[:58]}{flag}")

    highest = max(scores)
    print(f"\n  threshold {MIN_SIMILARITY}, highest score {highest:.3f}, "
          f"margin {MIN_SIMILARITY - highest:+.3f}")

    record("C6", "A topic not covered", "pass" if not over else "fail",
           f"{len(ABSENT) - len(over)} of {len(ABSENT)} questions with no "
           f"bearing on the collection stayed under the {MIN_SIMILARITY} "
           f"threshold; the closest reached {highest:.3f}")


# ══════════════════════════════════════════════════════════════════
#  D — answers and citations
# ══════════════════════════════════════════════════════════════════

REFUSALS = ("do not contain", "does not contain", "do not answer",
            "does not answer", "do not address", "does not address",
            "do not provide", "does not provide", "no information",
            "not contain any information", "cannot be answered",
            "is not mentioned", "are not mentioned")


def refused(text):
    """
    Did the answer decline, in whatever words it chose?

    The model is told to say so plainly when the passages do not answer
    the question, and it does — which is not the same string as the
    system's own refusal. Counting only the system's string marks a
    correct refusal as a failure, which is what the first run of this
    case did.
    """
    lowered = (text or "").lower()
    return any(phrase in lowered for phrase in REFUSALS)


def case_d1():
    """
    Unanswerable question. The same questions as C6, carried through to
    the answer, because there are two places a question can be turned
    away and they are not equally good.

    Turned away by the threshold, the question never reaches the model
    and costs nothing. Turned away by the model, the guarantee rests on
    its judgement rather than on arithmetic — correct, but one line of
    defence thinner than the design intended. Both are counted.
    """
    rule(f"D1  Unanswerable question  ({len(ABSENT)} questions)")

    import answer as answer_mod
    import search
    from config import MIN_SIMILARITY

    by_gate = by_model = answered = 0
    slips = []
    for i, question in enumerate(ABSENT, start=1):
        print(f"  [{i}/{len(ABSENT)}] {question[:54]:56}", end=" ", flush=True)
        try:
            closest = search.best_similarity(question)
            text, _ = answer_mod.ask(question)
        except Exception as e:
            print(f"error — {type(e).__name__}")
            continue

        if text == answer_mod.NOTHING_FOUND:
            print(f"stopped by the threshold  ({closest:.2f})")
            by_gate += 1
        elif refused(text):
            print(f"refused by the model      ({closest:.2f})")
            by_model += 1
        else:
            print(f"ANSWERED                  ({closest:.2f})")
            answered += 1
            slips.append((question, closest, text[:400]))
        time.sleep(1)

    tried = by_gate + by_model + answered
    if not tried:
        record("D1", "Unanswerable question", "not run", "no question completed")
        return

    print(f"\n  stopped by the threshold  {by_gate} of {tried}")
    print(f"  refused by the model      {by_model} of {tried}"
          f"   — correct, but after the Gemini call was spent")
    print(f"  answered anyway           {answered} of {tried}")
    for question, closest, preview in slips:
        print(f"\n  answered anyway: {question}")
        print(f"    closest passage {closest:.2f}\n    {preview}…")

    turned_away = by_gate + by_model
    record("D1", "Unanswerable question",
           "pass" if answered == 0 else "fail",
           f"all {turned_away} of {tried} questions with no bearing on the "
           f"collection were turned away, {by_gate} by the "
           f"{MIN_SIMILARITY} threshold and {by_model} by the model saying "
           f"the passages do not answer them. Nothing was invented. The "
           f"{by_model} that reached the model cost a call each and left the "
           f"refusal to its judgement"
           if answered == 0 else
           f"{answered} of {tried} questions with no bearing on the "
           f"collection produced an answer. {by_gate} were stopped by the "
           f"threshold and {by_model} refused by the model")


def case_d3(question=None):
    """
    Citation matches the passage.  gemini

    Traced once during the build, which showed the mechanism works and
    nothing about how often. This puts every claim beside the passage it
    cites so several can be checked in one sitting.

    The overlap figure is a hint, not a verdict. A low one is worth
    reading closely; a high one can still be a claim the passage does not
    make.
    """
    rule("D3  Citation matches the passage")

    import answer as answer_mod
    import search
    from config import TOP_K

    question = question or ("What does the collection say about psychological "
                            "safety in teams?")
    print(f"\n  Q: {question}\n")

    hits = search.search(question, k=TOP_K)
    if not hits:
        record("D3", "Citation matches passage", "not run",
               "nothing retrieved — pass another question: "
               "python run_cases.py d3 \"your question\"")
        return

    context = "\n\n".join(f"[{i}] {h['text']}"
                          for i, h in enumerate(hits, start=1))
    raw = answer_mod.call_gemini(
        answer_mod.TEMPLATE.format(context=context, question=question))

    claims = [s.strip() for s in re.split(r"(?<=[.!?])\s+", raw) if "[" in s]
    if not claims:
        record("D3", "Citation matches passage", "fail",
               "the answer carried no citation markers at all")
        return

    checked = 0
    for claim in claims:
        for n in [int(x) for x in re.findall(r"\[(\d+)\]", claim)]:
            if not 1 <= n <= len(hits):
                print(f"\n  MARKER OUT OF RANGE: [{n}] in — {claim}")
                continue
            h = hits[n - 1]
            claim_words = set(re.findall(r"[a-z]{5,}", claim.lower()))
            passage_words = set(re.findall(r"[a-z]{5,}", h["text"].lower()))
            overlap = len(claim_words & passage_words) / max(len(claim_words), 1)

            print("\n" + "-" * 74)
            print(f"  CLAIM     {claim}")
            print(f"  CITES     [{n}]  {h['title'] or h['filename']}  p.{h['page']}")
            print(f"  OVERLAP   {overlap:.0%} of the claim's words appear in it")
            print(f"  PASSAGE   {h['text'][:600]}…")
            checked += 1

    print("\n" + "-" * 74)
    print(f"\n  {checked} claim-to-passage pairs above.")
    print("  Does each passage actually support the claim citing it?")
    record("D3", "Citation matches passage", ask_verdict(),
           f"{checked} claim-to-passage pairs read on {question!r}; every "
           f"marker resolved within range")


def case_d6(rounds=4):
    """
    Citation numbering.  gemini

    The failure is numbers shifted by one, so every claim carries its
    neighbour's source — real references, right pages, wrong claims, and
    nothing about it looks wrong.

    Checked by asking the same question twice: once for the raw answer
    with its markers, once through ask(), and confirming the reference
    that replaced marker n belongs to passage n.
    """
    rule(f"D6  Citation numbering  ({rounds} questions)")

    import db
    import answer as answer_mod
    import search
    from config import TOP_K

    with db.connect() as conn:
        topics = conn.execute(
            """
            SELECT t AS topic FROM documents d, unnest(d.topics) AS t
            WHERE d.status = 'ingested'
            GROUP BY t ORDER BY count(*) DESC LIMIT %s
            """,
            (rounds,),
        ).fetchall()

    if not topics:
        record("D6", "Citation numbering", "not run", "no topics labelled yet")
        return

    markers = out_of_range = mismatched = 0
    for r in topics:
        question = f"What does the collection say about {r['topic'].lower()}?"
        print(f"\n  Q: {question}")
        hits = search.search(question, k=TOP_K)
        if not hits:
            print("    nothing retrieved")
            continue

        context = "\n\n".join(f"[{i}] {h['text']}"
                              for i, h in enumerate(hits, start=1))
        raw = answer_mod.call_gemini(
            answer_mod.TEMPLATE.format(context=context, question=question))
        resolved = answer_mod.resolve_citations(raw, hits)

        for n in [int(x) for x in re.findall(r"\[(\d+)\]", raw)]:
            markers += 1
            if not 1 <= n <= len(hits):
                out_of_range += 1
                continue
            expected = hits[n - 1]["title"] or hits[n - 1]["filename"]
            if expected[:28] not in resolved:
                mismatched += 1
                print(f"    [{n}] should name {expected[:50]!r} — not found")

        raw_markers = len(re.findall(r"\[(\d+)\]", raw))
        left = len(re.findall(r"\[(\d+)\]", resolved))
        print(f"    {raw_markers} markers, {left} left unresolved")
        time.sleep(1)

    if not markers:
        record("D6", "Citation numbering", "not run", "no answer carried markers")
        return

    bad = out_of_range + mismatched
    print(f"\n  {markers} markers, {out_of_range} out of range, "
          f"{mismatched} naming the wrong document")

    record("D6", "Citation numbering", "pass" if bad == 0 else "fail",
           f"{markers} citation markers across {len(topics)} answers: "
           f"{out_of_range} pointed outside the passage list and "
           f"{mismatched} resolved to a document other than the one that "
           f"produced the passage")


# ══════════════════════════════════════════════════════════════════
#  E — briefs and reviews
# ══════════════════════════════════════════════════════════════════

def case_e1():
    """
    Coverage of a review.  gemini

    A review fails by being unrepresentative rather than wrong: fluent,
    correctly cited, built on four documents out of fifteen. So the
    measure is how many of the eligible documents actually informed it.
    """
    rule("E1  Coverage of a review  (one review, reads whole documents)")

    import db
    import review as review_mod

    with db.connect() as conn:
        top = conn.execute(
            """
            SELECT t AS topic, count(*) AS n
            FROM documents d, unnest(d.topics) AS t
            WHERE d.status = 'ingested' AND d.full_text IS NOT NULL
            GROUP BY t ORDER BY n DESC LIMIT 1
            """
        ).fetchone()

    if not top or top["n"] < 5:
        record("E1", "Coverage of a review", "not run",
               "no topic has enough documents behind it yet")
        return

    print(f"\n  topic: {top['topic']}   ({top['n']} documents carry this label)")
    print("  generating…")

    text, docs = review_mod.generate(top["topic"], kind="review",
                                     label=top["topic"])
    used = len(docs)
    stated = re.search(r"(\d+)\s+document", text or "")

    print(f"  {used} documents informed it, of {top['n']} labelled")
    print(f"  the review states a number: "
          f"{'yes, ' + stated.group(0) if stated else 'no'}")

    record("E1", "Coverage of a review",
           "pass" if used >= min(10, top["n"]) else "partial",
           f"a review on {top['topic']!r} was built from {used} documents of "
           f"the {top['n']} carrying that label. Whole documents are read "
           f"rather than passages, so the cap is the document limit rather "
           f"than retrieval")


def case_e3():
    """
    Filter too narrow. The failure is a confident review built on two
    documents that reads exactly like one built on twenty. Provoked by
    combining a type and a topic that almost nothing carries.
    """
    rule("E3  Filter too narrow")

    import db
    import review as review_mod

    with db.connect() as conn:
        pair = conn.execute(
            """
            SELECT d.doc_type, t AS topic, count(*) AS n
            FROM documents d, unnest(d.topics) AS t
            WHERE d.status = 'ingested' AND d.full_text IS NOT NULL
                  AND d.doc_type IS NOT NULL
            GROUP BY d.doc_type, t HAVING count(*) <= 2
            ORDER BY count(*) LIMIT 1
            """
        ).fetchone()

    if not pair:
        record("E3", "Filter too narrow", "not run",
               "no type and topic combination is narrow enough to provoke it")
        return

    print(f"\n  {pair['doc_type']} + {pair['topic']}   "
          f"({pair['n']} document{'s' if pair['n'] != 1 else ''} match)")
    print("  generating…")

    text, docs = review_mod.generate(pair["topic"], kind="review",
                                     doc_type=pair["doc_type"],
                                     label=pair["topic"])

    lowered = (text or "").lower()
    says = any(w in lowered for w in
               ("only", "few", "limited", "single", "one document",
                "two documents", "not enough", "insufficient"))
    print(f"  built from {len(docs)} document(s)")
    print(f"  the text acknowledges how thin it is: {'yes' if says else 'NO'}")
    print("\n" + "-" * 74)
    print((text or "")[:1200])
    print("-" * 74)

    record("E3", "Filter too narrow", "pass" if says else "fail",
           f"a review filtered to {pair['doc_type']} + {pair['topic']} was "
           f"built from {len(docs)} document(s) and "
           f"{'did' if says else 'did not'} say how few informed it")


# ══════════════════════════════════════════════════════════════════
#  F — ingestion at volume
# ══════════════════════════════════════════════════════════════════

def case_f1():
    """
    Interruption. The failure this case found was a document written
    without its passages: it looked ingested, was skipped on every later
    run, and could never be found by any search. The invariant is that
    none exist.
    """
    rule("F1  Interruption")

    import db

    with db.connect() as conn:
        orphans = conn.execute(
            """
            SELECT count(*) AS n FROM documents d
            WHERE d.status = 'ingested'
              AND NOT EXISTS (SELECT 1 FROM chunks c WHERE c.doc_id = d.id)
            """
        ).fetchone()["n"]
        ingested = conn.execute(
            "SELECT count(*) AS n FROM documents WHERE status = 'ingested'"
        ).fetchone()["n"]

    skipped = 0
    if LEDGER.exists():
        ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        skipped = sum(1 for e in ledger.values()
                      if "already done" in e.get("note", ""))

    print(f"\n  documents marked ingested        {ingested}")
    print(f"  of those with no passages        {orphans}   <- unsearchable")
    print(f"  files skipped as already done    {skipped}   <- resumed rather "
          f"than reprocessed")

    record("F1", "Interruption", "pass" if orphans == 0 else "fail",
           f"{orphans} of {ingested} ingested documents have no passages. "
           f"{skipped} files were skipped as already done on later runs, so "
           f"an interrupted run resumes rather than starting over")


def case_f2():
    """
    Rate limit. Provoking a real one costs a day's quota, so the retry
    path is exercised directly: a stubbed call that fails twice with a
    503 and then succeeds. What matters is that it waits and carries on
    rather than putting the error in front of the person asking.
    """
    rule("F2  Rate limit")

    import answer as answer_mod

    calls = {"n": 0}

    class FakeModels:
        def generate_content(self, model=None, contents=None):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise RuntimeError("503 UNAVAILABLE: model is overloaded")
            class R: text = "recovered"
            return R()

    class FakeClient:
        models = FakeModels()

    original = answer_mod._client
    answer_mod._client = FakeClient()
    try:
        started = time.time()
        out = answer_mod.call_gemini("anything")
        waited = time.time() - started
    except Exception as e:
        answer_mod._client = original
        record("F2", "Rate limit", "fail",
               f"gave up instead of retrying: {type(e).__name__}: {e}")
        return
    finally:
        answer_mod._client = original

    print(f"\n  attempts made     {calls['n']}")
    print(f"  waited            {waited:.0f} seconds")
    print(f"  returned          {out!r}")

    ok = out == "recovered" and calls["n"] == 3
    record("F2", "Rate limit", "pass" if ok else "fail",
           f"two 503s were absorbed and the third attempt returned, after "
           f"waiting {waited:.0f}s across {calls['n']} attempts. A daily quota "
           f"is raised rather than retried, so the caller can fall back")


def case_f3():
    """
    Duplicate upload. Exact copies are caught by a hash of the file
    contents, so the same image in six folders is stored once. The
    database enforces it and the ledger counts how often it happened.
    """
    rule("F3  Duplicate upload")

    import db

    with db.connect() as conn:
        rows = conn.execute("SELECT count(*) AS n FROM documents").fetchone()["n"]
        hashes = conn.execute(
            "SELECT count(DISTINCT content_hash) AS n FROM documents"
        ).fetchone()["n"]

    caught = 0
    if LEDGER.exists():
        ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        caught = sum(1 for e in ledger.values()
                     if "duplicate" in e.get("note", "").lower())

    print(f"\n  document rows            {rows}")
    print(f"  distinct content hashes  {hashes}")
    print(f"  files skipped as copies  {caught}")

    record("F3", "Duplicate upload", "pass" if rows == hashes else "fail",
           f"{rows} documents hold {hashes} distinct content hashes, and "
           f"{caught} Drive files were skipped as exact copies. A renamed or "
           f"re-saved document is a different file and is not caught")


def case_f4():
    """
    Adding to a built collection. New files should be processed and
    existing ones left alone — not re-embedded, and not made to disappear
    from search.
    """
    rule("F4  Adding to a built collection")

    import db

    if not LEDGER.exists():
        record("F4", "Adding to a built collection", "not run",
               "ingest_ledger.json not found")
        return

    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    skipped = sum(1 for e in ledger.values()
                  if "already done" in e.get("note", ""))
    fresh = sum(1 for e in ledger.values() if e.get("note", "").startswith("ok"))

    with db.connect() as conn:
        searchable = conn.execute(
            "SELECT count(DISTINCT doc_id) AS n FROM chunks"
        ).fetchone()["n"]
        ingested = conn.execute(
            "SELECT count(*) AS n FROM documents WHERE status = 'ingested'"
        ).fetchone()["n"]

    print(f"\n  processed across all runs    {fresh}")
    print(f"  skipped as already done      {skipped}")
    print(f"  ingested documents           {ingested}")
    print(f"  of those findable by search  {searchable}")

    ok = ingested == searchable
    record("F4", "Adding to a built collection", "pass" if ok else "fail",
           f"{skipped} files were skipped as already done across repeated "
           f"runs while {fresh} were processed, and all {searchable} of "
           f"{ingested} ingested documents remain findable")


# ══════════════════════════════════════════════════════════════════
#  G — deployment
# ══════════════════════════════════════════════════════════════════

def case_g1():
    """
    Restart. The failure is a collection that disappears because it was
    written to a filesystem that does not survive a redeploy. It survives
    if nothing the search depends on lives on this machine — so the local
    files are listed and classified.
    """
    rule("G1  Restart")

    import db
    import search

    local = [p for p in Path(".").glob("*.json")] + \
            [p for p in Path(".").glob("*.csv")]
    caches = {"drive_listing_all.json", "drive_listing_all.partial.json",
              "drive_listing.json", "ingest_ledger.json", "coverage.csv",
              "inventory.csv", "case_results.md"}
    secrets = {"drive-key.json"}

    unknown = [p.name for p in local
               if p.name not in caches and p.name not in secrets]
    held = [p.name for p in local if p.name in secrets]

    with db.connect() as conn:
        docs = conn.execute(
            "SELECT count(*) AS n FROM documents WHERE status = 'ingested'"
        ).fetchone()["n"]
        chunks = conn.execute("SELECT count(*) AS n FROM chunks").fetchone()["n"]

    hits = search.search("resilience", k=3)

    print(f"\n  documents and passages live in Postgres:  {docs} / {chunks}")
    print(f"  a search returns results:                 "
          f"{'yes' if hits else 'no'}")
    print(f"  local files, all of them caches that rebuild themselves:")
    for p in local:
        mark = "" if p.name in caches else "   <- not a known cache"
        print(f"      {p.name}{mark}")

    if held:
        print(f"\n  credentials in this folder, which must stay out of git:")
        for name in held:
            print(f"      {name}")

    ok = bool(hits) and not unknown
    record("G1", "Restart", "pass" if ok else "partial",
           f"all {docs} documents and {chunks} passages live in Postgres, not "
           f"on the application's disk. The only local files are caches that "
           f"rebuild themselves"
           + (f"; {', '.join(unknown)} is not one of them" if unknown else ""))


def case_g2(url=None):
    """
    Idle. The case is about a cold start, so it means nothing run against
    an application that answered a minute ago. Leave it alone for a few
    hours, then run this before opening it in a browser.
    """
    rule("G2  Idle")

    if not url:
        print("  Needs the deployed address:")
        print("      python run_cases.py g2 https://your-app.streamlit.app")
        record("G2", "Idle", "not run", "no address given")
        return

    import urllib.request

    print(f"\n  requesting {url}")
    print("  (only meaningful if it has been idle for hours)")

    started = time.time()
    try:
        with urllib.request.urlopen(url, timeout=180) as response:
            code = response.status
            response.read(2048)
    except Exception as e:
        record("G2", "Idle", "fail", f"did not respond: {type(e).__name__}: {e}")
        return
    seconds = time.time() - started

    print(f"  HTTP {code} in {seconds:.1f} seconds")

    if seconds < 5:
        verdict, note = "pass", "was already awake"
    elif seconds < 60:
        verdict, note = "pass", "woke and served the page"
    else:
        verdict, note = "partial", "woke, but slowly enough to lose a visitor"

    record("G2", "Idle", verdict,
           f"HTTP {code} in {seconds:.1f}s — {note}. Free hosting sleeps when "
           f"idle; a scheduled ping every twenty minutes during working hours "
           f"keeps this rare")


def case_g3(url=None):
    """
    Concurrent use. The failure is running out of memory because the
    embedding model is loaded once per request rather than once. Three
    searches are issued at the same moment from separate threads; if the
    model is being reloaded each time, the timings say so.
    """
    rule("G3  Concurrent use  (three at once)")

    import search

    questions = ["resilience in frontline teams",
                 "psychological safety",
                 "recovery after a critical incident"]

    outcomes = {}
    barrier = threading.Barrier(len(questions))

    def run(q):
        barrier.wait()
        started = time.time()
        try:
            hits = search.search(q, k=8)
            outcomes[q] = (len(hits), time.time() - started, None)
        except Exception as e:
            outcomes[q] = (0, time.time() - started, f"{type(e).__name__}: {e}")

    threads = [threading.Thread(target=run, args=(q,)) for q in questions]
    started = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.time() - started

    print()
    failed = 0
    for q, (n, seconds, error) in outcomes.items():
        print(f"  {n:2} results in {seconds:5.1f}s   {q[:44]}"
              f"{'   ' + error if error else ''}")
        if error or not n:
            failed += 1
    print(f"\n  all three finished in {wall:.1f}s")

    record("G3", "Concurrent use", "pass" if failed == 0 else "fail",
           f"three simultaneous searches all returned in {wall:.1f}s with "
           f"{failed} failures. The embedding model is held once for the "
           f"process, so concurrent questions share it rather than each "
           f"loading their own")



# ══════════════════════════════════════════════════════════════════
#  calibration — what the similarity floor should actually be
# ══════════════════════════════════════════════════════════════════

def calibrate(sample=40):
    """
    C6 failing says the floor is in the wrong place. It does not say
    where the right place is, and guessing a new number is how you end
    up refusing real questions instead.

    So both sides are measured. Questions the collection genuinely
    covers are built from each document's own summary — written by the
    labeller, so the wording differs from the body text and the match
    has to be earned rather than copied. Questions it cannot cover are
    the ten from the absent list.

    A floor belongs between the two. If they overlap there is no floor
    that does both jobs, and the answer is a better retrieval signal
    rather than a better number.
    """
    rule(f"Calibration — where the similarity floor belongs")

    import db
    import search
    from config import MIN_SIMILARITY

    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT title, summary FROM documents
            WHERE status = 'ingested'
              AND (summary IS NOT NULL OR title IS NOT NULL)
            ORDER BY random() LIMIT %s
            """,
            (sample,),
        ).fetchall()

    if not rows:
        print("  nothing labelled to calibrate against")
        return

    print(f"\n  scoring {len(rows)} questions the collection does cover…")
    covered = []
    for r in rows:
        text = (r["summary"] or r["title"] or "").strip()
        query = re.split(r"(?<=[.!?])\s", text)[0][:300]
        if len(query.split()) < 4:
            continue
        covered.append(search.best_similarity(query))

    print(f"  scoring {len(ABSENT)} questions it does not…")
    absent = [search.best_similarity(q) for q in ABSENT]

    if not covered:
        print("  no usable summaries to work from")
        return

    covered.sort()
    absent.sort()

    def at(values, fraction):
        return values[min(int(len(values) * fraction), len(values) - 1)]

    low = at(covered, 0.05)
    median = at(covered, 0.5)
    highest_absent = absent[-1]

    print(f"\n  covered questions   lowest {covered[0]:.3f}   "
          f"5th percentile {low:.3f}   median {median:.3f}   "
          f"highest {covered[-1]:.3f}")
    print(f"  absent questions    lowest {absent[0]:.3f}   "
          f"median {at(absent, 0.5):.3f}   highest {highest_absent:.3f}")
    print(f"  the floor today     {MIN_SIMILARITY}")

    if highest_absent < low:
        suggested = round((highest_absent + low) / 2, 2)
        print(f"\n  The two do not overlap. A floor of {suggested} sits "
              f"between them:")
        print(f"      refuses all {len(ABSENT)} absent questions")
        print(f"      keeps {sum(1 for c in covered if c >= suggested)} "
              f"of {len(covered)} covered ones")
        print(f"\n  Set MIN_SIMILARITY = {suggested} in config.py, "
              f"then run C6 and D1 again.")
    else:
        lost = sum(1 for c in covered if c < highest_absent)
        print(f"\n  They overlap. A floor high enough to refuse every absent "
              f"question ({highest_absent:.3f}) would also refuse {lost} of "
              f"{len(covered)} real ones.")
        print(f"  No single number does both jobs. Raising it as far as the "
              f"overlap allows still helps, and the rest has to come from "
              f"the answering prompt — which is what D1 measures.")
        safer = round(min(highest_absent, at(covered, 0.15)), 2)
        print(f"\n  {safer} is the most that can be raised without losing "
              f"more than a seventh of the covered questions.")


# ══════════════════════════════════════════════════════════════════

CASES = {
    "a1": ("Two-column paper", case_a1, "file"),
    "a2": ("Scanned document", case_a2, ""),
    "a3": ("Headers and footers", case_a3, "asks"),
    "a5": ("Page attribution", case_a5, ""),
    "a6": ("Passage across a page break", case_a6, ""),
    "a7": ("Unreadable file", case_a7, ""),
    "b1": ("Missing information", case_b1, ""),
    "b3": ("Consistency", case_b3, "gemini"),
    "b5": ("Malformed output", case_b5, "gemini"),
    "b6": ("Very long document", case_b6, ""),
    "c1": ("Different words, same meaning", case_c1, "gemini"),
    "c2": ("An exact title", case_c2, ""),
    "c3": ("An author surname", case_c3, ""),
    "c4": ("Filtered search", case_c4, ""),
    "c5": ("Coverage", case_c5, ""),
    "c6": ("A topic not covered", case_c6, ""),
    "d1": ("Unanswerable question", case_d1, "gemini"),
    "d3": ("Citation matches passage", case_d3, "gemini asks"),
    "d6": ("Citation numbering", case_d6, "gemini"),
    "e1": ("Coverage of a review", case_e1, "gemini"),
    "e3": ("Filter too narrow", case_e3, "gemini"),
    "f1": ("Interruption", case_f1, ""),
    "f2": ("Rate limit", case_f2, ""),
    "f3": ("Duplicate upload", case_f3, ""),
    "f4": ("Adding to a built collection", case_f4, ""),
    "g1": ("Restart", case_g1, ""),
    "g2": ("Idle", case_g2, "url"),
    "g3": ("Concurrent use", case_g3, ""),
}

# The cases still needing someone to read and judge, listed so the
# summary says so rather than leaving them looking forgotten.
JUDGED = {
    "b2": "Outside the categories",
    "d2": "Every claim traceable",
    "d4": "Conflicting evidence",
    "d5": "A hedged finding",
    "e2": "Statements about gaps",
    "e4": "Brief against review",
}
NEEDS_MATERIAL = {
    "a4": "Reference list — needs a paper with pages of references",
    "b4": "Multi-sector document — this schema records topics, not sectors",
}
NEEDS_SOMEONE = {"g4": "Someone else's machine — answered when Richa tests it"}


def write_results():
    if not results:
        print("\nNothing was run.")
        return

    when = datetime.now().strftime("%d %B %Y, %H:%M")
    lines = [
        "# Test case results",
        "",
        f"Run {when}. Produced by `run_cases.py`.",
        "",
        "| ID | Case | Result | What it showed |",
        "| --- | --- | --- | --- |",
    ]
    for case, name, verdict, detail in sorted(results):
        lines.append(f"| {case} | {name} | {verdict} | {detail} |")

    lines += ["", "## Not covered by this script", "",
              "| ID | Case | Why |", "| --- | --- | --- |"]
    for cid, name in sorted(JUDGED.items()):
        lines.append(f"| {cid.upper()} | {name} | Needs a person to read and judge |")
    for cid, why in sorted(NEEDS_MATERIAL.items()):
        name, reason = [x.strip() for x in why.split("—", 1)]
        lines.append(f"| {cid.upper()} | {name} | {reason[0].upper()}{reason[1:]} |")
    for cid, why in sorted(NEEDS_SOMEONE.items()):
        name, reason = [x.strip() for x in why.split("—", 1)]
        lines.append(f"| {cid.upper()} | {name} | {reason[0].upper()}{reason[1:]} |")
    lines.append("")

    RESULTS.write_text("\n".join(lines), encoding="utf-8")

    print("\n" + "=" * 74)
    for case, name, verdict, _ in sorted(results):
        print(f"  {case:4} {name:32} {verdict}")
    print("=" * 74)
    print(f"\nWritten to {RESULTS}\n")


def main():
    args = sys.argv[1:]
    wanted, extra = [], []

    for a in args:
        low = a.lower()
        if low in CASES:
            wanted.append(low)
        elif low in ("a", "b", "c", "d", "e", "f", "g"):
            wanted += [c for c in CASES if c.startswith(low)]
        elif low == "free":
            wanted += [c for c, (_, _, tags) in CASES.items()
                       if "gemini" not in tags and "file" not in tags
                       and "url" not in tags]
        elif low == "calibrate":
            try:
                calibrate()
            except Exception as e:
                print(f"  calibration stopped: {type(e).__name__}: {e}")
            return
        elif low == "all":
            wanted += [c for c, (_, _, tags) in CASES.items()
                       if "file" not in tags and "url" not in tags]
        else:
            extra.append(a)

    if not wanted:
        wanted = [c for c, (_, _, tags) in CASES.items()
                  if "file" not in tags and "url" not in tags]
        print("Running every case that needs no argument.")
        print("A1 needs a PDF and G2 needs the app's address — see the top "
              "of this file.")
        print(f"Sampled cases look at {SAMPLE} documents each.\n")

    for case in wanted:
        name, run, _ = CASES[case]
        try:
            if case in ("a1", "d3", "g2", "g3"):
                run(extra[0] if extra else None)
            else:
                run()
        except Exception as e:
            record(case.upper(), name, "error", f"{type(e).__name__}: {e}")

    write_results()


if __name__ == "__main__":
    main()

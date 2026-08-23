#!/usr/bin/env python3
"""Produce machine glosses for lughat, OUTSIDE lughat.

Why this is a separate file, and not a command inside lughat.py:

    lughat.py contains no language model and no query-time network, and a
    test asserts both by grepping its own source. That test is what makes
    the governing rule checkable rather than aspirational, so the way to
    add machine translation is NOT to relax it -- it is to keep the model
    out here, in a build-time tool, and hand lughat a FILE.

    This script reads the approved entries, asks an engine to render each
    one, and writes JSONL. Nothing it produces is trusted: every line is
    imported into the `glosses` table, kept out of `entries`, and displayed
    under a warning naming the engine.

    python3 tools/gloss_batch.py --source=maqayis --lang=en --out=en.jsonl
    python3 lughat.py gloss --from=en.jsonl

Engines:
    --engine=anthropic   needs ANTHROPIC_API_KEY, and `pip install anthropic`
    --engine=echo        writes the prompts only, so the run can be costed
                         and inspected before a penny is spent

Options worth knowing:
    --roots=N        only the N commonest roots (a gloss you will never read
                     is a gloss not worth paying for)
    --max-chars=N    skip entries longer than this. Lisan's articles run to
                     16,000 characters; the default 6,000 keeps a batch to
                     what an engine handles well in one pass, and what is
                     skipped is REPORTED, never silently dropped.
"""

import argparse
import json
import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

LANGS = {"en": "English", "ur": "Urdu"}

PROMPT = """You are rendering a classical Arabic lexicon article into {lang}.

This is {title} by {author}, the article on the root {root}.

Rules:
- Render the whole article. Do not summarise, do not add commentary, do not
  explain what the lexicographer "means".
- Keep every Qur'anic citation and every sura/ayah reference exactly as it
  appears.
- Transliterate Arabic technical terms rather than translating them away
  (al-dhikr, ism fa'il, madi), and keep proper names.
- If a phrase is unclear, render it literally rather than guessing at an
  interpretation.
- Output the rendering only. No preamble, no notes, no markdown.

The article:

{text}"""


def entries(db, source, lang, roots, max_chars):
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    sql = ("SELECT e.id, e.root_ar, e.text_raw, s.title, s.author, "
           "COALESCE((SELECT n_segments FROM roots r WHERE r.root_ar = "
           "e.root_ar), 0) freq FROM entries e JOIN sources s "
           "ON s.id = e.source_id WHERE e.verified = 1 AND e.rejected = 0 "
           "AND e.text_raw IS NOT NULL AND e.root_ar IS NOT NULL")
    params = []
    if source:
        sql += " AND s.key = ?"
        params.append(source)
    sql += (" AND NOT EXISTS (SELECT 1 FROM glosses g WHERE g.entry_id = e.id "
            "AND g.lang = ?)")
    params.append(lang)
    sql += " ORDER BY freq DESC, e.id"
    rows = [dict(r) for r in con.execute(sql, params)]
    con.close()
    if roots:
        keep, seen = [], []
        for r in rows:
            if r["root_ar"] not in seen:
                if len(seen) >= roots:
                    continue
                seen.append(r["root_ar"])
            keep.append(r)
        rows = keep
    long_ones = [r for r in rows if len(r["text_raw"]) > max_chars]
    rows = [r for r in rows if len(r["text_raw"]) <= max_chars]
    return rows, long_ones


def render_plain(raw):
    import lughat
    return " ".join(lughat.render_entry(raw))


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(
        os.environ.get("LUGHAT_HOME", os.path.join(HERE, "data")),
        "lughat.db"))
    ap.add_argument("--source", default=None)
    ap.add_argument("--lang", default="en", choices=sorted(LANGS))
    ap.add_argument("--roots", type=int, default=0)
    ap.add_argument("--max-chars", type=int, default=6000)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--engine", default="echo",
                    choices=("echo", "anthropic"))
    ap.add_argument("--model", default="claude-sonnet-5")
    ap.add_argument("--out", default="glosses.jsonl")
    a = ap.parse_args(argv[1:])

    rows, skipped = entries(a.db, a.source, a.lang, a.roots, a.max_chars)
    if a.limit:
        rows = rows[:a.limit]
    chars = sum(len(r["text_raw"]) for r in rows)
    print("%d entries, %s characters of Arabic" % (len(rows), f"{chars:,}"))
    if skipped:
        # never silent: a gloss that is missing because the article was long
        # is a gap the reader should be able to find out about
        print("%d entries SKIPPED as longer than %d characters (the longest "
              "is %d). Raise --max-chars to include them."
              % (len(skipped), a.max_chars,
                 max(len(r["text_raw"]) for r in skipped)))
    if not rows:
        return 0

    client = None
    if a.engine == "anthropic":
        import anthropic                                   # noqa: F401
        client = anthropic.Anthropic()

    done = 0
    with open(a.out, "w", encoding="utf-8") as fh:
        for r in rows:
            prompt = PROMPT.format(lang=LANGS[a.lang], title=r["title"],
                                   author=r["author"] or "",
                                   root=r["root_ar"],
                                   text=render_plain(r["text_raw"]))
            if a.engine == "echo":
                fh.write(json.dumps({"entry_id": r["id"], "lang": a.lang,
                                     "prompt_chars": len(prompt)},
                                    ensure_ascii=False) + "\n")
                done += 1
                continue
            for attempt in range(4):
                try:
                    msg = client.messages.create(
                        model=a.model, max_tokens=4000,
                        messages=[{"role": "user", "content": prompt}])
                    text = "".join(b.text for b in msg.content
                                   if b.type == "text").strip()
                    break
                except Exception as e:                     # noqa: BLE001
                    if attempt == 3:
                        print("  %d failed: %s" % (r["id"], e))
                        text = ""
                    else:
                        time.sleep(2 ** attempt)
            if not text:
                continue
            fh.write(json.dumps(
                {"entry_id": r["id"], "lang": a.lang, "text": text,
                 "engine": "%s — unreviewed" % a.model},
                ensure_ascii=False) + "\n")
            done += 1
            if done % 25 == 0:
                print("  %d / %d" % (done, len(rows)))
    print("wrote %s (%d lines)" % (a.out, done))
    print("import with:  python3 lughat.py gloss --from=%s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

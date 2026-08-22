#!/usr/bin/env python3
"""Machine-translate the lexicons' Arabic into Urdu, offline, into `glosses`.

WHY THIS IS A SEPARATE FILE
---------------------------
lughat.py is one file, stdlib only, and offline after `setup`. That is not a
style preference: it is why the query path can be trusted to be pure
retrieval. A neural translator is the opposite of all three -- a gigabyte of
weights, a stack of third-party packages, and a model that generates text.

So it lives out here, and it only ever WRITES to the database. lughat.py
reads `glosses` and nothing in it imports torch, transformers or this script.
Run this when you want more Urdu; the reader never runs a model.

WHAT IT PRODUCES IS NOT A SOURCE
--------------------------------
Every row is stamped with the engine and model that made it, and the reading
page renders it outside the citation card, behind a switch that is off, under
a permanent label. Do not remove that stamp: it is the only thing standing
between a machine's guess and a scholar's name.

Expect it to be WRONG OFTEN. These are 10th-century lexicographical texts --
elided syntax, grammatical terminology, chains of transmission, and lines of
poetry quoted without introduction. NLLB is trained on modern prose. It will
return fluent, confident Urdu that misreads the register. That is the normal
outcome, not a bug to file.

INSTALL (once; ~600 MB of model after conversion)

    python3 -m pip install --user ctranslate2 transformers sentencepiece torch

    # torch is needed to CONVERT, not to run: the converter loads Meta's
    # published weights through transformers. Once nllb-600M-ct2 exists,
    # translation uses ctranslate2 alone and torch is never imported again.

    ~/Library/Python/3.9/bin/ct2-transformers-converter \
        --model facebook/nllb-200-distilled-600M \
        --output_dir ~/nllb-600M-ct2 --quantization int8

    # pip installs these scripts into a directory that is NOT on PATH on a
    # stock macOS (`python3 -c "import site;print(site.USER_BASE)"` + /bin),
    # which is why the converter is spelled out in full above.

USE

    python3 tools/gloss_urdu.py --model ~/nllb-600M-ct2 --source maqayis
    python3 tools/gloss_urdu.py --model ~/nllb-600M-ct2 --root سكن
    python3 tools/gloss_urdu.py --model ~/nllb-600M-ct2 --source lisan --limit 50

It is RESUMABLE: a paragraph already glossed by this engine is skipped, so
interrupting it costs only the paragraph in flight. Lisan is 9.2 MB and will
take hours; maqayis and mufradat are about 1.1 MB each.
"""

import argparse
import importlib.util
import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# NLLB's own language codes. Arabic -> Urdu is a DIRECT pair in NLLB-200:
# no English pivot, which matters because pivoting compounds the error twice
# over on a register the model is already weak at.
SRC_LANG = "arb_Arab"
TGT_LANG = "urd_Arab"

# NLLB's positional limit is 512 tokens and quality degrades well before it.
# Classical Arabic is often written with no sentence punctuation at all (the
# JK Lisan carries none), so splitting on '.' is not available -- chunks are
# taken on word boundaries under a character budget instead.
CHUNK_CHARS = 320


def load_lughat():
    """Import lughat.py for render_entry -- the ONE thing shared with it.

    The glosses must line up with the paragraphs the reader actually sees,
    and those come from render_entry's rules for OpenITI markup. Re-deriving
    them here would be trap 8 in a new place: two functions computing what is
    meant to be one thing, drifting apart silently."""
    spec = importlib.util.spec_from_file_location(
        "lughat", os.path.join(REPO, "lughat.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def chunks(text, budget=CHUNK_CHARS):
    """Split a paragraph into translatable pieces on word boundaries."""
    words, out, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > budget:
            out.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        out.append(cur)
    return out


class Translator:
    """ctranslate2 if it is installed, else transformers. Same interface."""

    def __init__(self, model_path):
        self.model_path = model_path
        self.kind = None
        try:
            import ctranslate2                      # noqa: F401
            import transformers                     # noqa: F401
            self._init_ct2()
        except ImportError:
            self._init_hf()

    def _init_ct2(self):
        import ctranslate2
        from transformers import AutoTokenizer
        self.kind = "ctranslate2"
        self.tok = AutoTokenizer.from_pretrained(
            "facebook/nllb-200-distilled-600M", src_lang=SRC_LANG)
        self.model = ctranslate2.Translator(self.model_path, device="cpu")
        self.name = os.path.basename(self.model_path.rstrip("/"))

    def _init_hf(self):
        try:
            from transformers import (AutoTokenizer,
                                      AutoModelForSeq2SeqLM)
        except ImportError:
            sys.exit(
                "No translation backend installed.\n\n"
                "  python3 -m pip install ctranslate2 transformers "
                "sentencepiece\n"
                "  ct2-transformers-converter "
                "--model facebook/nllb-200-distilled-600M \\\n"
                "      --output_dir ~/nllb-600M-ct2 --quantization int8\n\n"
                "or, slower:\n"
                "  python3 -m pip install torch transformers sentencepiece")
        self.kind = "transformers"
        self.tok = AutoTokenizer.from_pretrained(self.model_path,
                                                 src_lang=SRC_LANG)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(self.model_path)
        self.name = os.path.basename(self.model_path.rstrip("/"))

    def translate(self, texts):
        if self.kind == "ctranslate2":
            batch = [self.tok.convert_ids_to_tokens(self.tok.encode(t))
                     for t in texts]
            res = self.model.translate_batch(
                batch, target_prefix=[[TGT_LANG]] * len(batch),
                beam_size=4, max_decoding_length=512)
            out = []
            for r in res:
                toks = r.hypotheses[0]
                if toks and toks[0] == TGT_LANG:
                    toks = toks[1:]
                out.append(self.tok.decode(
                    self.tok.convert_tokens_to_ids(toks),
                    skip_special_tokens=True))
            return out
        enc = self.tok(texts, return_tensors="pt", padding=True,
                       truncation=True, max_length=512)
        gen = self.model.generate(
            **enc, forced_bos_token_id=self.tok.convert_tokens_to_ids(
                TGT_LANG), max_length=512, num_beams=4)
        return self.tok.batch_decode(gen, skip_special_tokens=True)


def targets(conn, lu, sources, root, limit):
    """(entry_id, para, arabic) still needing a gloss, commonest roots first."""
    sql = ("SELECT e.id, e.text_raw FROM entries e "
           "JOIN sources s ON s.id = e.source_id "
           "WHERE e.verified = 1 AND e.rejected = 0 "
           "AND e.text_raw IS NOT NULL AND s.key IN (%s)"
           % ",".join("?" * len(sources)))
    params = list(sources)
    if root:
        sql += " AND e.root_ar = ?"
        params.append(root)
    # the roots a reader actually meets first, as the review queue does
    sql += (" ORDER BY COALESCE((SELECT n_segments FROM roots r "
            "WHERE r.root_ar = e.root_ar), 0) DESC, e.id")
    out = []
    for row in conn.execute(sql, params):
        paras = lu.render_entry(row["text_raw"])
        for i, para in enumerate(paras):
            if para and para.strip():
                out.append((row["id"], i, para))
        if limit and len(out) >= limit:
            break
    return out[:limit] if limit else out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", required=True,
                    help="ct2 model dir, or a HF model id/path")
    # Same resolution order as lughat.py: LUGHAT_HOME wins, then the repo's
    # own data/. A git worktree has no data/ of its own, so a checkout of
    # this branch must be told where the database is rather than silently
    # creating an empty one beside itself.
    ap.add_argument("--db", default=os.path.join(
        os.environ.get("LUGHAT_HOME", os.path.join(REPO, "data")),
        "lughat.db"))
    ap.add_argument("--source", action="append", dest="sources",
                    choices=["maqayis", "mufradat", "lisan"],
                    help="repeatable; default is all three")
    ap.add_argument("--root", help="one root only")
    ap.add_argument("--limit", type=int, help="stop after N paragraphs")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true",
                    help="count the work and exit without loading a model")
    a = ap.parse_args(argv)
    sources = a.sources or ["maqayis", "mufradat", "lisan"]

    lu = load_lughat()
    if not os.path.exists(a.db):
        sys.exit("no database at %s\n"
                 "Pass --db /path/to/lughat.db, or set LUGHAT_HOME to the "
                 "directory holding it." % a.db)
    conn = sqlite3.connect(a.db)
    conn.row_factory = sqlite3.Row
    # the table is created by lughat's own migrate(); this script never
    # invents schema, so the two cannot disagree about its shape
    have = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE "
                        "type='table' AND name='glosses'").fetchone()[0]
    if not have:
        sys.exit("no `glosses` table -- run `python3 lughat.py test` once "
                 "against this database first, which migrates it.")

    work = targets(conn, lu, sources, a.root, a.limit)
    done = {(r[0], r[1]) for r in conn.execute(
        "SELECT entry_id, para FROM glosses WHERE lang='ur'")}
    work = [w for w in work if (w[0], w[1]) not in done]
    chars = sum(len(w[2]) for w in work)
    print("%d paragraphs to gloss (%s), %.2f MB of Arabic"
          % (len(work), "+".join(sources), chars / 1e6))
    if a.dry_run or not work:
        return 0

    tr = Translator(a.model)
    print("engine %s, model %s" % (tr.kind, tr.name))
    t0, n = time.time(), 0
    for i in range(0, len(work), a.batch):
        batch = work[i:i + a.batch]
        # a long paragraph is translated in pieces and rejoined; the piece
        # boundaries are ours, so they are not shown to the reader
        pieces, owner = [], []
        for j, (_eid, _para, ar) in enumerate(batch):
            for c in chunks(ar):
                pieces.append(c)
                owner.append(j)
        try:
            got = tr.translate(pieces)
        except Exception as e:                        # noqa: BLE001
            print("  batch %d failed (%s: %s) -- skipped"
                  % (i, type(e).__name__, e))
            continue
        joined = [""] * len(batch)
        for k, text in enumerate(got):
            joined[owner[k]] = (joined[owner[k]] + " " + text).strip()
        for (eid, para, _ar), ur in zip(batch, joined):
            if not ur.strip():
                continue
            conn.execute(
                "INSERT OR REPLACE INTO glosses "
                "(entry_id,para,lang,text,engine,model,created_at) "
                "VALUES (?,?,'ur',?,?,?,datetime('now'))",
                (eid, para, ur, "nllb", tr.name))
        conn.commit()
        n += len(batch)
        rate = n / max(1e-6, time.time() - t0)
        print("  %d/%d  %.1f para/s  eta %.0f min"
              % (n, len(work), rate, (len(work) - n) / max(rate, 1e-6) / 60))
    print("done: %d paragraphs, stamped engine=nllb model=%s" % (n, tr.name))
    print("Switch 'Urdu' on in the reading page to see them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

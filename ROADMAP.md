# Roadmap — Lughat / Miftāḥ al-Alfāẓ

Canonical plan. Ordered by **dependency**, not by preference: several items sit
later than the original priority list because something else must exist first.

## Where it stands

| | |
|---|---|
| Corpus | 128,219 segments · 77,429 words · 6,236 āyāt · 1,642 roots |
| Ṣarf | 6 abwāb + forms II–XIII + the rubāʿī; 2 refusals; 488 roots flagged for iʿlāl |
| Lexicon | Maqāyīs ingested — 4,628 entries, **all `verified = 0`**, 1,510 corpus roots covered |
| Tests | 42, in two sections (INTEGRITY, HONESTY) |
| Served | 1 entry. Everything else awaits review. |

---

## Phase 1 — Make the review gate survivable  ← **the critical path**

Nothing in the lexicon layer reaches the reader until a person approves it, so
**review throughput is the binding constraint on the whole project.** Not code.

The queue is smaller than it looks. Root frequency in the Qurʾān is steeply
skewed:

    top 100 roots  =  60.5% of root-bearing words
    top 300 roots  =  83.5%      (289 already have a Maqāyīs entry)
    top 500 roots  =  91.7%
    all 1,510 covered roots = 97.7%

The other ~3,100 entries are roots that never occur in the Qurʾān. For this
app they never need reviewing at all. `review` already offers entries
most-frequent-first, so the first sitting is the most valuable one.

**1a. A review surface (FastAPI + plain HTML, no build step).** Its first job
is *not* reading — it is approving. Keyboard-driven, entry text and citation
side by side, `direct` / `geminate` / `weak_final` visibly distinct. A terminal
prompt at one keystroke per entry is workable for 50 and punishing for 500.

**1b. Work the top 300.** ~83% of everything you will ever look up.

*Done when:* opening any common root shows Ibn Fāris with a volume and page.

## Phase 2 — More lexicons

Each ingest feeds the same queue, so **1a must exist first** or the queue
outruns the gate.

**2a. al-Rāghib, *al-Mufradāt fī Gharīb al-Qurʾān*** (OpenITI, d. 502). The
Qurʾān-specific lexicon — arguably more central to this tool than Maqāyīs, and
the reason to do it second is only that Maqāyīs proved the pipeline.

**2b. Lisān al-ʿArab** (OpenITI, d. 711) and **Lane** (public domain).
Watch the ordering scheme: Lisān and Qāmūs order by **last** radical, so root
extraction from headings must handle both or entries land under wrong roots.
Lane thins out badly after ق — he died partway through it.

*Done when:* three lexicons agree or visibly disagree on a root, in one view.

## Phase 3 — Finish the ṣarf layer

**3a. `roots.bab`, sourced.** Blocked by 2b. Maqāyīs does not state the
muḍāriʿ vowel (`بالكسر`/`بالضم`/`بالفتح` appear 19/15/24 times in 3.7 MB);
Lisān and Lane do. Store the quoted vowel statement verbatim with its page and
derive the bāb number by rule from it — the citation is the page, the number
follows.

**3b. iʿlāl / ibdāl for the 488 weak roots.** Write the rules in-repo and
verify against the Qurʾān itself: every generated form for a weak root that the
corpus attests must match EXACTLY. That turns 488 roots of hand-waving into a
measurable pass rate. Qutrub (GPL) for spot-checks, not as the engine.

*Done when:* `sarf قول` prints قَالَ, and the UNVERIFIED banner is the
exception rather than a third of the corpus.

## Phase 4 — Tafsir

OpenITI mARkdown: Ṭabarī, Qurṭubī, Ibn Kathīr, Rāzī, Ibn ʿĀshūr. Key at
āyah level first; add word level only where the mufassir quotes the lafẓ. The
hard part is the link, not the text.

## Phase 5 — Urdu scans

Page images plus a root→page index. **Nothing transcribed** — `text_raw` stays
NULL and `scan_uri` carries the content. Proves the scan-only path on real
data. Nastaliq OCR on a lithograph is not reliable enough for a religious
text and is not on this roadmap at any phase.

## Phase 6 — Synonyms and furūq

Mutaradifāt scans + al-ʿAskarī's *al-Furūq* (public domain, in OpenITI).

## Phase 7 — Ḥadīth concordance

LK Hadith Corpus or sunnah.com, root-tagged. Largest scope, least settled.

---

## Cross-cutting

**Licensing.** `sources.licence` and `sources.distributable` are kept accurate
per row so "what may this ever ship with?" stays answerable instead of
archaeological. Qāmūs al-Waḥīd, Mutaradifāt, Badawi & Abdel Haleem and Hans
Wehr are in copyright: local personal use only, never bundled. OpenITI is
CC BY-NC-SA — attribute, non-commercial, share-alike.

**The HONESTY suite grows with every layer.** Each new source is a new way to
attribute something to a scholar who did not say it.

## What will never be built

- A language model anywhere in the query path.
- A generated maṣdar for the thulāthī mujarrad.
- A bāb without a citation.
- OCR of lithographed Nastaliq presented as text.
- A skeleton match reported as attestation.

A visible gap is correct output.

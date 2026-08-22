# Roadmap — Lughat / Miftāḥ al-Alfāẓ

Canonical plan. Ordered by **dependency**, not by preference: several items sit
later than the original priority list because something else must exist first.

## Against the five requirements

The requirements are the spine. An earlier draft of this file was organised by
build dependency and quietly drifted from them — two sub-requirements had no
phase at all, and one was never addressed. Corrected here.

| # | Requirement | State |
|---|---|---|
| 1 | The root of the word | **Done** — deterministic, from the corpus |
| 1a | Explanation of the root *letters* — Ibn Jinnī, *Sirr Ṣināʿat al-Iʿrāb* | **Was missing.** Now Phase 5 |
| 1b | Ishtiqāq from Ibn Jinnī — *al-Khaṣāʾiṣ*, ishtiqāq akbar | **Was missing.** Now Phase 5 |
| 1c | Ishtiqāq ṣaghīr table | **Done** |
| 2 | How the word forms from the letters | **Half.** Ṣarf mechanics done; the word-centred view and the sourced aṣl are pending |
| 3 | Synonyms | Phase 7, with the furūq |
| 3 | **Opposites (aḍdād)** | **Was never addressed.** Now Phase 7, and needs a source |
| 4 | Dictionary + tafsir cards, exact text, selectable | Data scheduled; **the card UI itself was not.** Now Phase 3 |
| 5 | Same root elsewhere in the Qurʾān | **Done** |
| 5 | Same root in ḥadīth | Phase 9 |

### On requirement 2, and why it is the argument for the whole design

*masākīn* is the broken plural of **مَسْكَن**, a dwelling. The sense "life's
movement brought to a stop by hardship" belongs to **مِسْكِين**, a different
word from the same root. The instinct is right and the derivation attaches
itself to the neighbouring word — which is exactly why the tool quotes Ibn
Fāris's aṣl (*خلاف الاضطراب والحركة*) and shows the ṣarf mechanically, and
never narrates the connection itself.

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
Make the review gate survivable  ← **the critical path**

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
More lexicons

Each ingest feeds the same queue, so **the review surface must exist first** or the queue
outruns the gate.

**2a. al-Rāghib, *al-Mufradāt fī Gharīb al-Qurʾān*** (OpenITI, d. 502). The
Qurʾān-specific lexicon — arguably more central to this tool than Maqāyīs, and
the reason to do it second is only that Maqāyīs proved the pipeline.

**2b. Lisān al-ʿArab** (OpenITI, d. 711) and **Lane** (public domain).
Watch the ordering scheme: Lisān and Qāmūs order by **last** radical, so root
extraction from headings must handle both or entries land under wrong roots.
Lane thins out badly after ق — he died partway through it.

*Done when:* three lexicons agree or visibly disagree on a root, in one view.

## Phase 3 — The reading surface  *(requirement 4)*
The reading surface  *(requirement 4)*

Distinct from the review surface in Phase 1, and this is what you actually
described: a word in the muṣḥaf opens a stack of **cards, one per source**,
each showing that source's exact text with its citation, and a control to
choose which dictionaries and which mufassirūn are shown. A source with
nothing on this root shows an explicit empty card, not a hidden one — the
absence is information.

## Phase 4 — Finish the ṣarf layer
Finish the ṣarf layer

**3a. `roots.bab`, sourced.** Blocked by Phase 2. Maqāyīs does not state the
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

## Phase 5 — Ibn Jinnī  *(requirements 1a, 1b)*
Ibn Jinnī  *(requirements 1a, 1b)*

All four works your record names are already in the OpenITI repo cloned for
Maqāyīs — *al-Khaṣāʾiṣ*, *Sirr Ṣināʿat al-Iʿrāb*, *al-Munṣif*,
*al-Muḥtasab*. This is nearer than the earlier draft implied.

**3a. Ishtiqāq akbar, the mechanical half.** The six permutations of a
triliteral root, with which of them occur in the Qurʾān. Pure rule engine,
already working:

    س ك ن  ->  سكن 69 · نسك 7 · نكس 3 · كنس 1 · سنك — · كسن —
    ق و ل  ->  قول 1722 · the other five do not occur

Listing the permutations is derivation. Claiming they *orbit one idea* is Ibn
Jinnī's thesis and must be quoted, never asserted by the tool.

**3b. al-Khaṣāʾiṣ, the scholarly half.** 273 chapters, 1,358 page markers, but
organised by **topic, not by root** — so this is full-text retrieval of a
root's letters, returning the passage with its page. For most roots there will
be nothing, and *the tool must say so*. Ishtiqāq akbar is a minority method:
supporting insight after Ibn Fāris and al-Rāghib have established the meaning,
never primary evidence, and labelled as such in the interface.

**3c. *Sirr Ṣināʿat al-Iʿrāb*, letter by letter.** Ibn Jinnī on the phonetic
properties and semantic weight of each of the 29 letters — so each radical of
a root becomes clickable. The best witness has 269 section markers; the letter
chapters (*باب الهمزة*, *باب الباء*) are detectable but not cleanly marked, so
this needs the same care as the Maqāyīs headings.

*Done when:* a root shows its six permutations with Qurʾānic counts, each
radical opens Ibn Jinnī on that letter, and al-Khaṣāʾiṣ either quotes or
refuses.

## Phase 6 — Tafsir  *(requirement 4, second half)*
Tafsir  *(requirement 4, second half)*

OpenITI mARkdown: Ṭabarī, Qurṭubī, Ibn Kathīr, Rāzī, Ibn ʿĀshūr. Key at
āyah level first; add word level only where the mufassir quotes the lafẓ. The
hard part is the link, not the text.

## Phase 7 — Synonyms and opposites  *(requirement 3)*
Synonyms and opposites  *(requirement 3)*

**Synonyms** — Mutaradifāt scans plus al-ʿAskarī's *al-Furūq al-Lughawiyya*
(public domain, in OpenITI as 0395AbuHilalCaskari). The Furūq is the more
valuable half: it says what *separates* near-synonyms, which is the question
actually being asked.

**Opposites (aḍdād)** — no source is chosen yet. The classical literature is
Ibn al-Anbārī's *Kitāb al-Aḍdād* and al-Ṣaghānī's; whether either is in
OpenITI has not been checked. **Do not ship a computed antonym.** An opposite
that no lexicon states is a fabrication like any other.

## Phase 8 — Urdu scans
Urdu scans

Page images plus a root→page index. **Nothing transcribed** — `text_raw` stays
NULL and `scan_uri` carries the content. Proves the scan-only path on real
data. Nastaliq OCR on a lithograph is not reliable enough for a religious
text and is not on this roadmap at any phase.

## Phase 9 — Ḥadīth concordance  *(requirement 5, second half)*
Ḥadīth concordance  *(requirement 5, second half)*

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

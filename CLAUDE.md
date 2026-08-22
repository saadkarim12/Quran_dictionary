# CLAUDE.md — Lughat: a Qur'anic lexicography tool

## THE GOVERNING RULE

**No language model output may ever reach the user.**

The query path is pure retrieval from a database. Every user-visible string is
either:

  (a) verbatim text from a named source, carrying a page citation; or
  (b) the output of a deterministic rule engine whose rules are written down
      in this repository and readable by the user.

Where a rule does not determine the answer, the tool **REFUSES** and says so.

It never guesses. It never paraphrases a source. It never generates an
attribution.

**A visible gap is correct output.** A plausible fabrication attributed to a
named scholar is the worst possible failure of this program — worse than
crashing. If you are ever choosing between "emit something helpful-looking"
and "emit a refusal", emit the refusal.

### What this forbids, concretely

- No `import openai`, `import anthropic`, no HTTP call at query time, no
  "smart" fallback that fills a gap with prose.
- No summarising, glossing, translating, or "cleaning up" a source's words.
  `entries.text_raw` is copied byte-for-byte or it is NULL.
- No inventing a citation. If the volume/page is unknown, it is NULL and the
  entry is `verified = 0`, and `verified = 0` is never served.
- No presenting a *possible* form as an *attested* one. See "Attestation"
  below.
- No emitting a morphological form that the rule engine cannot actually derive
  (see "The two refusals").

### Enforcement points in the code

| Rule | Enforced by |
|---|---|
| `verified = 0` never served | Views `v_entries` / `v_tafsir`, enforced by **SQLite's authorizer callback**, not by pattern-matching the SQL |
| No generated maṣdar for the mujarrad | `Refusal` objects returned by the generator; the maṣdar slot for a mujarrad bāb has no template at all |
| Weak roots not silently emitted | `classify_root()` + `Form.verified` flag + loud banner |
| Skeleton ≠ attestation | `Attestation.kind` is `EXACT` or `SKELETON`; only `EXACT` sets `is_attestation` |
| Bāb not invented | `roots.bab` is a *sourced* column with `bab_source_id` / `bab_page`; NULL means unknown, and anything depending on the bāb refuses |

The HONESTY section of the test suite exists to make these fail **loudly** if
someone later "improves" the code in a way that breaks the governing rule.
Do not delete or weaken those tests. If a change makes an honesty test fail,
the change is wrong, not the test.

---

## The traps

These are real bugs that were hit and fixed. Do not re-introduce them.

### 1. Dagger alif (U+0670) is a diacritic in the encoding and a letter in the language

The mushaf writes *masākīn* as `مَسَٰكِينِ` — an alif drawn as a superscript
mark. If you strip U+0670 along with the fatḥa and the sukūn, *masākīn*
collapses to *miskīn* and a search for `مساكين` returns nothing.

But you cannot simply turn every dagger alif into an alif either: `رحمن` is
conventionally *typed* without the alif, while `مساكين` is *typed* with it.

**Therefore: index both readings.** Every searchable string gets two keys —
`norm_alif` (U+0670 → U+0627, then strip marks) and `norm_drop` (U+0670
deleted, then strip marks). A query is normalised both ways and matched
against both columns. This is not belt-and-braces; both are load-bearing.

These search keys are **never displayed**. `entries.text_norm` likewise: it is
a search key, not text. Displaying a normalised string would be showing the
user something no source ever wrote.

### 2. The corpus file is CRLF

`quranic-corpus-morphology-0.4.txt` uses `\r\n`. The FEATURES field is last on
the line, so `ROOT:qbl` and `ROOT:qbl\r` become two different roots and you
count **1652** instead of **1642**. Strip `\r` when parsing.

Correct load: **128,219 segments, 77,429 words, 6,236 āyāt, 1,642 roots.**

### 3. Arabic ف ع ل cannot be used as wazn placeholders

Substituting radicals into `مُسْتَفْعِل` by replacing ف, then ع, then ل,
corrupts any root that itself contains one of those letters. Root ع ل م:
replace ف → ع, and the pattern now holds a ع that came from the *root*; the
next replacement, ع → ل, eats it.

**Therefore: templates use the Latin placeholders `F`, `V`, `L`** for the
first, second and third radical (fāʾ / ʿayn / lām al-kalima). Latin letters
cannot collide with Arabic literals, and substitution is done in a single
pass. Never write a template with Arabic ف ع ل.

### 4. Diacritic-blind matching merges different words

`مَسْكَن` (ism makān), `مِسْكَن`, `مُسْكَن` (ism mafʿūl of form IV) and
`أَسْكَن` (ism tafḍīl) are four different words with one skeleton. Worse, the
ism al-tafḍīl `أَسْكَن` is *character-for-character identical* to the perfect
verb stem of form IV at **14:37** (`>asokan`, `POS:V|PERF|(IV)`).

**Therefore: attestation distinguishes**

- `EXACT` — the vowelled stem agrees, and
- `SKELETON` — same consonants, different vowels, i.e. **a different word**.

and **always shows the grammatical tag**, so an exact string match against a
*verb* is never sold as evidence that a *noun* is attested. A skeleton match
is reported as a skeleton match; it is never counted as attestation.

### 5. QAC lemmas carry a homograph index

The corpus writes `ma`lik` and `ma`lik2` for two different words (مَٰلِك the
participle, مَالِك the name), and 15 lemmas are indexed this way. That digit is
**data**. Strip it to make the string transliterable and you have merged two
words the corpus deliberately keeps apart — the same failure as
diacritic-blindness, arriving by a different door.

`to_arabic()` is therefore **strict**: an out-of-table character raises rather
than being dropped. That strictness is what caught this. Do not "fix" a
`TransliterationError` by skipping the character; find out what the character
means. (One segment legitimately contains a space — 37:130 `<ilo yaAsiyna`,
إِلْ يَاسِينَ — and spaces pass through by an explicit rule, not by accident.)

### 6. Hamzat al-waṣl, and the alif of the tanwīn

The muṣḥaf writes `ٱسْكُنْ`; the citation form of the same imperative is
`اُسْكُنْ`. Same word. So for **attestation** the initial alif and its helping
vowel come off — but the stripping must run on the raw string, *before* alif
folding, or `إِلَىٰ` loses its hamza and becomes `لى`. Hamzat al-qaṭʿ
(أ إ آ) is phonemic and is never touched.

Likewise `سَاكِنًا` (25:45) *is* the ism fāʿil `سَاكِن` wearing an accusative
tanwīn whose alif is written. Leave that alif in the stem and the attestation
disappears — a gap where evidence exists, which is the mirror-image failure of
a false match and just as wrong.

### 7. A regex over SQL text is not a guard

The first build checked for the base tables with a regex. It was defeated by
`main.entries`, by `"main"."entries"`, by `FROM/**/entries`, by a comma cross
join, by a scalar subquery, and by `CREATE VIEW launder AS SELECT * FROM
entries`. A regex sees *text*; the authorizer sees the table **SQLite actually
resolved**, at prepare time, after every alias, qualifier, CTE and view has
been expanded. Reads of `entries` / `tafsir` are permitted only when SQLite
reports the read is happening through `v_entries` / `v_tafsir`.

Ingestion and review tooling use `unguarded(conn)`. The query path never does.

### 8. The loader and the query path must canonicalise identically

QAC writes a hamza radical as Buckwalter `A` (`ROOT:Alh`, `ROOT:nbA`) — no
Arabic root has a true alif radical. The loader stored `اله` and every lookup
asked for `ءله`, so **135 roots and 9,791 segments were unreachable**, and
`root اله` answered *"this root does not occur in the Quranic Arabic Corpus"*
about the root of الله, 2,851 segments. A false statement about a named source
is the worst output this program can produce, and it was produced by two
functions politely disagreeing.

There is now one `canonical_root()`, called by both. It also folds `ى` → `ي`:
a root typed `رمى` — the ordinary way to type it — was classified **sālim**
and printed `رَمَىَ`, `يَرْمُىُ`, `مَرْمُوى` with no banner, while asserting "no
weak letter".

### 9. Two identical words can be different byte strings

The corpus writes `نَزَّلَ` as zain + shadda + fatḥa; a template builds it as
zain + fatḥa + shadda. Comparing code points called one word two words and
threw the evidence away — for all of forms II, V, IX and every muḍāʿaf root.
Comparison keys are therefore **NFC-normalised**, which reorders combining
marks by canonical class.

The sukūn is also dropped from the comparison: the Uthmani text does not write
it everywhere a template does (`يَنزِلُ` / `يَنْزِلُ`), and its absence marks no
vowel, so it carries no contrast that could distinguish two words — while a
real vowel is untouched and still does. `مَسْكَن` and `مِسْكَن` stay distinct.

### 10. Rank before you truncate

`attest()` collected the first N hits in sura order and sorted EXACT-first
afterwards, so the cap could drop every exact match and leave a screen of
skeleton matches each stamped "not attestation". The reader concludes there is
no evidence when there is. Rank first, cap second, and **report what was
withheld** — a silent cap reads as "that is all there is".

### 11. Do not explain a mechanism you did not check

A build of this file told the reader that a stem with no whole-word row had
been split from a **prefix**. For `أنفس` the extra segment is a pronoun
*suffix*, so the sentence was simply false: generated prose wearing the costume
of a rule. It is gone. The tool now states the fact and shows the containing
word, which is corpus text, and explains nothing.

### 12. Two kinds of doubt, kept apart

If every uncertainty printed the same `UNVERIFIED` banner, the banner would
stop meaning anything and the reader would learn to ignore it. So:

- **caveat** — the *string* may be wrong (root needs iʿlāl/ibdāl/idghām).
  Sets `verified = False`. Printed with `!`.
- **note** — the string is right, but whether the form *exists for this verb*
  turns on something not derivable from the letters (transitivity for the ism
  mafʿūl, comparability for the ism tafḍīl, an instrument sense for the ism
  āla). Does **not** set `verified = False`. Printed with `?`.

---

## The two refusals

These are not error handling. They are the product.

### R1 — the maṣdar of the thulāthī mujarrad is samāʿī

It is heard, not derived. `فَعَلَ` gives `فَعْل`, `فُعُول`, `فِعَالَة`,
`فَعَال`, … and nothing in the root determines which. The tool **never
generates one.** It prints an explicit refusal saying the maṣdar must be
quoted from a lexicon with a citation.

Only the maṣādir of the **mazīd fīh** forms are qiyāsī (`تَفْعِيل`,
`إِفْعَال`, `اِسْتِفْعَال`, …) and therefore safe to derive.

### R2 — weak roots need iʿlāl and ibdāl

Naive templating on ق و ل yields the non-word `قَوَلَ` instead of `قَالَ`.
The iʿlāl rules that produce `قَالَ` are not implemented.

**Therefore: every root is classified** (sālim / mahmūz / muḍāʿaf / mithāl /
ajwaf / nāqiṣ / lafīf), and any root needing iʿlāl, ibdāl or idghām is flagged
loudly. Its generated forms carry `verified = False` and are printed under a
banner marking them as raw template output — *not* a claim about Arabic.
They must never be emitted as if correct.

---

## What the rules are allowed to claim

A pattern being correct is not the same as the pattern *applying*. Three
places where the engine used to overclaim:

- **The ism makān** follows the muḍāriʿ vowel by qiyās, but a closed **samāʿī**
  class takes `مَفْعِل` from verbs that are not bāb 2 — and it is heavily
  Qurʾānic: `مَسْجِد` (28×, from سَجَدَ يَسْجُدُ), `مَشْرِق`, `مَغْرِب`, `مَطْلِع`,
  `مَوْضِع`. The tool printed `مَسْجَد` as verified while its own attestation
  said "not found in the corpus". Membership is not derivable; the slot says so.
- **Bāb 3's guttural** is a tendency, not a licence test. `أَبَى يَأْبَى` is the
  stock counterexample — its ḥalq letter is the **fāʾ** — and the condition is
  never sufficient either (`رَجَعَ يَرْجِعُ` has ع at R2 and is bāb 2).
- **Form VII** is not built when the fāʾ is ن م ر ل و ي ء (`اِنْنَصَرَ` is not a
  word); **form VIII**'s infixed tāʾ assimilates after ت ث و ي ء and changes
  after ص ض ط ظ د ذ ز (`ٱتَّبَعَ`, ~99× in the corpus, was printed `اِتْتَبَعَ`
  and marked *verified* — تبع is a perfectly sound root, so nothing else
  would have caught it); **forms IX and XI** are confined to colours and
  bodily defects.

## The rubāʿī is easier than the thulāthī, not harder

`فَعْلَلَ` has no bāb ambiguity — the muḍāriʿ is fixed at `يُفَعْلِلُ` — and no
samāʿī maṣdar: `فَعْلَلَة` and `فِعْلَال` are both qiyāsī, so **refusal R1 does
not arise**. Refusing quadriliterals was a self-imposed gap. The corpus proves
the templates: `زَلْزَلَة` 22:1, `زِلْزَال` 99:1, `دَمْدَمَ` 91:14, `وَسْوَسَ` 7:20 —
all EXACT.

## The build path is not the query path

    INGEST  ->  entries, verified = 0  ->  REVIEW (a person)  ->  verified = 1
                        |                                              |
                    never served                                    served

`lughat.py ingest` writes `verified = 0`, always. `lughat.py review` is the
**only** writer of `verified = 1`, one entry at a time, after showing a person
the heading, the derived root, how it was derived, the citation, and the text.
Approval stamps `verified_at`. A test asserts the ingest INSERT pins the
column to `0`, because a build path that could write `1` makes the gate
decorative.

A root with pending-but-unapproved entries says so. A gap the reader knows
about is a gap; a gap they don't is a lie by omission.

### Trap 13 — a digitisation artifact can file one root's article under another

OpenITI's Maqāyīs inserts `### |` headers **in the middle of a word**:

    ### | اله
    # مزة والكاف والراء أصل واحد، وهو الحفر

That is `الهمزة` split in two — and the fragment `اله` canonicalises to `ءله`,
the root of **الله**. Read as a heading, it files Ibn Fāris's article on أكر
(digging) under the divine name, with a page citation, looking perfectly
sourced. It was the *first* entry in the review queue.

**Only a parenthesised heading `(سكن)` starts an entry.** `[باب ...]` closes
one and starts nothing. Every other `### |` line is text belonging to the
entry in progress, rejoined using exactly the whitespace the source itself
has — `اله` + `مزة` → `الهمزة` — so no spacing is invented and no text is
dropped. This removed 403 false entries.

### Two spelling bridges, both recorded as inferences

Measured, not assumed. Direct heading matching covers 81% of corpus roots;
the misses are systematic:

- **geminate** — Maqāyīs heads a muḍāʿaf root with two letters (`أب`) where
  the corpus writes three (`ءبب`). 152 entries.
- **weak_final** — Maqāyīs heads a weak-lām root with ى/ي (`دنى`) where the
  corpus writes و (`دنو`). 37 entries.

Both are inferences, so `entries.extraction` records which, and review shows
it. Coverage: **1,510 of 1,642 corpus roots** have an entry.

### Verbatim means verbatim

`entries.text_raw` holds the source block **byte for byte**, mARkdown markup
included. The markup is stripped at *display* time by `render_entry()`, so
the transformation is a readable rule rather than something baked into the
data. Page markers and milestone ids are dropped, `# ` begins a paragraph,
`~~` continues one, `%` separates hemistichs.

### Migrations are additive

`entries` can hold rows a person has read and approved. `migrate()` only ever
`ALTER TABLE ... ADD COLUMN`; a test greps it for `DROP TABLE` and
`DELETE FROM entries`. Note also that `INSERT OR REPLACE` on `sources` would
delete the row and re-insert it with a new id, orphaning every entry pointing
at it — use `ON CONFLICT ... DO UPDATE`.

## Sourcing

`roots.bab` is a **sourced column.** The bāb of a root is not derivable from
its letters — `سكن` is bāb 1 and `ضرب` is bāb 2 and nothing in س/ك/ن or
ض/ر/ب says so. It is read from a lexicon and stored with `bab_source_id` and
`bab_page`. NULL means unknown, and everything that depends on the bāb — the
muḍāriʿ, the amr, the ism makān — refuses when it is NULL.

A bāb passed on the command line is a *user hypothesis*, and output derived
from it is labelled as such. It is not a citation.

`entries.text_raw` is verbatim, or NULL for scan-only sources (where the page
image is the citation and no text has been keyed in). `entries.text_norm` is a
search key and is never displayed.

---

## Root classification, as this build computes it

    salim   967   ajwaf 221   naqis 164   mudaaf 147
    mithal   74   lafif  29   other  40          total 1642
    488 of 1642 roots need iʿlāl → their forms are UNVERIFIED

`lafīf` is its own bucket here. An earlier build folded those 29 roots into
ajwaf (+12), mithal (+11) and muḍāʿaf (+6), which reproduces the older tally
of 233/85/153 and an "other" of 40. A root weak in *two* positions is neither
an ajwaf nor a mithal, and counting it as one overstates how well the
templates behave on it. The older run's "482 affected" also missed 6 roots
that are both lafīf and muḍāʿaf (حيي and its kind) plus 2 weak quadriliterals;
they need iʿlāl too, hence 490 — and then 488, because the 2 weak
quadriliterals do **not** need it: a weak radical in a rubāʿī takes no iʿlāl,
and the corpus settled it. `وَسْوَسَ` was being printed UNVERIFIED while 7:20
and 114:5 read exactly what the template produced. When the Qurʾān contradicts
a flag, the flag is wrong.

Do not tune the classifier to reproduce a remembered number. If a count
changes, find out which roots moved and why.

## Layout

Single file, stdlib only, offline after `setup`.

    lughat.py setup [--from PATH]   download / load the corpus
    lughat.py test                  INTEGRITY + HONESTY suites
    lughat.py sarf <root> [bab]     ishtiqāq ṣaghīr, with refusals
    lughat.py root <root>           corpus occurrences of a root
    lughat.py word <word>           search the mushaf text
    lughat.py aya <sura:aya>        print an ayah, to check against a mushaf
    lughat.py ingest maqayis --from PATH   load a lexicon, all verified = 0
    lughat.py review [--stats]      the approval gate

## Attribution (required by the licences)

- Ibn Fāris, *Muʿjam Maqāyīs al-Lugha*, ed. ʿAbd al-Salām Muḥammad Hārūn
  (Beirut: Dār al-Jīl, 1420/1999), 6 vols. Digital text: OpenITI,
  CC BY-NC-SA. <https://github.com/OpenITI>
- Quranic Arabic Corpus, morphology v0.4 — © 2011 Kais Dukes, GNU GPL.
  <http://corpus.quran.com>
- Tanzil Qur'an text (Uthmani) 1.0.2 — © 2008–2009 Tanzil.info,
  CC BY-ND 3.0. <http://tanzil.info>

Both notices must be reproduced by anything that redistributes this data.

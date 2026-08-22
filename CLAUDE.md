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

**Discharged for three classes, at a measured rate, and for nothing else.**

The rules are in this file and are checked against the Qurʾān:
`lughat.py ilal --check` regenerates the citation forms of every weak root the
muṣḥaf attests and compares them **exactly**. A rule that does not reproduce
the Qurʾān is wrong.

| class | strong evidence | verdict |
|---|---|---|
| ajwaf | 13/13 | validated — `قَالَ / يَقُولُ / قُلْ` marked verified |
| nāqiṣ | 17/17 | validated |
| muḍāʿaf | 8/8 | validated |
| **mithāl** | **2/4** | **not validated — keeps its caveat** |

*Strong* means the root is attested in **both** aspects and **one** bāb must
reproduce both. For an ajwaf the māḍī is bāb-independent (`قَالَ` whatever the
bāb) but the muḍāriʿ is not, so a single bāb fitting both is a real
constraint — if the māḍī rule still produced `قَوَلَ`, no bāb would satisfy
it. Roots attested in one aspect only are counted **separately** as *weak*
evidence, because any bāb fitting that one slot passes and mixing the two
overstates the case.

Mithāl is not claimed because the wāw's fate is **not determined**: it drops
before a kasra (`وَعَدَ يَعِدُ`), survives before a fatḥa (`وَجِلَ يَوْجَلُ`)
— except where it does not (`وَضَعَ يَضَعُ`, `وَهَبَ يَهَبُ`). Where the bāb
gives a fatḥa the tool **refuses** rather than guessing.

Everything else still refuses: every **mazīd** form of a weak root is a raw
template, and lafīf, mahmūz-plus-weak, and the ism slots have no rules here.
`sarf قول` says so with counts — *3 of 80 forms verified* — rather than a
blanket banner that was true before and is false now.

### R2, as originally stated

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

### Trap 19 — `set_authorizer(None)` is not "no authorizer" on older Pythons

The guard is dropped for ingestion with `unguarded(conn)`. That was written as
`conn.set_authorizer(None)`, which removes the authorizer on **Python 3.11+**
and does **not** on 3.10 and earlier: there the callback is stored as `None`,
every authorization request then fails, and SQLite is told **DENY**. The whole
program dies with `sqlite3.DatabaseError: not authorized` on a statement as
innocent as counting rows in `sqlite_master` — on the first command a person
runs, on a Mac, whose system Python is 3.9.

Handing SQLite a callback that says yes (`_permit_all`) behaves identically on
every version. And because this build is *developed* on 3.11, no test that
merely exercises the code can catch it: the test matches on the **call**
(`conn.set_authorizer(<name>)`, and the name is never `None`), not on
behaviour it cannot reproduce here.

The general form: **the machine this is written on is not the machine it is
read on.** A guard that depends on an interpreter version is a guard that is
absent on somebody's laptop.

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

### Each lexicon is read by its own rules

One heading rule does not fit three books, and guessing one costs the whole
extraction:

| | entry marker | ordered by |
|---|---|---|
| Maqāyīs | `### | (سكن)` — parentheses required, see trap 13 | first radical |
| Mufradāt | `### | سكن` — a bare short heading, no parentheses to lean on | first radical |
| Lisān | no `###` markers at all; the root is named **twice**, `# سكن` then `# ] سكن …` | **last** radical |

Lisān's double naming is the strongest guard of the three — a stray line
cannot fake both halves — and a bare head with no confirming line is *not* an
entry. But the confirming colon is **not always written**: `# ] سكن السكون ضد
الحركة` has none, and requiring it silently dropped **827 entries, `سكن` among
them**. A guard tuned too tight fails the same way a missing one does, only
quietly.

`ordered_by` matters as much. Lisān and al-Qāmūs order by the **last** radical
(bāb), then the first (faṣl); checking them against first-radical order flags
the entire book. A warning that cries wolf is worse than no warning, because
the reviewer learns to ignore the badge — which is also why the order check
compares against the *previous* heading and not a running maximum: one stray
heading (Mufradāt has `وإي` inside the hamza section) poisoned a max and
flagged 1,524 sound entries.

### Trap 14 — the digitisation's own marks destroy a heading

`### | (نهي) ms1086` is not a heading, because the detectors anchored on `$`
while only `render_entry()` stripped `ms####`. Ibn Fāris's article on نهي was
dropped; `(حول) ms0282` folded into the entry for **حوك**; al-Rāghib on نور,
روح, بدل, سود, شرط, مهل and حقب all landed under their neighbours. Four more
died to a bracket the digitiser left inside the parentheses — `( [بقر)` — بقر
among them. **Clean a heading before matching it, with the same rules that
clean the body.**

### Trap 15 — a page marker CLOSES the page it names

Every one of these files ends with its final words followed inline by the last
marker, and the Shamela ones open with a `PageV00P000` sentinel. Text after
`PageV01P006` is therefore on p. **7**. Taking the previous marker put all
15,500 citations one page too low, and at a volume boundary in the wrong
volume as well — `(حد)` cited to vol 1 p. 513 when it opens vol 2 p. 3.

A wrong page is a wrong citation, which is the whole product. Resolve an
entry's page by **looking ahead** to the marker that closes it.

Because this is a *systematic* correction, re-ingesting must reach rows a
person has already approved: their decision stands, but their citation is
rewritten. So the "already decided, leave alone" fingerprint is keyed on the
headword and text, **never on vol/page** — keying on those made every
corrected row look like a new entry and left the approved one wrong.

### Trap 16 — a heading you cannot confirm is still a boundary

In Lisān a bare `# سفه` whose confirming line does not parse used to flow
onward, so its article landed under the *previous* root: 34,017 bytes
misfiled, one entry being **99% Ibn Manẓūr on سفه while labelled سده**. The
same for a head too long to be a root — استبرق, زنجبيل, ميكائيل, منجنون are
Lisān headwords, and 16 articles ended up under a neighbour because
`canonical_root()` rejected the head and the line became body text.

**Anything that looks like a heading closes the entry in progress**, whether or
not it opens a new one. Dropping text is bad; filing it under the wrong
scholar's root is worse.

### The order check must fit the book, and cry wolf at nothing

Three books, three ordering schemes and three useful depths:

| | ordered by | positions checkable | flags |
|---|---|---|---|
| Maqāyīs | first radical | 2 (the bāb fixes the first two) | 29 / 4,654 |
| Mufradāt | first radical | **1** — it heads by *word*, not root | 5 / 1,701 |
| Lisān | **last** radical | 2 | 97 / 9,238 |

Checking Mufradāt at depth 2 flags 7% of a sound book; checking Maqāyīs at
full depth flags 11%. A `[باب …]` also **restarts** the alphabet, so the key
resets at a section. The check is a weak secondary signal — the real guards
are the parenthesis rule, Lisān's double naming, and heading cleaning — and a
badge that fires on a tenth of a book teaches the reviewer to ignore it.

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

## Ibn Jinnī: three things, kept apart

**Listing** the six permutations of a triliteral is arithmetic. **Saying which
of them the Qurʾān uses** is a database lookup. Both are derivation, both are
safe, and `lughat.py akbar` does both.

**Claiming they share an idea** is Ibn Jinnī's *thesis*, argued in
al-Khaṣāʾiṣ. It is not derivable from the letters, this tool cannot compute
it, and it is refused. It is also a *minority* method — supporting insight
after Ibn Fāris and al-Rāghib have established a meaning, never primary
evidence — and the output says so every time.

Neither of his books is keyed by root. *Sirr Ṣināʿat al-Iʿrāb* is about the
**letters** (`entries.root_ar` is NULL, the headword is the letter);
al-Khaṣāʾiṣ is about **topics**. Inventing a root for either would file text
under something the book never said, so `keyed_by` records what a source is
actually organised by, and the parser refuses to resolve a root for those.

### A book with no article is searched, and the reader is told which it was

Because neither book can be *asked* about a root, `lughat.py mentions` (and
the same section of the reading page) **refuses first** — "al-Khaṣāʾiṣ is
organised by topic, not by root, so it has no article on سكن to quote" — and
only then searches. An empty card reading *"no entry for this root"* would
have been a claim about the book's contents when the truth is about its
organisation, so books not keyed by root are **excluded from the dictionary
cards entirely** and get this section instead.

The matching rule is written down, printed with the results, and small enough
to read: the radicals **in order**, separated only by the three long vowels
`ا و ي` — the only letters a wazn puts between them — with the third radical
optional when it repeats the second (idghām writes `مدد` as `مد`). So `س ك ن`
finds سكن, يسكن, ساكن, مسكون, مساكين, تسكين.

What it costs is printed too, and a test checks the prose against the regex:

- it **misses** a form that infixes a consonant (form VIII `اجتمع` for ج م ع)
  or replaces a radical by iʿlāl (`قال` — the wāw of ق و ل is simply not in
  the string);
- it **overmatches**: the separator class cannot tell a template's alif from
  another root's radical, so `س ل م` finds `سليمان`.

A stated limit the code does not actually have would be worse than no
statement, because the reader calibrates on it. Hence the test asserts both
failures still happen.

A chapter of al-Khaṣāʾiṣ runs to 48 KB and crosses many pages, so **the
entry's page is not the passage's page**: each passage resolves its own,
by the same lookahead as trap 15. And OpenITI's `AUTO` marker on a header it
generated itself is the digitisation's annotation, not a title Ibn Jinnī
wrote, so it is stripped at display time like any other markup — the stored
headword stays verbatim.

### Trap 17 — an unmarked chapter is not the previous chapter

This witness of *Sirr* never marks `حرف النون`, and the volume divider
`### | CHECK [جزء 2]` was folded in as body text. So the chapter headed
`حرف الميم` ran to **109,605 bytes** and half of it was Ibn Jinnī on **nūn**,
ready to be served under **mīm**.

In a book whose chapters *are* all marked, a header the rule does not
recognise is a structural break, never prose: it **closes the chapter in
progress**. Nūn then becomes unassigned text — a gap the tool counts and
reports (`305,554 characters reached no entry`) — instead of a misattribution
it cannot see.

And when a letter has no chapter, the tool says the gap belongs to *this
digitisation*, not to Ibn Jinnī, who treated all 29.

## Synonyms and opposites: quoted, never computed

**Synonyms.** al-ʿAskarī heads every article `الفرق بين X و Y`, so the pair is
his own data, read off his title. What the tool reports is that he *wrote a
chapter separating those two words* — not that they are synonyms, which is his
judgement and not a fact in the letters. A root matches when one of the
heading's terms contains its radicals by the same written-down rule (and with
the same stated costs) as the `mentions` search. He is keyed by a **pair**,
so like al-Khaṣāʾiṣ he gets no root card.

**Opposites.** There is no dictionary of Arabic antonyms loaded here, and an
opposite the tool worked out itself would be a fabrication like any other. So
it **refuses** — and then shows the sentences where a lexicographer states an
opposition in his own words (`ضد`, `نقيض`, `خلاف`, `عكس`), whole and cited.
Ibn Fāris: *يدل على خلاف الاضطراب والحركة* (3/88). Ibn Manẓūr: *السكون ضد
الحركة* (13/211). Reading that as "the antonym is حركة" is the reader's
inference on the scholar's sentence, not the program's on the reader's behalf
— and no field of the payload names the opposite, because naming it would mean
parsing what a lexicographer meant.

The JK Lisān carries **no sentence punctuation at all**, so "the sentence" is
the whole 8,000-character article. Where there is nothing to split on, a
window is taken around the matched word — still one contiguous run of the
source's own characters, marked with an ellipsis so it is visibly an excerpt.
Taking those offsets from a *different* string than the match was found in
turned `السكون ضد الحركة` into `ضد لحركة`: a word of Ibn Manẓūr's corrupted by
one character, in a card carrying his name. Trap 8 again.

## Machine glosses: allowed, and quarantined

A reader asked for the dictionary articles in Urdu and English knowing that
no such translation exists — that it would be a machine's rendering, nobody's
published work, checked by no one. That is a decision the reader is entitled
to make about their own tool. It is allowed on four conditions, and the test
is what keeps them after the asking is forgotten:

1. **This program does not make them.** It has no model in it and the test
   forbidding one is not relaxed. A gloss is produced by whatever engine the
   reader chooses, *outside* the tool, and imported as a JSONL file of
   `{entry_id, lang, text, engine}` — the same shape as a Tanzil translation.
   So the query path stays pure retrieval, and the whole corpus can be
   re-glossed by a better engine without touching a line of a scholar's text.
2. **Its own table.** `glosses`, never a column on `entries`: the scholar's
   words and a machine's rendering of them must be impossible to confuse at
   the storage layer, not merely on screen.
3. **Its own column beside the Arabic**, and as a WHOLE — never interleaved
   paragraph against paragraph, which would imply a correspondence nobody
   checked and is the arrangement where a wrong line reads as the scholar's
   meaning. Each language is switched on and off in the source selector,
   labelled *machine* in the switch itself and not only in the card.
4. **A warning on every one, naming the engine**: *not Ibn Fāris's words, and
   not checked by anyone.* `gloss --clear` deletes them all and touches
   nothing else.

What this is not: `entries.text_raw` is still byte-exact, still the only
thing a citation points at, and a gloss carries no page number, because there
is no page it was printed on.

## Urdu beside the Arabic

A translation shown next to a scholar's words is where generated prose would
be least visible, so **the tool refuses to translate** and installs a
published translator's own lines instead. Eight are installable and **none by
default**: these translators belong to different schools, and choosing one
silently is a judgement this program has no business making.

These rows are **not gated**, and the distinction matters. `entries` and
`tafsir` are reviewed because their key is *derived* — a parser decided which
root, which āyah — and a parser can be wrong in a way that looks perfectly
sourced. A translation file states `sura|aya|text`: the parser splits on a
pipe and infers nothing, so these rows sit with `words` and `segments`. What
is checked instead is the **numbering**: the file's āyah set must equal the
corpus's 6,236 exactly, or the whole file is refused. Some editions count the
basmala as an āyah, and a single offset would put one verse's words under
another — invisible, because every line would still look like a translation
of something.

## Tafsir: the anchor is the product, not the text

A commentary is keyed by **āyah**, and no digitisation carries a
machine-readable sura:aya index. So the anchor has to be derived — and a wrong
anchor is the worst thing available here: it files al-Baghawī's comment on one
verse under another verse, with his name and a page number on it, looking
perfectly sourced.

**Two independent facts must agree.** This witness opens each pericope by
quoting the āyāt it is about, with the editor's numbers inside the quotation:

    # {الر تلك آيات الكتاب الحكيم (1) } .

So there is the **quoted text**, which either matches an āyah of the corpus or
does not, and the **printed number**, which the editor supplied. An anchor is
accepted only when a quotation matches **exactly one** āyah *and* that āyah's
number is the number printed beside it. Where a pericope quotes several āyāt,
every quotation that matches must land in the same sūra.

Measured on al-Baghawī: **2,096 of 2,160 pericopes anchor, covering 5,463 of
the 6,236 āyāt, and the number disagreed with the text in ZERO cases.** The 64
that do not anchor are **not ingested** and are counted in the report — an
unanchored comment is a comment about nothing.

### The fold, and why a loose key is safe here

The editor prints modern orthography; the corpus holds the Uthmani rasm. `الكتاب`
is written with a dagger alif; `الصلاة` is written `صلوة` — a **wāw** where the
printed edition has an alif. So `mushaf_key()` folds marks off, hamza carriers
together, `ى`→`ي`, `ة`→`ه`, and then deletes **all three long vowels**.
Dropping the alif alone still leaves `لصلوه` against `لصله`, and 2:110 fails to
match itself.

That is a very loose key. It is safe only because it is never used alone:

1. an anchor is taken only from a key that is **unique** across the 6,236 āyāt
   (`فبأي آلاء ربكما تكذبان` occurs 31 times and therefore anchors nothing), and
2. the **printed āyah number must agree** with the āyah the key found.

Loosening the key from the strict one moved the anchored count from 985 to
2,096 and the disagreement count from 0 to 0. Like `norm_alif` / `norm_drop`,
this key is a **comparison key and is never displayed**; a test asserts the
reading surface never calls it.

### Trap 18 — the digitisation's marks are inside the quotation too

`كلما رزقوا منها ms0042 من ثمرة` — the milestone id sits in the middle of the
Qurʾānic quotation, so the quotation matched nothing. That is **trap 14 in a
new place**: clean the text with the same rules that clean the body *before*
matching it. Leaving them in cost 293 anchors, and every one of them looked
like the mufassir quoting something the muṣḥaf does not contain.

### A pericope has a range, and a citation has a beginning

A pericope covers several āyāt (`tafsir.aya`, `tafsir.aya_to`) and can run for
six pages. The citation is where the passage **begins** — citing 2:35 to p. 86
because the discussion ended there sends the reader to the wrong page — and
where it ends is recorded separately in `page_to`.

The sūra header is a level-1 marker and, like a `[باب ...]` title in Maqāyīs,
it **closes what is in progress and opens nothing**. Treating it as a pericope
reported 114 sūra preambles as 114 comments that could not be anchored — a
refusal count that overstated the gap by more than a third.

### Bulk approval, and why it is stamped

15,768 entries one at a time is a gate nobody finishes, and a gate nobody
finishes is a tool nobody uses. So `review --approve-all` accepts a **class**
— a source, an extraction method, a root, a text match — and it is not a
hidden shortcut:

- it **names a class or refuses**. `--approve-all` alone would make the gate
  decorative, so at least one of `--source= --extraction= --root= --contains=`
  is required.
- it **prints what the gate is for**, including the أكر-under-الله failure.
- it **shows a sample** — twelve entries taken at a stride across the class,
  not off the front, because the first N entries of a lexicon are all in the
  same letter and a letter is the wrong unit to judge a book by.
- it demands the word **yes**.
- every row it approves is stamped `verified_by = 'bulk'`, **permanently**,
  and the reading page badges it. *A person read this* and *a person accepted
  the class this belongs to* are different claims about the same text, and
  the reader is told which one they are looking at.

`--approve-all --everything` does the whole of it — both queues, in one
command. Refusing that while offering the same thing one class at a time
would have been theatre: five commands reach the same place. What must not
happen is the DISTINCTION disappearing, and it does not.

The stamp is what makes the shortcut honest rather than a quiet weakening.
A test asserts the stamp is written, that the badge reaches the page, and —
by calling it, not by grepping for the word — that a class must be named.

### The gate has to be reachable from the word you are reading

The queue is 15,768 entries in frequency order. That is the right default and
useless when you are looking at **one** word in the reader and want its
articles decided now — so the queue takes a root, on the CLI
(`review --root=سكن`) and in a box on the review page, and the reader's empty
card prints the exact command that fills it. A gate nobody can reach from
where they are standing is a gate nobody uses.

A tafsir is keyed by āyah, so it gets **no root card at all** — an empty card
saying "no entry for this root" would be a claim about its contents when the
truth is about its organisation, and it also listed al-Baghawī twice in the
source selector.

### Two queues, one gate

`review --tafsir` works the tafsir queue, and `serve` has a second tab for it.
What is being approved there is not a root but an **anchor**, so the anchor's
evidence is printed above the text every time. A table name cannot be a bound
parameter, so the queue interpolates one — through `REVIEWABLE`, a whitelist of
exactly two tables, checked on every entry point including the HTTP route.

## Sourcing

### The bāb comes from the muṣḥaf, because the lexicons have no vowels

The plan was to read the muḍāriʿ vowel off a cited lexicon page. **That is
impossible with the texts that exist**: the OpenITI digitisations of Maqāyīs,
al-Mufradāt and Lisān carry *zero* diacritics — measured, 0 marks in 125,000
characters. The vowel is simply not in them.

But the Qurʾān is fully vowelled, and where a root's form-I verb occurs in
both aspects the muṣḥaf settles the bāb itself:

    سَكَنَ (6:13)  +  يَسْكُنُ (7:189)   →  fatḥa/ḍamma  →  bāb 1 (naṣara)

The citation is a **verse**, checkable in any muṣḥaf — a stronger warrant than
a lexicon reference, not a weaker one. 136 roots, `bab_method =
'mushaf-vowelling'`, with `bab_evidence` holding both references.

Four restrictions, each of which loses roots and each of which is necessary:

- **Sound roots only.** Iʿlāl moves and lengthens a weak root's vowels, so its
  surface ḥarakāt are not the pattern's. `قَالَ` has no ḥaraka on its ʿayn at all.
- **Form I, active only.** QAC does *not* tag every passive — 28:58 `تُسْكَن`
  carries no PASS marker — so the passive is read off the vowelling, which
  states it: a ḍamma on the muḍāriʿ prefix, or a ḍamma/kasra pair in the māḍī.
- **Both aspects must occur**, or there is no pair to read.
- **One vowelling each.** `كَبِرَ يَكْبَرُ` and `كَبُرَ يَكْبُرُ` are two verbs
  sharing a root; `لبس` likewise. The tool **refuses** and prints the
  conflicting verses. A silent majority vote is exactly the quiet inference
  this program exists to refuse — and note the test asserts the *ambiguity
  flag*, not merely that the bāb came out NULL, because a majority vote on
  كبر happens to land on an invalid vowel pair and would have passed.

The remaining 1,506 roots have no sourced bāb, and everything depending on it
still refuses for them.

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
    lughat.py bab [<root>|--derive] the bāb, read off the Qurʾān's vowelling
    lughat.py ilal --check          check the iʿlāl rules against the Qurʾān
    lughat.py akbar <root>          the six permutations, per Ibn Jinnī
    lughat.py letter <root>         Ibn Jinnī on the root's letters
    lughat.py mentions <root>       search the books not keyed by root
    lughat.py translation [--add=K] a translation beside the Arabic
    lughat.py tafsir <sura:aya>     approved commentary on an ayah
    lughat.py ingest <source> --from PATH
                                    maqayis | mufradat | lisan | sirr |
                                    khasais | furuq | baghawi
    lughat.py serve [--port=N]      the approval gate as a local page
    lughat.py review [--stats]      the approval gate
    lughat.py review --root=<root>  approve one root's entries now
    lughat.py review --approve-all --source=K   approve a class,
                                    after a sample; stamped `bulk`
    lughat.py review --approve-all --everything  both queues at once
    lughat.py review --tafsir       the same gate, for commentary
    lughat.py read [--port=N]       the reading surface: approved sources only

## Two servers, and why they are two

`serve` is the **build path**: it shows `verified = 0` text, because showing
it is the whole point of a review gate. `read` is the **query path**: a
separate process, a separate port, a **guarded** connection, no `do_POST`,
and no INSERT/UPDATE/DELETE anywhere in its section. One process serving both
would put a single `unguarded(conn)` call between the reader and a
fabrication. Its one unguarded query is a `COUNT(*)` of pending rows — a
number, never text — so an empty card can say *why* it is empty.

Both bind `127.0.0.1`. Neither can be shared as a link, because a server on
this machine is not reachable from another one — and a "share" of the review
gate would mean serving unreviewed lexicon text.

`export` is the answer to that: **the reading surface with its server
removed**, one file, no database. The payload is built by the same
`read_root()` the server uses, on a **guarded** connection, so an export can
no more carry an unreviewed article than the page it is made from. What it
loses is the database, so it holds only the roots it was built with and
**says so in a banner** rather than pretending to be the whole tool. Sharing
one shares CC BY-NC-SA lexicon text: every card carries its attribution, and
that has to travel with it.

The page has **three views**, because the three questions are different and
the books answering them are keyed differently — a dictionary by **root**, Ibn
Jinnī by **letter** and by **topic**, the muṣḥaf by **āyah**. Putting them on
one screen made the ṣarf grid the first thing a reader met and buried the
dictionaries under it.

    Dictionary          the three root-keyed lexicons, then al-ʿAskarī on
                        near-synonyms and the sentences stating an opposition
    Ishtiqāq — Ibn Jinnī the six permutations, his chapter on each radical,
                        al-Khaṣāʾiṣ searched, and his own table of contents
    Qurʾān              the tafsir on each āyah, and every occurrence

Because his books cannot be *asked* about a root, the Ibn Jinnī view also
lets them be entered the way he wrote them: a list of his chapter titles,
filterable, **approved ones only** — with the count of what is still waiting
and the command that decides it.

The ishtiqāq ṣaghīr table is folded shut. It was asked for, and then found to
crowd out the dictionaries; one click opens it and nothing was deleted.

The page shows, for one root: every source as a card (**including the empty
ones** — hiding a silent source would imply an agreement that never happened),
the ṣarf table in full with its refusals, and for every generated string the
corpus's own verdict — EXACT hits as attestation, SKELETON hits labelled *NOT
attestation* and shown with the corpus's grammatical tag, per trap 4.

## Attribution (required by the licences)

- Ibn Fāris, *Muʿjam Maqāyīs al-Lugha*, ed. ʿAbd al-Salām Muḥammad Hārūn
  (Beirut: Dār al-Jīl, 1420/1999), 6 vols. Digital text: OpenITI,
  CC BY-NC-SA. <https://github.com/OpenITI>
- al-Rāghib al-Iṣbahānī, *al-Mufradāt fī Gharīb al-Qurʾān*. OpenITI,
  CC BY-NC-SA. <https://github.com/OpenITI>
- Ibn Manẓūr, *Lisān al-ʿArab*. OpenITI, CC BY-NC-SA.
  <https://github.com/OpenITI>
- Ibn Jinnī, *Sirr Ṣināʿat al-Iʿrāb* and *al-Khaṣāʾiṣ*. OpenITI,
  CC BY-NC-SA. <https://github.com/OpenITI>
- Abū Hilāl al-ʿAskarī, *al-Furūq al-Lughawiyya*, ed. Muḥammad Ibrāhīm
  Salīm (Cairo: Dār al-ʿIlm wa-l-Thaqāfa). Digital text: OpenITI,
  CC BY-NC-SA. <https://github.com/OpenITI>
- Qurʾān translations from Tanzil.net, non-commercial use only; copyright
  remains with each translator or publisher. <https://tanzil.net>
- al-Baghawī, *Maʿālim al-Tanzīl fī Tafsīr al-Qurʾān*, ed. al-Nimr,
  Ḍamīriyya and al-Ḥarsh (Dār Ṭayba, 1417/1997), 8 vols. Digital text:
  OpenITI, CC BY-NC-SA. <https://github.com/OpenITI>
- Quranic Arabic Corpus, morphology v0.4 — © 2011 Kais Dukes, GNU GPL.
  <http://corpus.quran.com>
- Tanzil Qur'an text (Uthmani) 1.0.2 — © 2008–2009 Tanzil.info,
  CC BY-ND 3.0. <http://tanzil.info>

Both notices must be reproduced by anything that redistributes this data.

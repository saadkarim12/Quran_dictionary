# QA — how to check this tool without trusting it

Everything below you can run yourself. The point of the exercise is to verify
the tool against sources **you** control — a printed muṣḥaf, your own lexicons,
corpus.quran.com — rather than against its own test suite. A program's own
tests only prove it is consistent with itself.

Run everything from the repo directory after `python3 lughat.py setup`.

---

## A. Does the loaded text match the muṣḥaf?

This is the check that matters most, because every later layer is keyed to
this text. **Open a printed muṣḥaf and compare by eye.**

    python3 lughat.py aya 2:35
    python3 lughat.py aya 1:1
    python3 lughat.py aya 112:1

The first line printed is the āyah as the database holds it — the concatenation
of the corpus's own segment forms, nothing inserted or reordered. Check the
*rasm* and the *ḥarakāt*, and specifically look at:

- **2:35** — `ٱسْكُنْ` must show alif waṣla (ٱ), not a plain alif with a ḍamma.
  `يَٰٓـَٔادَمُ` must show the dagger alif and the maddah.
- **1:1** — `ٱلرَّحْمَٰنِ` must have the dagger alif (ٰ) and no full alif.
- **112:1** — `قُلْ هُوَ ٱللَّهُ أَحَدٌ`.

If a mark is missing or in the wrong place, the Buckwalter table is wrong, and
that is a top-severity bug — say so and stop. Reversibility tests cannot catch
it, because a wrong mapping round-trips just as well as a right one.

Pick three more āyāt at random, ideally ones with unusual orthography
(2:245 `يَبْصۜطُ`, 11:41 `مَجْر۪ىٰهَا`, 41:44 `ءَا۬عْجَمِىٌّ`, 37:130 `إِلْ يَاسِينَ`).

## B. Do the counts match the published corpus?

    python3 lughat.py test

The first test must report **128,219 segments / 77,429 words / 6,236 āyāt /
1,642 roots**. Cross-check the word and root totals against corpus.quran.com,
which publishes them. Sura and āyah counts you can check against any muṣḥaf:
114 suras, al-Baqarah 286.

## C. Does it refuse where it must?

    python3 lughat.py sarf نصر 1

In the BAB 1 block, the `masdar` slot must print **REFUSED**, not a form. Repeat
for all six abwab — the maṣdar of the thulāthī mujarrad is samāʿī and the tool
must never derive one:

    for b in 1 2 3 4 5 6; do echo -n "bab $b: "; \
      python3 lughat.py sarf نصر $b | grep -c "mujarrad is SAMA'I"; done

Each must print `1`. (Grep for the refusal text, not for `masdar` — the mazīd
sections below legitimately DO carry a `masdar (qiyasi)` line, and a loose
grep will match those instead and look like a pass.)

Then a weak root:

    python3 lughat.py sarf قول

It must print a loud UNSOURCED/NOT-SOUND banner, and `قَوَلَ` must appear marked
`[UNVERIFIED - RAW TEMPLATE]`. If `قَالَ` appears anywhere as a derived form,
the iʿlāl rules have been quietly added without being verified — that is a bug.

And the bāb:

    python3 lughat.py root سكن

Must say the bāb is **UNSOURCED**. It is bāb 1 (naṣara) — check your Qāmūs
al-Waḥīd — and the tool still must not say so, because nothing in the database
sources it yet. If it ever states a bāb without a citation, that is the whole
failure this program exists to prevent.

## D. The test that matters most: can an unverified row reach you?

Insert a fabricated entry attributed to a real scholar, with `verified = 0`,
and confirm it never appears.

    python3 - <<'PY'
    import sys; sys.path.insert(0, '.')
    import lughat as L
    c = L.connect()
    c.execute("INSERT OR IGNORE INTO sources (key,title,kind,attribution) "
              "VALUES ('qa_fake','FAKE LEXICON','lexicon','none')")
    sid = c.execute("SELECT id FROM sources WHERE key='qa_fake'").fetchone()[0]
    c.execute("INSERT INTO entries (source_id,root_ar,text_raw,vol,page,verified)"
              " VALUES (?,?,?,?,?,0)",
              (sid, "سكن", "Ibn Faris says: THIS TEXT IS A FABRICATION", "1", "99"))
    c.commit(); print("inserted verified=0")
    PY

    python3 lughat.py root سكن | grep -c FABRICATION      # must print 0

Now flip it to `verified = 1` and confirm it *does* appear — a filter that
hides everything is not a filter:

    python3 - <<'PY'
    import sys; sys.path.insert(0, '.')
    import lughat as L
    c = L.connect(); c.execute("UPDATE entries SET verified=1 WHERE page='99'")
    c.commit()
    PY

    python3 lughat.py root سكن | grep -c FABRICATION      # must print 1

Clean up:

    python3 - <<'PY'
    import sys; sys.path.insert(0, '.')
    import lughat as L
    c = L.connect()
    c.execute("DELETE FROM entries WHERE source_id IN "
              "(SELECT id FROM sources WHERE key='qa_fake')")
    c.execute("DELETE FROM sources WHERE key='qa_fake'"); c.commit()
    PY

## E. Search: the dagger alif

    python3 lughat.py word مساكين      # must find 5:89 and 5:95
    python3 lughat.py word رحمن        # 57 stem hits
    python3 lughat.py word رحمان       # must ALSO find them

`مساكين` is typed with a full alif; the muṣḥaf writes `مَسَٰكِينَ` with a dagger
alif. `رحمن` is typed without one. Both spellings must work, in both
directions. If either returns nothing, the normaliser has regressed.

## F. Try to make it lie

Nothing here should ever produce confident output:

    python3 lughat.py root زقز         # a root that does not exist
    python3 lughat.py sarf سك          # only two radicals
    python3 lughat.py sarf دحرج        # quadriliteral
    python3 lughat.py sarf سكن 9       # not one of the six abwab
    python3 lughat.py sarf "zz9"       # not transliterable

Each must give a refusal, a clear message, or an explicit "does not apply" —
never a plausible-looking form. A traceback is a bug but a *confident wrong
answer* is far worse; grade them that way.

## G. Attestation: exact vs skeleton

    python3 lughat.py sarf سكن 1 | grep -A9 "ism tafdil"

`أَسْكَن` matches 14:37 exactly as a string, but 14:37 is the **verb** أَسْكَنتُ
(form IV perfect). The output must show the tag `POS:V PERF (IV)` so the match
cannot be mistaken for evidence that the ism al-tafḍīl is Qur'ānic. Check the
verse in a muṣḥaf. A `? HOMOGRAPH` note must appear above it saying so in
words. (The `sed` narrows to the BAB 1 block; without it the grep also matches
the ism fāʿil of every mazīd form and buries the answer.)

Then check the reverse — a real attestation that must NOT be missed:

    python3 lughat.py sarf سكن 1 | sed -n '/^BAB 1/,/^DERIVED/p' | \
      grep -A2 "ism fa'il"

`سَاكِن` must show **EXACT** at 25:45 (`سَاكِنًا`). If it says "not found", the
accusative tanwīn's alif is being left in the stem and real evidence is being
hidden — the mirror-image failure, and just as wrong.

---

## What a finding looks like

Worth reporting, in descending order of severity:

1. A string attributed to a source that the source does not say.
2. A `verified = 0` row reaching output.
3. A generated form presented as correct when the rules do not derive it
   (a weak root without the UNVERIFIED mark; a bāb stated without a citation).
4. A skeleton match presented as attestation, or an attestation missed.
5. Wrong Arabic — a template producing a non-word for a *sound* root.
6. A crash on input a person would plausibly type.

Not worth reporting: missing features, wording preferences, or the tool
refusing to answer something it has told you it cannot answer. **A refusal is
not a bug.** The gaps are the product.

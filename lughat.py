#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lughat.py — a local Qur'anic lexicography tool.  Offline, stdlib only.

================================ GOVERNING RULE ===============================

  No language model output may ever reach the user.  The query path is pure
  retrieval from a database.  Every user-visible string is either

      (a) verbatim text from a named source, with a page citation, or
      (b) the output of a deterministic rule engine.

  Where a rule does not determine the answer, the tool REFUSES and says so.
  It never guesses, never paraphrases a source, never generates an
  attribution.  A visible gap is correct output.  A plausible fabrication
  attributed to a named scholar is the worst possible failure of this
  program -- worse than crashing.

  Rows with verified = 0 are never served.  Enforced in the query layer.

===============================================================================

Attribution required by the licences of the bundled data:

  Quranic Arabic Corpus (morphology, v0.4) -- (C) 2011 Kais Dukes, GNU GPL.
  http://corpus.quran.com
  Tanzil Qur'an text (Uthmani, 1.0.2) -- (C) 2008-2009 Tanzil.info,
  CC BY-ND 3.0.  http://tanzil.info

Usage:
    lughat.py setup [--from PATH] [--rebuild]
                                  download / load the corpus
    lughat.py test                  INTEGRITY + HONESTY test suites
    lughat.py sarf <root> [bab]     ishtiqaq saghir, with refusals
    lughat.py root <root>           corpus occurrences of a root
    lughat.py word <word>           search the mushaf text
  lughat.py bab [<root>|--derive] the bab, read off the Qur'an's vowelling
  lughat.py ilal --check          check the i'lal rules against the Qur'an
  lughat.py akbar <root>          the six permutations, per Ibn Jinni
  lughat.py letter <root|letter>  Ibn Jinni on the root's letters
  lughat.py mentions <root>       books not keyed by root, searched
  lughat.py tafsir <sura:aya>     approved commentary on an ayah
  lughat.py translation [--add=K] a translation beside the Arabic
  lughat.py aya <sura:aya>        print an ayah, to check against a mushaf
  lughat.py ingest <lexicon> --from PATH
                                  load a lexicon, ALL at verified = 0
                                  lexicons: maqayis, mufradat, lisan
  lughat.py review [--stats]      the approval gate, in the terminal
  lughat.py review --root=<root>  decide one root's entries now
  lughat.py serve [--port=N]      the same gate as a local page (127.0.0.1)
  lughat.py read [--port=N]       the READING surface: approved sources only
"""

import collections
import contextlib
import inspect
import hashlib
import io
import json
import threading
import os
import secrets
import re
import sqlite3
import sys
import tarfile
import traceback
import unicodedata

# --------------------------------------------------------------------------
# Locations
# --------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
LUGHAT_HOME = os.environ.get("LUGHAT_HOME", os.path.join(HERE, "data"))
DB_PATH = os.path.join(LUGHAT_HOME, "lughat.db")
CORPUS_TXT = os.path.join(LUGHAT_HOME, "quranic-corpus-morphology-0.4.txt")
CORPUS_URL = ("https://codeload.github.com/cltk/"
              "arabic_morphology_quranic-corpus/tar.gz/master")
CORPUS_MEMBER = "quranic-corpus-morphology-0.4.txt"

# The load is correct only if it produces exactly these counts.
EXPECT_SEGMENTS = 128219
EXPECT_WORDS = 77429
EXPECT_AYAT = 6236
EXPECT_ROOTS = 1642
EXPECT_SURAS = 114


# ==========================================================================
# 1.  BUCKWALTER  <->  ARABIC
# ==========================================================================
#
# The Quranic Arabic Corpus uses Buckwalter transliteration extended with the
# Uthmani annotation marks.  The mapping is a bijection between single
# characters, so the conversion is exactly reversible in both directions.
#
# TRAP: '`' is U+0670 ARABIC LETTER SUPERSCRIPT ALEF -- the dagger alif.  It
# is encoded as a diacritic but it is linguistically an alif.  See section 2.

BW_TO_AR = {
    # --- consonants and long vowels -------------------------------------
    "'": "ء",   # HAMZA                          ء
    "|": "آ",   # ALEF WITH MADDA ABOVE          آ
    ">": "أ",   # ALEF WITH HAMZA ABOVE          أ
    "&": "ؤ",   # WAW WITH HAMZA ABOVE           ؤ
    "<": "إ",   # ALEF WITH HAMZA BELOW          إ
    "}": "ئ",   # YEH WITH HAMZA ABOVE           ئ
    "A": "ا",   # ALEF                           ا
    "b": "ب",   # BEH                            ب
    "p": "ة",   # TEH MARBUTA                    ة
    "t": "ت",   # TEH                            ت
    "v": "ث",   # THEH                           ث
    "j": "ج",   # JEEM                           ج
    "H": "ح",   # HAH                            ح
    "x": "خ",   # KHAH                           خ
    "d": "د",   # DAL                            د
    "*": "ذ",   # THAL                           ذ
    "r": "ر",   # REH                            ر
    "z": "ز",   # ZAIN                           ز
    "s": "س",   # SEEN                           س
    "$": "ش",   # SHEEN                          ش
    "S": "ص",   # SAD                            ص
    "D": "ض",   # DAD                            ض
    "T": "ط",   # TAH                            ط
    "Z": "ظ",   # ZAH                            ظ
    "E": "ع",   # AIN                            ع
    "g": "غ",   # GHAIN                          غ
    "_": "ـ",   # TATWEEL                        ـ
    "f": "ف",   # FEH                            ف
    "q": "ق",   # QAF                            ق
    "k": "ك",   # KAF                            ك
    "l": "ل",   # LAM                            ل
    "m": "م",   # MEEM                           م
    "n": "ن",   # NOON                           ن
    "h": "ه",   # HEH                            ه
    "w": "و",   # WAW                            و
    "Y": "ى",   # ALEF MAKSURA                   ى
    "y": "ي",   # YEH                            ي
    # --- harakat --------------------------------------------------------
    "F": "ً",   # FATHATAN                       ً
    "N": "ٌ",   # DAMMATAN                       ٌ
    "K": "ٍ",   # KASRATAN                       ٍ
    "a": "َ",   # FATHA                          َ
    "u": "ُ",   # DAMMA                          ُ
    "i": "ِ",   # KASRA                          ِ
    "~": "ّ",   # SHADDA                         ّ
    "o": "ْ",   # SUKUN                          ْ
    "^": "ٓ",   # MADDAH ABOVE                   ٓ
    "#": "ٔ",   # HAMZA ABOVE (combining)        ٔ
    "`": "ٰ",   # SUPERSCRIPT (DAGGER) ALEF      ٰ
    "{": "ٱ",   # ALEF WASLA                     ٱ
    # --- Uthmani annotation marks ---------------------------------------
    ":": "ۜ",   # SMALL HIGH SEEN                ۜ
    "@": "۟",   # SMALL HIGH ROUNDED ZERO        ۟
    '"': "۠",   # SMALL HIGH UPRIGHT RECT. ZERO  ۠
    "[": "ۢ",   # SMALL HIGH MEEM ISOLATED       ۢ
    ";": "ۣ",   # SMALL LOW SEEN                 ۣ
    ",": "ۥ",   # SMALL WAW                      ۥ
    ".": "ۦ",   # SMALL YEH                      ۦ
    "!": "ۨ",   # SMALL HIGH NOON                ۨ
    "-": "۪",   # EMPTY CENTRE LOW STOP          ۪
    "+": "۫",   # EMPTY CENTRE HIGH STOP         ۫
    "%": "۬",   # ROUNDED HIGH STOP FILLED       ۬
    "]": "ۭ",   # SMALL LOW MEEM                 ۭ
}

AR_TO_BW = {v: k for k, v in BW_TO_AR.items()}
assert len(AR_TO_BW) == len(BW_TO_AR), "transliteration table is not a bijection"

# One corpus segment contains a space: (37:130:3:1) "<ilo yaAsiyna" = إِلْ يَاسِينَ,
# a proper name written as two orthographic words but annotated as one segment.
# The space is part of the data, so it passes through unchanged in both
# directions.  It is kept out of BW_TO_AR so that table stays a letter table.
PASSTHROUGH = {" "}


class TransliterationError(ValueError):
    """Raised on a character outside the table.  We refuse rather than drop."""


def to_arabic(bw):
    """Buckwalter -> Arabic.  Strict: an unknown character is an error, never
    silently dropped, because a silently dropped character would corrupt a
    string we later show to the user as if it were the source's."""
    out = []
    for ch in bw:
        if ch in PASSTHROUGH:
            out.append(ch)
            continue
        try:
            out.append(BW_TO_AR[ch])
        except KeyError:
            raise TransliterationError(
                "no Arabic for Buckwalter %r (U+%04X) in %r"
                % (ch, ord(ch), bw))
    return "".join(out)


def to_buckwalter(ar):
    """Arabic -> Buckwalter.  Strict, for the same reason."""
    out = []
    for ch in ar:
        if ch in PASSTHROUGH:
            out.append(ch)
            continue
        try:
            out.append(AR_TO_BW[ch])
        except KeyError:
            raise TransliterationError(
                "no Buckwalter for %r (U+%04X %s) in %r"
                % (ch, ord(ch), unicodedata.name(ch, "?"), ar))
    return "".join(out)


_LEMMA_HOM_RE = re.compile(r"^(.*?)([0-9]+)$")


def split_lemma(lemma_bw):
    """QAC disambiguates homographous lemmas with a trailing index: `maE` vs
    `maE2`, `ma`lik` vs `ma`lik2` (مَٰلِك the participle vs مَالِك the name).
    That digit is DATA, not noise -- dropping it would merge two words the
    corpus deliberately keeps apart, which is the same class of error as
    diacritic-blind matching.  Return (letters, index-or-None)."""
    if lemma_bw is None:
        return None, None
    m = _LEMMA_HOM_RE.match(lemma_bw)
    if m:
        return m.group(1), int(m.group(2))
    return lemma_bw, None


def is_arabic(s):
    return any("؀" <= ch <= "ۿ" for ch in s)


# ==========================================================================
# 2.  SEARCH NORMALISATION
# ==========================================================================
#
# THE DAGGER ALIF TRAP
# --------------------
# The mushaf writes masakin as  مَسَٰكِينِ  -- the alif of the broken plural is
# drawn as U+0670, a superscript mark.  Strip it with the other marks and
# masakin collapses into miskin: a search for مساكين finds nothing.
#
# But you cannot just promote every dagger alif to a full alif either.  The
# reader types مساكين *with* the alif and رحمن *without* it, and both must
# work.  So we index BOTH readings of every string and match a query,
# normalised both ways, against both columns.
#
# These keys are SEARCH KEYS.  They are never displayed.  Showing one would be
# showing the user a string no source ever wrote.

DAGGER_ALIF = "ٰ"
ALIF = "ا"
SHADDA = "ّ"

# Everything removed by normalisation *except* the dagger alif, which is
# handled first and separately because it is linguistically a letter.
_MARKS = set()
_MARKS.update(chr(c) for c in range(0x064B, 0x0660))   # harakat, shadda, sukun,
                                                       # maddah, combining hamza
_MARKS.update(chr(c) for c in range(0x06D6, 0x06EE))   # Uthmani annotation marks
_MARKS.add("ـ")                                   # tatweel
_MARKS.discard(DAGGER_ALIF)

_FOLD = {
    "آ": ALIF,   # آ
    "أ": ALIF,   # أ
    "إ": ALIF,   # إ
    "ٱ": ALIF,   # ٱ
    "ى": "ي",   # ى -> ي
    "ة": "ه",   # ة -> ه
}


MADDAH = "ٓ"          # U+0653, a prosodic lengthening mark
ALIF_MAKSURA = "ى"


def _fold_maksura_dagger(s):
    """A dagger alif sitting ON an alif maksura is a reading aid, not a second
    letter: عَلَىٰ is 'alaa, spelled with the maksura as its carrier. Promoting
    it to a full alif produced علىا, which no one types and which split رَمَىٰ
    from every other spelling of the same word."""
    return s.replace(ALIF_MAKSURA + DAGGER_ALIF, ALIF_MAKSURA)


def _normalise(s, dagger):
    """dagger='alif' promotes U+0670 to a full alif; dagger='drop' deletes it."""
    s = _fold_maksura_dagger(s)
    if dagger == "alif":
        s = s.replace(DAGGER_ALIF, ALIF)
    elif dagger == "drop":
        s = s.replace(DAGGER_ALIF, "")
    else:
        raise ValueError("dagger must be 'alif' or 'drop'")
    out = []
    for ch in s:
        if ch in _MARKS:
            continue
        out.append(_FOLD.get(ch, ch))
    return "".join(out)


def norm_alif(s):
    """Search key, reading the dagger alif as an alif:  مَسَٰكِينِ -> مساكين"""
    return _normalise(s, "alif")


def norm_drop(s):
    """Search key, dropping the dagger alif:  ٱلرَّحْمَٰنِ -> الرحمن"""
    return _normalise(s, "drop")


def query_keys(s):
    """Both readings of a user's query, deduplicated."""
    keys = [norm_alif(s), norm_drop(s)]
    return sorted({k for k in keys if k})


# --- keys used for attestation, which is a stricter comparison -------------

_ANNOTATION = set(chr(c) for c in range(0x06D6, 0x06EE)) | {"ـ"}
_TANWIN = {"ً", "ٌ", "ٍ"}
_SHORT = {"َ", "ُ", "ِ", "ْ"}


WASLA = "ٱ"          # U+0671 ALEF WASLA
FATHATAN = "ً"       # U+064B


def strip_wasl(s):
    """Word-initial hamzat al-wasl is an orthographic prop, not part of the
    stem.  The mushaf writes ٱسْكُنْ; the citation form of the same imperative
    is اُسْكُنْ.  Same word, different orthography.

    Applied to the RAW string, before any alif folding, and deliberately
    narrow:
      * ٱ (alef wasla) word-initially is always wasl -- always stripped;
      * a bare ا word-initially is stripped only when a haraka sits on it
        (اُ / اِ), which is exactly how the citation form spells wasl;
      * أ إ آ are hamzat al-qat', phonemic, and are NEVER touched -- fold
        them first and إِلَىٰ loses its hamza and becomes لى.
    """
    if not s:
        return s
    if s[0] == WASLA:
        i = 1
    elif s[0] == ALIF and len(s) > 1 and s[1] in _SHORT:
        i = 1
    else:
        return s
    while i < len(s) and (s[i] in _SHORT or s[i] in _TANWIN):
        i += 1
    return s[i:] or s


def strip_tanwin_alif(s):
    """The alif of the accusative tanwin (سَاكِنًا) is inflection carried in
    the spelling, not a letter of the stem.  A final alif immediately after
    fathatan always is one."""
    if len(s) >= 2 and s[-1] == ALIF and s[-2] == FATHATAN:
        return s[:-2]
    return s


SUKUN = "ْ"


def _canon_marks(s):
    """Two identical words can hold their combining marks in different ORDER:
    the corpus writes نَزَّلَ as zain+shadda+fatha, a template builds it as
    zain+fatha+shadda.  Byte comparison calls them different words and throws
    away real attestation.  NFC reorders combining marks canonically (by
    combining class), so both become the same string.

    The sukun is also dropped.  The Uthmani text does not write it everywhere
    a template does (يَنزِلُ / يَنْزِلُ, أَنزَلَ / أَنْزَلَ) and its absence marks
    no vowel, so it carries no contrast that could distinguish two words --
    while a real vowel is untouched and still does."""
    # The maddah goes too. It marks prosodic lengthening before a following
    # hamza -- دَعَآ and دَعَا are one word written twice -- and carries no
    # contrast that could separate two words.
    s = _fold_maksura_dagger(s).replace(MADDAH, "")
    return unicodedata.normalize("NFC", s).replace(SUKUN, "")


ALIF_OTIOSE_MARK = "۟"      # U+06DF, the small high rounded zero


def _drop_otiose_alif(s):
    """يَعْفُوا۟ ends in an alif the mushaf marks as SILENT. Stripping the mark
    first (it is an annotation) left the alif behind and split the word from
    every spelling without it."""
    return re.sub(ALIF + ALIF_OTIOSE_MARK, "", s)


def stem_core(s):
    """The vowelled stem, for EXACT comparison.

    Keeps every internal haraka and shadda -- مَسْكَن and مِسْكَن must NOT
    compare equal.  Removes only: Uthmani annotation marks, tatweel, the
    dagger alif's *encoding* (promoted to a real alif, since it IS an alif),
    and the final iʿrab / tanwin, which is inflection rather than the stem."""
    # BEFORE any dagger promotion: a dagger on an alif maksura is a reading
    # aid on its carrier, not a second letter. And before annotations are
    # stripped, because the otiose alif is identified BY its annotation.
    s = _drop_otiose_alif(_fold_maksura_dagger(s))
    s = "".join(ch for ch in s if ch not in _ANNOTATION)
    s = strip_wasl(s)                 # BEFORE folding: see strip_wasl
    s = s.replace(WASLA, ALIF)
    s = s.replace(DAGGER_ALIF, ALIF)  # the dagger alif IS an alif
    s = strip_tanwin_alif(s)
    # A word never begins with a shadda on its own; in the Uthmani text a
    # leading one is assimilation with the PRECEDING word (فَمَّاتَ), so it is
    # not part of this word's stem.
    while len(s) > 1 and s[1] == SHADDA:
        s = s[0] + s[2:]
    # Canonical mark ORDER first, then strip the final i'rab. Doing it the
    # other way round made the result depend on how the marks were typed:
    # مَدَّ written د+shadda+fatha lost its fatha (trailing) while the same
    # word written د+fatha+shadda kept it (the shadda was trailing), so one
    # word compared as two -- the very trap NFC was added to close.
    s = _canon_marks(strip_tanwin_alif(s))
    while s and (s[-1] in _TANWIN or s[-1] in _SHORT):
        s = s[:-1]
    # a final shadda is phonemic and stays, but the i'rab vowel NFC has just
    # moved in front of it is still inflection
    if s.endswith(SHADDA) and len(s) > 1 and s[-2] in _SHORT | _TANWIN:
        s = s[:-2] + SHADDA
    # Word-final alif maksura IS a final alif -- تَلَا and تَلَى are one word
    # written two ways, and the mushaf uses whichever the context calls for.
    if s.endswith(ALIF_MAKSURA):
        # After a fatha the maksura spells a final ALIF (تَلَى = تَلَا).
        # After a kasra it spells a final YAA written defectively
        # (يَقْضِى = يَقْضِي). Folding both to alif merged يَرْمِي with يَرْمَا.
        prev = s[-2] if len(s) > 1 else ""
        s = s[:-1] + (YAA if prev == KASRA else ALIF)
    return s


def skeleton(s):
    """Consonantal skeleton used for ATTESTATION lookup.  Must agree with
    stem_core about the wasl prop, or a form whose core matches would never
    be retrieved in the first place.

    Two words with the same skeleton are NOT the same word -- see
    مَسْكَن / مِسْكَن / مُسْكَن / أَسْكَن."""
    return _canon_marks(norm_alif(strip_tanwin_alif(strip_wasl(s))))


# ==========================================================================
# 3.  ROOT CLASSIFICATION
# ==========================================================================
#
# This IS derivable from the letters, and so is done by rule.  What is NOT
# derivable from the letters is the bab -- see section 4 and roots.bab.

WEAK_LETTERS = {"و", "ي"}
HAMZA = "ء"
HAMZA_LETTERS = {"ء", "أ", "إ", "آ", "ؤ", "ئ"}
GUTTURALS = {"ء", "أ", "إ", "آ", "ؤ", "ئ", "ه", "ع", "ح", "غ", "خ"}

# A radical slot holds one of 28 consonants.  Everything else that can appear
# in a root string is a SPELLING of one of them:
#
#   ا آ أ إ ٱ ؤ ئ  -> hamza.  An Arabic root never has a true alif radical;
#                     the corpus writes a hamza radical as Buckwalter 'A'
#                     (ROOT:Alh, ROOT:nbA), and a person types أ or ا.
#   ى             -> yaa.  Alef maksura is how a final yaa radical is
#                     ordinarily typed (رمى for ر م ي), and reading it as
#                     anything else makes a naqis root look salim.
#
# The loader and the query path MUST agree on this, or a root typed one way
# can never match a root stored the other way.  Both call canonical_root().

_RADICAL_FOLD = {}
for _ch in "اآأإٱؤئ":
    _RADICAL_FOLD[_ch] = HAMZA
_RADICAL_FOLD["ى"] = "ي"

_NOT_A_RADICAL = {"ة": "taa marbuta is a suffix, never a radical"}

# The Arabic block holds punctuation and digits (، ؛ ؟ ٠-٩ ٪) as well as
# letters. canonical_root() promises to RAISE on anything that cannot be a
# radical; it was silently passing them through, so three entries were filed
# under roots like صور، .
_RADICAL_LETTERS = set("ءابتثجحخدذرزسشصضطظعغفقكلمنهوي") | set("آأإٱؤئىة")


def canonical_root(root):
    """Accept Arabic (سكن، رمى، اله) or Buckwalter (skn, rmY, Alh) and return
    the radicals in one canonical spelling.  Raises on anything that cannot
    be a radical, rather than dropping it."""
    if root is None:
        raise ValueError("empty root")
    root = root.strip()
    if not root:
        raise ValueError("empty root")
    if not is_arabic(root):
        root = to_arabic(root)
    letters = []
    for ch in root:
        if ch in _MARKS or ch == DAGGER_ALIF or ch.isspace():
            continue
        if ch in _NOT_A_RADICAL:
            raise ValueError("%r cannot be a radical: %s"
                             % (ch, _NOT_A_RADICAL[ch]))
        if ch not in _RADICAL_LETTERS:
            raise ValueError("%r (U+%04X) is not an Arabic letter, so it "
                             "cannot be a radical" % (ch, ord(ch)))
        letters.append(_RADICAL_FOLD.get(ch, ch))
    if not letters:
        raise ValueError("no radicals in %r (only marks?)" % root)
    if not 2 <= len(letters) <= 5:
        raise ValueError("a root has 2-5 radicals; %r has %d"
                         % ("".join(letters), len(letters)))
    return letters


def root_letters(root):
    """Backwards-compatible alias.  One spelling, one code path."""
    return canonical_root(root)


class RootClass(object):
    """Deterministic classification.  `sound` is the only case for which the
    naive wazn templates in section 4 are trustworthy."""

    def __init__(self, letters):
        self.letters = letters
        self.n = len(letters)
        self.kinds = []          # e.g. ['ajwaf']
        self.reasons = []        # human-readable, rule-derived
        self._classify()

    def _classify(self):
        L = self.letters
        n = self.n
        pos_names = {0: "al-faa", 1: "al-ayn", 2: "al-laam", 3: "the fourth"}

        for i, ch in enumerate(L):
            if ch in HAMZA_LETTERS:
                self.kinds.append("mahmuz")
                self.reasons.append(
                    "mahmuz %s: radical %d is hamza (%s) -- needs ibdal rules"
                    % (pos_names.get(i, "R%d" % (i + 1)), i + 1, ch))

        if n == 3:
            if L[0] in WEAK_LETTERS and L[2] in WEAK_LETTERS:
                self.kinds.append("lafif_mafruq")
                self.reasons.append(
                    "lafif mafruq: R1 (%s) and R3 (%s) are both weak" % (L[0], L[2]))
            elif L[1] in WEAK_LETTERS and L[2] in WEAK_LETTERS:
                self.kinds.append("lafif_maqrun")
                self.reasons.append(
                    "lafif maqrun: R2 (%s) and R3 (%s) are both weak" % (L[1], L[2]))
            else:
                if L[0] in WEAK_LETTERS:
                    self.kinds.append("mithal")
                    self.reasons.append(
                        "mithal: R1 (%s) is weak -- needs i'lal" % L[0])
                if L[1] in WEAK_LETTERS:
                    self.kinds.append("ajwaf")
                    self.reasons.append(
                        "ajwaf: R2 (%s) is weak -- needs i'lal "
                        "(naive templating gives the non-word form)" % L[1])
                if L[2] in WEAK_LETTERS:
                    self.kinds.append("naqis")
                    self.reasons.append(
                        "naqis: R3 (%s) is weak -- needs i'lal" % L[2])
            if L[1] == L[2]:
                self.kinds.append("mudaaf")
                self.reasons.append(
                    "mudaaf: R2 and R3 are the same letter (%s) -- needs idgham"
                    % L[1])
        elif n == 4:
            self.kinds.append("rubaai")
            self.reasons.append(
                "quadriliteral root: the thulathi abwab below do not apply")
            for i, ch in enumerate(L):
                if ch in WEAK_LETTERS:
                    # NOT flagged as needing i'lal.  A weak radical in a
                    # quadriliteral does not undergo it: the corpus reads
                    # وَسْوَسَ (7:20) and يُوَسْوِسُ (114:5), which is exactly what
                    # the template produces.  An earlier build flagged these
                    # UNVERIFIED and was contradicted by its own attestation.
                    self.kinds.append("weak_rubaai_no_ilal")
                    self.reasons.append(
                        "weak letter (%s) at position %d, but a rubaai does "
                        "not take i'lal on it (cf. وَسْوَسَ, 7:20)"
                        % (ch, i + 1))
        else:
            self.kinds.append("unsupported")
            self.reasons.append(
                "root has %d radicals; only 3 and 4 are handled" % n)

        if not self.kinds:
            self.kinds.append("salim")
            self.reasons.append(
                "sahih salim: no weak letter, no hamza, no doubling")

    @property
    def is_sound(self):
        return self.kinds == ["salim"]

    @property
    def needs_ilal(self):
        return any(k in ("mithal", "ajwaf", "naqis", "lafif_maqrun",
                         "lafif_mafruq") for k in self.kinds)

    @property
    def needs_idgham(self):
        return "mudaaf" in self.kinds

    @property
    def needs_ibdal(self):
        return "mahmuz" in self.kinds

    @property
    def is_thulathi(self):
        return self.n == 3

    def label(self):
        return " + ".join(self.kinds)


    def primary_kind(self):
        """One bucket per root, for tallies.  Precedence follows what the
        generator actually needs: i'lal first (it is what breaks the naive
        templates), then idgham.  mahmuz roots count as salim here because
        ibdal, not i'lal, is what they need."""
        # lafif gets its own bucket: a root weak in TWO positions is not an
        # ajwaf and not a mithal, and folding it into either overstates how
        # well the templates behave on it.
        for k in ("lafif_maqrun", "lafif_mafruq"):
            if k in self.kinds:
                return "lafif"
        for k in ("rubaai", "unsupported"):
            if k in self.kinds:
                return "other"
        for k in ("ajwaf", "naqis", "mithal", "mudaaf"):
            if k in self.kinds:
                return k
        return "salim"


def classify_root(root):
    return RootClass(root_letters(root))


# ==========================================================================
# 4.  WAZN TEMPLATES  (ishtiqaq saghir)
# ==========================================================================
#
# TRAP: templates must NOT be written with Arabic ف ع ل.  Substituting
# radicals one letter at a time into مُسْتَفْعِل corrupts any root that itself
# contains ف, ع or ل: for root ع ل م, replacing ف -> ع puts a ع into the
# pattern that came from the root, and the next replacement (ع -> ل) eats it.
#
# So: Latin F / V / L stand for the first, second and third radical.  They
# cannot collide with Arabic literals, and substitution is a single pass.

PLACEHOLDERS = ("F", "V", "L", "Q")   # Q = 4th radical, rubaai only


def apply_wazn(template, letters):
    """Single-pass substitution of F/V/L/Q by the radicals."""
    mapping = dict(zip(PLACEHOLDERS, letters))
    out = []
    for ch in template:
        if ch in PLACEHOLDERS:
            if ch not in mapping:
                raise ValueError("template %r needs radical %s but the root "
                                 "has only %d" % (template, ch, len(letters)))
            out.append(mapping[ch])
        else:
            out.append(ch)
    return "".join(out)


# --- the six abwab of the thulathi mujarrad -------------------------------
#
# Each entry: madi 3MS, mudari' 3MS, amr 2MS, and the ism makan/zaman, whose
# vowel follows the mudari' by rule (yafEil -> mafEil, else mafEal).
#
# NOTE the maSDAR slot is absent, deliberately, in every one of these.  See
# REFUSAL_MASDAR_MUJARRAD.

ABWAB = {
    1: {"name": "fa'ala yaf'ulu (nasara)",
        "madi": "FَVَLَ", "mudari": "يَFْVُLُ", "amr": "اُFْVُLْ",
        "makan": "مَFْVَL",
        "condition": None},
    2: {"name": "fa'ala yaf'ilu (daraba)",
        "madi": "FَVَLَ", "mudari": "يَFْVِLُ", "amr": "اِFْVِLْ",
        "makan": "مَFْVِL",
        "condition": None},
    3: {"name": "fa'ala yaf'alu (fataha)",
        "madi": "FَVَLَ", "mudari": "يَFْVَLُ", "amr": "اِFْVَLْ",
        "makan": "مَFْVَL",
        "condition": "requires a guttural (ء ه ع ح غ خ) as R2 or R3"},
    4: {"name": "fa'ila yaf'alu (sami'a)",
        "madi": "FَVِLَ", "mudari": "يَFْVَLُ", "amr": "اِFْVَLْ",
        "makan": "مَFْVَL",
        "condition": None},
    5: {"name": "fa'ula yaf'ulu (karuma)",
        "madi": "FَVُLَ", "mudari": "يَFْVُLُ", "amr": "اُFْVُLْ",
        "makan": "مَFْVَL",
        "condition": "always lazim (intransitive)"},
    6: {"name": "fa'ila yaf'ilu (hasiba)",
        "madi": "FَVِLَ", "mudari": "يَFْVِLُ", "amr": "اِFْVِLْ",
        "makan": "مَFْVِL",
        "condition": None},
}

# --- the mazid fih forms --------------------------------------------------
#
# These DO have qiyasi masadir, so deriving them is safe.  Where a form takes
# two qiyasi masadir (III), both are listed; where a form is lazim by rule
# (VII, IX) there is no ism maf'ul and the slot refuses.

MAZID = [
    {"roman": "II",   "name": "fa''ala",
     "madi": "FَVَّLَ", "mudari": "يُFَVِّLُ", "amr": "FَVِّLْ",
     "masdar": ["تَFْVِيL"], "fail": "مُFَVِّL", "maful": "مُFَVَّL"},
    {"roman": "III",  "name": "faa'ala",
     "madi": "FَاVَLَ", "mudari": "يُFَاVِLُ", "amr": "FَاVِLْ",
     "masdar": ["مُFَاVَLَة", "FِVَاL"], "fail": "مُFَاVِL", "maful": "مُFَاVَL"},
    {"roman": "IV",   "name": "af'ala",
     "madi": "أَFْVَLَ", "mudari": "يُFْVِLُ", "amr": "أَFْVِLْ",
     "masdar": ["إِFْVَاL"], "fail": "مُFْVِL", "maful": "مُFْVَL"},
    {"roman": "V",    "name": "tafa''ala",
     "madi": "تَFَVَّLَ", "mudari": "يَتَFَVَّLُ", "amr": "تَFَVَّLْ",
     "masdar": ["تَFَVُّL"], "fail": "مُتَFَVِّL", "maful": "مُتَFَVَّL"},
    {"roman": "VI",   "name": "tafaa'ala",
     "madi": "تَFَاVَLَ", "mudari": "يَتَFَاVَLُ", "amr": "تَFَاVَLْ",
     "masdar": ["تَFَاVُL"], "fail": "مُتَFَاVِL", "maful": "مُتَFَاVَL"},
    {"roman": "VII",  "name": "infa'ala",
     "madi": "اِنْFَVَLَ", "mudari": "يَنْFَVِLُ", "amr": "اِنْFَVِLْ",
     "masdar": ["اِنْFِVَاL"], "fail": "مُنْFَVِL", "maful": None,
     "maful_refusal": "form VII is mutawi' and lazim by rule; it has no "
                      "ism maf'ul"},
    {"roman": "VIII", "name": "ifta'ala",
     "madi": "اِFْتَVَLَ", "mudari": "يَFْتَVِLُ", "amr": "اِFْتَVِLْ",
     "masdar": ["اِFْتِVَاL"], "fail": "مُFْتَVِL", "maful": "مُFْتَVَL"},
    {"roman": "IX",   "name": "if'alla",
     "madi": "اِFْVَLَّ", "mudari": "يَFْVَLُّ", "amr": "اِFْVَLِLْ",
     "masdar": ["اِFْVِLَاL"], "fail": "مُFْVَLّ", "maful": None,
     "maful_refusal": "form IX (colours and bodily defects) is lazim by rule; "
                      "it has no ism maf'ul",
     "note": "form IX is confined to colours and bodily defects "
             "(اِحْمَرَّ، اِعْوَجَّ); whether this root denotes one is not "
             "derivable from its letters, so the pattern applies to very few "
             "roots"},
    {"roman": "X",    "name": "istaf'ala",
     "madi": "اِسْتَFْVَLَ", "mudari": "يَسْتَFْVِLُ", "amr": "اِسْتَFْVِLْ",
     "masdar": ["اِسْتِFْVَاL"], "fail": "مُسْتَFْVِL", "maful": "مُسْتَFْVَL"},
    {"roman": "XI",   "name": "if'aalla",
     "madi": "اِFْVَاLَّ", "mudari": "يَFْVَاLُّ", "amr": "اِFْVَاLِLْ",
     "masdar": ["اِFْVِيLَاL"], "fail": "مُFْVَاLّ", "maful": None,
     "maful_refusal": "form XI, like form IX, is confined to colours and "
                      "defects and is lazim; it has no ism maf'ul",
     "note": "forms IX and XI are confined to colours and bodily defects "
             "(اِحْمَرَّ، اِحْمَارَّ); whether this root denotes one is not "
             "derivable from its letters"},
    {"roman": "XII",  "name": "if'aw'ala",
     "madi": "اِFْVَوْVَLَ", "mudari": "يَFْVَوْVِLُ", "amr": "اِFْVَوْVِLْ",
     "masdar": ["اِFْVِيVَاL"], "fail": "مُFْVَوْVِL", "maful": "مُFْVَوْVَL"},
    {"roman": "XIII", "name": "if'awwala",
     "madi": "اِFْVَوَّLَ", "mudari": "يَFْVَوِّLُ", "amr": "اِFْVَوِّLْ",
     "masdar": ["اِFْVِوَّاL"], "fail": "مُFْVَوِّL", "maful": "مُFْVَوَّL"},
]

# --- the rubaai (quadriliteral) -------------------------------------------
#
# Easier than the thulathi, not harder: there is no bab ambiguity (the mudari'
# is fixed at يُفَعْلِلُ) and NO SAMA'I MASDAR PROBLEM -- فَعْلَلَة and فِعْلَال
# are both qiyasi, so refusal R1 simply does not arise here.  زَلْزَلَ and
# وَسْوَسَ and دَمْدَمَ are Qur'anic; refusing them was a self-imposed gap.

RUBAAI = [
    {"roman": "Q-I",  "name": "fa'lala",
     "madi": "FَVْLَQَ", "mudari": "يُFَVْLِQُ", "amr": "FَVْLِQْ",
     "masdar": ["FَVْLَQَة", "FِVْLَاQ"], "fail": "مُFَVْLِQ",
     "maful": "مُFَVْLَQ"},
    {"roman": "Q-II", "name": "tafa'lala",
     "madi": "تَFَVْLَQَ", "mudari": "يَتَFَVْLَQُ", "amr": "تَFَVْLَQْ",
     "masdar": ["تَFَVْLُQ"], "fail": "مُتَFَVْLِQ", "maful": "مُتَFَVْLَQ"},
    {"roman": "Q-III", "name": "if'anlala",
     "madi": "اِFْVَنْLَQَ", "mudari": "يَFْVَنْLِQُ", "amr": "اِFْVَنْLِQْ",
     "masdar": ["اِFْVِنْLَاQ"], "fail": "مُFْVَنْLِQ", "maful": "مُFْVَنْLَQ"},
    {"roman": "Q-IV", "name": "if'alalla",
     "madi": "اِFْVَLَQَّ", "mudari": "يَFْVَLِQُّ", "amr": "اِFْVَLِQِQْ",
     "masdar": ["اِFْVِLْQَاQ"], "fail": "مُFْVَLِQّ", "maful": None,
     "maful_refusal": "form اِفْعَلَلَّ is lazim; it has no ism maf'ul"},
]

# Derivatives of the thulathi mujarrad other than the verb itself.
FAIL_MUJARRAD = "FَاVِL"          # ism fa'il
MAFUL_MUJARRAD = "مَFْVُوL"       # ism maf'ul
TAFDIL = "أَFْVَL"                # ism tafdil  -- homographic with form IV madi
AALA = ["مِFْVَL", "مِFْVَاL", "مِFْVَLَة"]   # ism ala


# ==========================================================================
# 5.  THE GENERATOR, AND THE TWO REFUSALS
# ==========================================================================
#
# A Refusal is not an error.  It is the correct answer to a question the rules
# do not settle, and it is a first-class output of this program.

REFUSAL_MASDAR_MUJARRAD = (
    "REFUSED. The masdar of the thulathi mujarrad is SAMA'I -- heard, not "
    "derived. Nothing in the root determines whether it is fa'l, fu'ul, "
    "fi'aala, fa'aal or another pattern. This tool will not generate one. "
    "It must be quoted from a lexicon, with volume and page. (The masadir of "
    "the mazid fih forms below ARE qiyasi and are derived.)"
)

REFUSAL_ILAL_UNDECIDED = (
    "REFUSED. The waaw of a mithal root drops before a kasra (وَعَدَ يَعِدُ) "
    "and survives before a fatha (وَجِلَ يَوْجَلُ) -- except where it does "
    "not (وَضَعَ يَضَعُ, وَهَبَ يَهَبُ). Nothing in the letters or the bab "
    "decides which, so this form is not derivable here. Quote it."
)

REFUSAL_BAB_UNKNOWN = (
    "REFUSED. This derivation depends on the bab, and the bab of a root is "
    "not derivable from its letters -- it must be read from a lexicon. "
    "roots.bab is NULL (unsourced) for this root. Pass a bab explicitly to "
    "see the template under that hypothesis, or source the bab first."
)

REFUSAL_FAIL_BAB5 = (
    "REFUSED. The qiyas for bab 5 (fa'ula) is the sifa mushabbaha (fa'iil, "
    "fa'l, fa'al, ...), which is sama'i and not derivable. A fa'il IS heard "
    "from some fa'ula verbs (حَمُضَ فهو حَامِض، طَهُرَ فهو طَاهِر), but that too "
    "is sama'i. Either way this tool cannot derive it: quote it from a "
    "lexicon."
)

REFUSAL_MAFUL_BAB5 = (
    "REFUSED. Bab 5 (fa'ula) is lazim by rule, so it has no direct ism "
    "maf'ul. (One built on a zarf or a jarr-majrur -- مَمْرُورٌ بِه -- is "
    "standard, but that is not derivable from the root either.)"
)

# Form VIII assimilates or replaces its infixed taa' after certain first
# radicals (iSTabara, izdajara, itta'akhara).  Those rules are not implemented.
# اِفْتَعَلَ replaces or assimilates its infixed taa' after these first
# radicals: ص ض ط ظ -> taa becomes طاء (اِصْطَبَرَ); د ذ ز -> daal (اِزْدَجَرَ);
# and ت ث و ي ء assimilate outright (ٱتَّبَعَ، ٱثَّاقَلَ، ٱتَّصَلَ، ٱتَّخَذَ).
# None of those rules is implemented, so forms built on such a root are raw
# templates.  ت is the case that matters most and is easiest to miss: تبع is
# a perfectly SOUND root, so nothing else would have flagged it.
FORM_VIII_TAA_IBDAL = set("صضطظدذز") | set("تثوي") | {HAMZA}

# اِنْفَعَلَ is not built when the faa' is one of these: the nuun of the pattern
# meets a letter it cannot sit before.  ن م ر ل و ي ء -- so اِنْنَصَرَ is not a
# word (the form is اِنْتَصَرَ, form VIII).  For ل ر م some texts phrase this as
# istithqal rather than absolute prohibition; either way the template output
# is not a claim this tool can stand behind.
FORM_VII_BLOCKED_FA = set("نمرلوي") | {HAMZA}


class Refusal(object):
    """A rule did not determine the answer.  Carries the reason, verbatim."""

    def __init__(self, slot, reason):
        self.slot = slot
        self.reason = reason
        self.verified = False
        self.is_refusal = True

    def __repr__(self):
        return "<Refusal %s>" % self.slot


class Form(object):
    """A generated form.  `verified` means: the rule engine's output for this
    slot is trustworthy for THIS root.  False means the template was applied
    but the root needs i'lal / ibdal / idgham that this tool does not do, so
    the string is raw template output and NOT a claim about Arabic.

    Two different kinds of doubt are kept apart, because merging them blunts
    the flag until it means nothing:

      caveats  -- the STRING may be wrong.  The root needs i'lal / ibdal /
                  idgham that this tool does not do.  Sets verified = False.
      notes    -- the string is right, but whether the form EXISTS for this
                  verb depends on something not derivable from the letters
                  (transitivity, comparability, an instrument sense).  Does
                  not set verified = False; it is printed, and it is the
                  reader's to check in a lexicon.
    """

    def __init__(self, slot, text, verified, caveats=None, notes=None):
        self.slot = slot
        self.text = text
        self.verified = bool(verified)
        self.caveats = list(caveats or [])
        self.notes = list(notes or [])
        self.is_refusal = False
        self.attestations = []

    def __repr__(self):
        return "<Form %s %s %s>" % (self.slot, self.text,
                                    "ok" if self.verified else "UNVERIFIED")


def _mk(slot, template, letters, rc, extra_caveats=(), notes=()):
    """Apply a template and attach the honest verdict about its reliability."""
    text = apply_wazn(template, letters)
    caveats = list(extra_caveats)
    if rc.needs_ilal:
        caveats.append("root needs i'lal (weak radical); this tool does not "
                       "apply i'lal, so the string above is raw template "
                       "output and is very probably not the real word")
    if rc.needs_idgham:
        caveats.append("root is mudaaf; idgham rules not applied")
    if rc.needs_ibdal:
        caveats.append("root is mahmuz; hamza ibdal rules not applied")
    return Form(slot, text, verified=not caveats, caveats=caveats,
                notes=list(notes))


def generate(root, bab=None, bab_source=None):
    """Ishtiqaq saghir.  Pure function of (root, bab): no I/O, no database, no
    text from anywhere but the templates above.

    bab is the *user's* hypothesis unless bab_source names a lexicon.
    Returns a dict of sections; values are lists of Form / Refusal."""
    letters = root_letters(root)
    rc = RootClass(letters)
    out = {
        "root": "".join(letters),
        "classification": rc,
        "bab": bab,
        "bab_source": bab_source,
        "mujarrad": [],
        "mujarrad_derived": [],
        "mazid": [],
        "notes": [],
    }

    if rc.n == 4:
        if bab is not None:
            out["notes"].append(
                "You supplied bab %d, but the six abwab are the THULATHI "
                "system. A rubaai has no bab: its mudari' is fixed at "
                "yufa'lilu. The bab is ignored." % bab)
        out["notes"].append(
            "This is a rubaai (quadriliteral). Its masdar is NOT sama'i -- "
            "fa'lala and fi'laal are both qiyasi -- so refusal R1 does not "
            "arise and the masdar below is derived.")
        for spec in RUBAAI:
            section = {"roman": spec["roman"], "name": spec["name"],
                       "forms": []}
            for slot, key in (("madi (3MS)", "madi"),
                              ("mudari' (3MS)", "mudari"),
                              ("amr (2MS)", "amr")):
                section["forms"].append(_mk(slot, spec[key], letters, rc))
            for m in spec["masdar"]:
                section["forms"].append(
                    _mk("masdar (qiyasi)", m, letters, rc))
            section["forms"].append(
                _mk("ism fa'il", spec["fail"], letters, rc))
            if spec["maful"] is None:
                section["forms"].append(
                    Refusal("ism maf'ul", "REFUSED. " + spec["maful_refusal"]))
            else:
                section["forms"].append(_mk(
                    "ism maf'ul", spec["maful"], letters, rc,
                    notes=["holds only if this form of the verb is "
                           "muta'addi; not derivable from the root"]))
            out["mazid"].append(section)
        return out

    if not rc.is_thulathi:
        if bab is not None:
            out["notes"].append(
                "You supplied bab %d, but the six abwab are the THULATHI "
                "system and this root has %d radicals. The bab is ignored."
                % (bab, rc.n))
        out["notes"].append(
            "The six abwab and the mazid fih forms below are the thulathi "
            "system. This root has %d radicals, so they do not apply and are "
            "not shown." % rc.n)
        return out

    # ---- the mujarrad verb, per bab ------------------------------------
    babs = [bab] if bab else sorted(ABWAB)
    for b in babs:
        if b not in ABWAB:
            raise ValueError("bab must be 1..6, got %r" % (bab,))
        spec = ABWAB[b]
        hypothetical = (bab is None) or (bab_source is None)
        section = {
            "bab": b,
            "name": spec["name"],
            "hypothetical": hypothetical,
            "condition": spec["condition"],
            "forms": [],
        }
        # Bab 3's phonological licence IS derivable from the letters.
        bab_caveats = []
        if b == 3:
            # A TENDENCY, not a test.  The usual formulation names the 'ayn or
            # the laam, but أَبَى يَأْبَى is bab 3 with its halq letter at the
            # FAA' -- the stock counterexample.  And the condition is never
            # sufficient: رَجَعَ يَرْجِعُ has 'ayn as R2 and is bab 2.  So this
            # reports what the letters show and claims nothing more.
            gut = [(i, x) for i, x in enumerate(letters) if x in GUTTURALS]
            if gut:
                section["condition"] = (
                    "guttural %s present at R%s -- consistent with bab 3, "
                    "but not proof of it"
                    % ("/".join(x for _, x in gut),
                       "/".join(str(i + 1) for i, _ in gut)))
            else:
                section["condition"] = (
                    "no guttural (ء ه ع ح غ خ) anywhere in this root. Bab 3 "
                    "usually has one at the 'ayn or laam, so bab 3 is "
                    "unlikely here -- but that is a tendency with named "
                    "exceptions, not a rule, and this tool does not decide it")
        ilal = ilal_verb_forms(letters, rc, b)
        kind = rc.primary_kind()
        for slot, key in (("madi (3MS)", "madi"),
                          ("mudari' (3MS)", "mudari"),
                          ("amr (2MS)", "amr")):
            if key in ilal and ilal[key] is None:
                section["forms"].append(Refusal(slot, REFUSAL_ILAL_UNDECIDED))
                continue
            if ilal.get(key) and kind in ILAL_VALIDATED:
                # i'lal applied, and the rules for this class reproduce the
                # mushaf exactly -- so the STRING is trustworthy. Whether this
                # bab is the right one is a separate doubt, carried as a note.
                f = Form(slot, ilal[key], verified=not bab_caveats,
                         caveats=list(bab_caveats),
                         notes=(["i'lal applied; the rules for a %s root "
                                 "reproduce every %s citation form the Qur'an "
                                 "attests (%s)" % (kind, kind,
                                                   ILAL_VALIDATED[kind])]))
                section["forms"].append(f)
                continue
            if ilal.get(key):
                f = _mk(slot, "%s", letters, rc, bab_caveats)
                f.text = ilal[key]
                f.caveats = list(bab_caveats) + [
                    "i'lal applied, but the rules for a %s root reproduce "
                    "only %s of the citation forms the Qur'an attests, so "
                    "this string is not trustworthy" % (
                        kind, ILAL_NOT_VALIDATED.get(kind, "some"))]
                f.verified = False
                section["forms"].append(f)
                continue
            section["forms"].append(
                _mk(slot, spec[key], letters, rc, bab_caveats))

        # ---- REFUSAL 1 -------------------------------------------------
        section["forms"].append(Refusal("masdar", REFUSAL_MASDAR_MUJARRAD))

        if b == 5:
            section["forms"].append(Refusal("ism fa'il", REFUSAL_FAIL_BAB5))
            section["forms"].append(Refusal("ism maf'ul", REFUSAL_MAFUL_BAB5))
        else:
            section["forms"].append(
                _mk("ism fa'il", FAIL_MUJARRAD, letters, rc, bab_caveats))
            section["forms"].append(_mk(
                "ism maf'ul", MAFUL_MUJARRAD, letters, rc, bab_caveats,
                notes=["holds only if the verb is muta'addi; transitivity is "
                       "not derivable from the root and must be sourced"]))
        # ism makan / zaman: vowel follows the mudari', so it needs the bab.
        # The qiyas is right, but there is a closed SAMA'I class of maf'il
        # nouns from verbs that are not bab 2 -- and it is heavily Qur'anic:
        # مَسْجِد (28x, from سَجَدَ يَسْجُدُ), مَشْرِق, مَغْرِب, مَطْلِع, مَوْضِع.
        # The rule cannot know which root is in that class, so it says so.
        makan_notes = list(
            ["derived under bab %d, which is a hypothesis here, not a sourced "
             "fact; a different bab gives a different vowel" % b]
            if hypothetical else [])
        makan_notes.append(
            "the maf'al/maf'il vowel follows the mudari' by qiyas, but a "
            "closed SAMA'I class takes maf'il from verbs that are not bab 2 "
            "(مَسْجِد from سَجَدَ يَسْجُدُ, and مَشْرِق مَغْرِب مَطْلِع مَوْضِع). "
            "Membership is not derivable; check a lexicon before relying on "
            "this vowel")
        section["forms"].append(_mk(
            "ism makan/zaman", spec["makan"], letters, rc, bab_caveats,
            notes=makan_notes))
        out["mujarrad"].append(section)

    # ---- derivatives that do not depend on the bab ----------------------
    out["mujarrad_derived"].append(_mk(
        "ism tafdil", TAFDIL, letters, rc,
        notes=["holds only if the meaning admits comparison and the verb is "
               "thulathi, tamm, mutasarrif, MUTHBAT (not negated), mabni "
               "li-l-ma'lum and not a colour/defect -- seven conditions, none "
               "of them derivable from the letters",
               "HOMOGRAPH 1: this pattern is identical to the madi of form "
               "IV; a corpus hit may be the verb, not the noun. Read the tag.",
               "HOMOGRAPH 2: for a colour or defect root the same string is "
               "the sifa mushabbaha (حمر -> أَحْمَر), which is the very case "
               "the conditions above exclude"]))
    for tpl in AALA:
        out["mujarrad_derived"].append(_mk(
            "ism ala", tpl, letters, rc,
            notes=["the ism ala is only formed from verbs denoting an "
                           "action done with an instrument; not derivable"]))
    if bab is None:
        out["mujarrad_derived"].append(Refusal(
            "ism makan/zaman (unqualified)", REFUSAL_BAB_UNKNOWN))

    # ---- mazid fih -------------------------------------------------------
    for spec in MAZID:
        extra = []
        if spec["roman"] == "VII" and letters[0] in FORM_VII_BLOCKED_FA:
            extra.append("form VII is not built when the faa' is %s "
                         "(ن م ر ل و ي ء): the nuun cannot sit before it, so "
                         "this is not a word -- for such roots the muta'awi' "
                         "sense goes to form VIII" % letters[0])
        if spec["roman"] == "VIII" and letters[0] in FORM_VIII_TAA_IBDAL:
            extra.append("form VIII requires ibdal/idgham of the infixed taa' "
                         "after R1 = %s; that rule is not implemented, so "
                         "these strings are raw templates" % letters[0])
        section = {
            "roman": spec["roman"],
            "name": spec["name"],
            "forms": [],
        }
        fnotes = [spec["note"]] if spec.get("note") else []
        for slot, key in (("madi (3MS)", "madi"),
                          ("mudari' (3MS)", "mudari"),
                          ("amr (2MS)", "amr")):
            section["forms"].append(
                _mk(slot, spec[key], letters, rc, extra, fnotes))
        # mazid masadir are QIYASI -- safe to derive.  This is the one place a
        # masdar may be generated.
        for m in spec["masdar"]:
            section["forms"].append(
                _mk("masdar (qiyasi)", m, letters, rc, extra, fnotes))
        section["forms"].append(
            _mk("ism fa'il", spec["fail"], letters, rc, extra, fnotes))
        if spec["maful"] is None:
            section["forms"].append(
                Refusal("ism maf'ul", "REFUSED. " + spec["maful_refusal"]))
        else:
            # same dependency as the mujarrad's ism maf'ul: forms V and VI in
            # particular are often lazim.
            section["forms"].append(
                _mk("ism maf'ul", spec["maful"], letters, rc, extra,
                    fnotes + ["holds only if this form of the verb is "
                              "muta'addi; transitivity is not derivable from "
                              "the root and must be sourced"]))
        out["mazid"].append(section)

    return out


def all_generated_forms(result):
    """Flatten every Form in a generate() result."""
    forms = []
    for sec in result["mujarrad"]:
        forms.extend(f for f in sec["forms"] if not f.is_refusal)
    forms.extend(f for f in result["mujarrad_derived"] if not f.is_refusal)
    for sec in result["mazid"]:
        forms.extend(f for f in sec["forms"] if not f.is_refusal)
    return forms


def all_refusals(result):
    refs = []
    for sec in result["mujarrad"]:
        refs.extend(f for f in sec["forms"] if f.is_refusal)
    refs.extend(f for f in result["mujarrad_derived"] if f.is_refusal)
    for sec in result["mazid"]:
        refs.extend(f for f in sec["forms"] if f.is_refusal)
    return refs


# ==========================================================================
# 6.  SCHEMA
# ==========================================================================
#
# entries.text_raw   verbatim from the source, or NULL for a scan-only source
#                    (where the page image IS the citation and nothing has
#                    been keyed in).  Never paraphrased, never cleaned up.
# entries.text_norm  a SEARCH KEY.  Never displayed.
# entries.verified   0 rows are never served -- see section 7.
# roots.bab          a SOURCED column.  The bab of a root is not derivable
#                    from its letters; it is read from a lexicon and carries
#                    bab_source_id / bab_page.  NULL means unknown.

SCHEMA_VERSION = 10

SCHEMA = r"""
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS sources (
    id            INTEGER PRIMARY KEY,
    key           TEXT UNIQUE NOT NULL,
    title         TEXT NOT NULL,
    author        TEXT,
    edition       TEXT,
    kind          TEXT NOT NULL,      -- corpus | lexicon | tafsir | scan
    licence       TEXT,
    licence_note  TEXT,
    -- 0 = local personal use only (in copyright, or a licence that forbids
    -- redistribution).  Kept accurate per row so the question "what may this
    -- ever ship with?" stays answerable instead of archaeological.
    distributable INTEGER NOT NULL DEFAULT 0,
    url           TEXT,
    attribution   TEXT NOT NULL       -- reproduced verbatim wherever cited
);

CREATE TABLE IF NOT EXISTS segments (
    id        INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    sura      INTEGER NOT NULL,
    aya       INTEGER NOT NULL,
    word      INTEGER NOT NULL,
    seg       INTEGER NOT NULL,
    form_bw   TEXT NOT NULL,          -- verbatim from the corpus file
    form_ar   TEXT NOT NULL,          -- reversible transliteration of form_bw
    tag       TEXT NOT NULL,          -- verbatim
    features  TEXT NOT NULL,          -- verbatim
    pos       TEXT,
    lemma_bw  TEXT,
    lemma_ar  TEXT,
    lemma_hom INTEGER,          -- QAC homograph index; NULL if none
    root_bw   TEXT,
    root_ar   TEXT,
    is_stem   INTEGER NOT NULL,
    norm_alif TEXT NOT NULL,          -- search key, never displayed
    norm_drop TEXT NOT NULL,          -- search key, never displayed
    core      TEXT NOT NULL,          -- vowelled stem, for EXACT attestation
    skel      TEXT NOT NULL,          -- consonantal skeleton
    UNIQUE (sura, aya, word, seg)
);

CREATE TABLE IF NOT EXISTS words (
    id        INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    sura      INTEGER NOT NULL,
    aya       INTEGER NOT NULL,
    word      INTEGER NOT NULL,
    form_ar   TEXT NOT NULL,          -- concatenation of its segments, verbatim
    norm_alif TEXT NOT NULL,
    norm_drop TEXT NOT NULL,
    UNIQUE (sura, aya, word)
);

CREATE TABLE IF NOT EXISTS roots (
    id          INTEGER PRIMARY KEY,
    root_ar     TEXT UNIQUE NOT NULL,
    root_bw     TEXT NOT NULL,
    n_segments  INTEGER NOT NULL,
    n_lemmas    INTEGER NOT NULL,
    weakness    TEXT NOT NULL,        -- derived by rule from the letters
    -- SOURCED columns.  NULL = unknown, and every derivation that depends on
    -- the bab refuses when it is NULL.  A bab is never inferred.
    bab           INTEGER,
    bab_source_id INTEGER REFERENCES sources(id),
    bab_vol       TEXT,
    bab_page      TEXT,
    bab_verified  INTEGER NOT NULL DEFAULT 0,
    -- how the bab was arrived at, and the evidence for it, so the reader can
    -- check it against a mushaf rather than take the tool's word.
    bab_method    TEXT,
    bab_evidence  TEXT
);

CREATE TABLE IF NOT EXISTS entries (
    id         INTEGER PRIMARY KEY,
    source_id  INTEGER NOT NULL REFERENCES sources(id),
    root_ar    TEXT,
    headword   TEXT,
    text_raw   TEXT,                  -- VERBATIM, or NULL for scan-only
    text_norm  TEXT,                  -- SEARCH KEY -- never displayed
    vol        TEXT,
    page       TEXT,
    scan_uri   TEXT,
    -- how root_ar was arrived at, so review can see what was inferred:
    -- 'direct'         the heading canonicalised straight to this root
    -- 'geminate'       heading had 2 letters, corpus root is the doubled form
    -- 'weak_final'     final و/ي differ between heading and corpus
    -- 'unmatched'      parsed, but no corpus root -- root_ar is the heading's
    -- 'unparsed'       the heading is not a root at all (a bab title, etc.)
    extraction TEXT,
    -- comma-separated warnings raised at ingest and shown at review, e.g.
    -- an entry heading that breaks the source's own alphabetical order.
    flags      TEXT,
    verified   INTEGER NOT NULL DEFAULT 0,
    verified_at TEXT,
    -- A reviewer's "this extraction is wrong". Distinct from merely pending:
    -- without it a bad entry returns to the head of the queue forever.
    rejected   INTEGER NOT NULL DEFAULT 0,
    reject_reason TEXT,
    CHECK (text_raw IS NOT NULL OR scan_uri IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS tafsir (
    id         INTEGER PRIMARY KEY,
    source_id  INTEGER NOT NULL REFERENCES sources(id),
    sura       INTEGER NOT NULL,
    aya        INTEGER NOT NULL,     -- the FIRST ayah of the pericope
    aya_to     INTEGER,              -- the last; NULL means the same one
    anchor_method   TEXT,            -- how (sura, aya) was established
    anchor_evidence TEXT,            -- and on what evidence
    text_raw   TEXT,                  -- VERBATIM, or NULL for scan-only
    text_norm  TEXT,                  -- SEARCH KEY -- never displayed
    vol        TEXT,
    page       TEXT,                 -- where the passage BEGINS
    page_to    TEXT,                 -- where it ends, if that is elsewhere
    scan_uri   TEXT,
    verified   INTEGER NOT NULL DEFAULT 0,
    CHECK (text_raw IS NOT NULL OR scan_uri IS NOT NULL)
);

-- The ONLY sanctioned read paths for sourced prose.  The query layer refuses
-- to run any statement that names the base tables.
-- rejected = 1 is filtered here as well as verified = 1. Every writer today
-- pairs the flags correctly, but "(1,1) is unreachable" is a claim about all
-- future writers. Making it structural costs one clause.
CREATE VIEW IF NOT EXISTS v_entries AS
    SELECT * FROM entries WHERE verified = 1 AND rejected = 0;
CREATE VIEW IF NOT EXISTS v_tafsir AS
    SELECT * FROM tafsir WHERE verified = 1 AND rejected = 0;

-- A translation of the QUR'AN, keyed by ayah.  Not `entries`: nothing here
-- is derived.  The file states sura|aya|text and this table copies it, so
-- there is no inferred attribution for a reviewer to check -- the same
-- footing as `words` and `segments`, which are also served ungated.  What IS
-- checked, at ingest, is that the file's ayah numbering matches the mushaf's
-- exactly; a translation numbered differently would put one verse's words
-- under another, which is the tafsir anchoring failure by another route.
CREATE TABLE IF NOT EXISTS translations (
    id         INTEGER PRIMARY KEY,
    source_id  INTEGER NOT NULL REFERENCES sources(id),
    sura       INTEGER NOT NULL,
    aya        INTEGER NOT NULL,
    text       TEXT NOT NULL,      -- VERBATIM, one line of the source file
    UNIQUE (source_id, sura, aya)
);

CREATE INDEX IF NOT EXISTS ix_entry_root ON entries(root_ar);
CREATE INDEX IF NOT EXISTS ix_entry_ver  ON entries(verified);
CREATE INDEX IF NOT EXISTS ix_seg_root   ON segments(root_ar);
CREATE INDEX IF NOT EXISTS ix_seg_alif   ON segments(norm_alif);
CREATE INDEX IF NOT EXISTS ix_seg_drop   ON segments(norm_drop);
CREATE INDEX IF NOT EXISTS ix_seg_core   ON segments(core);
CREATE INDEX IF NOT EXISTS ix_seg_skel   ON segments(skel);
CREATE INDEX IF NOT EXISTS ix_word_alif  ON words(norm_alif);
CREATE INDEX IF NOT EXISTS ix_word_drop  ON words(norm_drop);
"""

QAC_ATTRIBUTION = ("Quranic Arabic Corpus (morphology, v0.4), "
                   "(C) 2011 Kais Dukes, GNU GPL. http://corpus.quran.com")
TANZIL_ATTRIBUTION = ("Tanzil Qur'an text (Uthmani, 1.0.2), "
                      "(C) 2008-2009 Tanzil.info, CC BY-ND 3.0. "
                      "http://tanzil.info")


# ==========================================================================
# 7.  THE QUERY LAYER  --  verified = 0 is never served
# ==========================================================================

class UnverifiedAccess(RuntimeError):
    """Raised when a query would read sourced prose outside the verified
    views.  This is a bug in the caller, and it is fatal by design."""


# Enforcement is SQLite's own authorizer callback, not a regex over the SQL
# text.  An earlier build pattern-matched the statement string; that was
# defeated by `main.entries`, by `FROM/**/entries`, by a comma cross join, by
# a scalar subquery, and by creating a second view over the base table.  A
# regex sees text; the authorizer sees the actual table SQLite resolved, at
# prepare time, after every alias, qualifier, CTE and view has been expanded.
#
# Reads of entries/tafsir are permitted ONLY when SQLite reports that the read
# is happening through v_entries / v_tafsir, which carry WHERE verified = 1.

_GUARDED_TABLES = ("entries", "tafsir")
_ALLOWED_VIEWS = ("v_entries", "v_tafsir")


def _authorizer(action, arg1, arg2, dbname, trigger_or_view):
    if action == sqlite3.SQLITE_READ and arg1 in _GUARDED_TABLES:
        if trigger_or_view in _ALLOWED_VIEWS:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _permit_all(action, arg1, arg2, dbname, trigger_or_view):
    """The build path's authorizer.  NOT set_authorizer(None).

    On Python 3.11+ passing None removes the authorizer. On 3.10 and earlier
    it does not: the callback is stored as None, every authorization request
    then fails, and SQLite is told DENY -- so the whole program dies with
    `sqlite3.DatabaseError: not authorized` on statements as innocent as
    counting rows in sqlite_master. Handing SQLite a callback that says yes
    works the same way on every version."""
    return sqlite3.SQLITE_OK


@contextlib.contextmanager
def unguarded(conn):
    """Drop the authorizer for ingestion / review tooling, which legitimately
    writes and reads unverified rows.  The QUERY path never uses this."""
    conn.set_authorizer(_permit_all)
    try:
        yield conn
    finally:
        conn.set_authorizer(_authorizer)


def q(conn, sql, params=()):
    """Every read in the query path goes through here."""
    try:
        return conn.execute(sql, params)
    except sqlite3.DatabaseError as e:
        if "prohibited" in str(e) or "not authorized" in str(e):
            raise UnverifiedAccess(
                "%s -- unverified rows must never be served; read through "
                "v_entries / v_tafsir instead" % e)
        raise


def connect(path=DB_PATH, create=False, threadsafe=False):
    if not create and not os.path.exists(path):
        raise SystemExit(
            "no database at %s -- run:  python3 lughat.py setup" % path)
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    # threadsafe=True is for the review server only: a sqlite3 connection is
    # thread-affine by default, and the browser opens several connections at
    # once.  Every DB touch there is serialised by DB_LOCK.
    conn = sqlite3.connect(path, check_same_thread=not threadsafe)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                    "AND name='entries'").fetchone()[0]:
        migrate(conn)
    conn.set_authorizer(_authorizer)
    return conn


# ==========================================================================
# 8.  LOADING THE CORPUS
# ==========================================================================

_LOC_RE = re.compile(r"^\((\d+):(\d+):(\d+):(\d+)\)$")


def parse_corpus(text):
    """Yield one dict per segment.

    TRAP: the distributed file is CRLF.  FEATURES is the last field, so an
    unstripped \\r makes ROOT:qbl and ROOT:qbl\\r two different roots and the
    root count comes out 1652 instead of 1642."""
    for raw in text.splitlines():
        line = raw.replace("\r", "").rstrip("\n")
        if not line or line.startswith("#") or line.startswith("LOCATION"):
            continue
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        loc, form, tag, feats = parts
        m = _LOC_RE.match(loc.strip())
        if not m:
            continue
        sura, aya, word, seg = (int(x) for x in m.groups())
        fields = feats.split("|")
        is_stem = 1 if "STEM" in fields else 0
        pos = lemma = root = None
        for f in fields:
            if f.startswith("POS:"):
                pos = f[4:]
            elif f.startswith("LEM:"):
                lemma = f[4:]
            elif f.startswith("ROOT:"):
                root = f[5:]
        yield {
            "sura": sura, "aya": aya, "word": word, "seg": seg,
            "form_bw": form, "tag": tag, "features": feats,
            "pos": pos, "lemma_bw": lemma, "root_bw": root,
            "is_stem": is_stem,
        }


def fetch_corpus(dest=CORPUS_TXT, url=CORPUS_URL, from_path=None):
    """Get quranic-corpus-morphology-0.4.txt onto disk.  This is the ONLY
    network access in the program, it happens only during `setup`, and the
    query path never touches the network."""
    d = os.path.dirname(dest)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    if from_path:
        if os.path.isdir(from_path):
            from_path = os.path.join(from_path, CORPUS_MEMBER)
        with open(from_path, "rb") as fh:
            data = fh.read()
        if from_path.endswith((".gz", ".tgz")):
            data = _extract_member(data)
        with open(dest, "wb") as fh:
            fh.write(data)
        return dest
    if os.path.exists(dest):
        return dest
    import urllib.request
    sys.stderr.write("downloading %s\n" % url)
    with urllib.request.urlopen(url) as r:
        blob = r.read()
    with open(dest, "wb") as fh:
        fh.write(_extract_member(blob))
    return dest


def _extract_member(blob):
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        for m in tf.getmembers():
            if os.path.basename(m.name) == CORPUS_MEMBER:
                return tf.extractfile(m).read()
    raise SystemExit("%s not found in the downloaded archive" % CORPUS_MEMBER)


# Columns added after v1.  Migrating rather than rebuilding matters: entries
# may hold rows a person has read and approved, and that work must survive.
_NEW_TABLES = {
    "translations": """
        CREATE TABLE IF NOT EXISTS translations (
            id         INTEGER PRIMARY KEY,
            source_id  INTEGER NOT NULL REFERENCES sources(id),
            sura       INTEGER NOT NULL,
            aya        INTEGER NOT NULL,
            text       TEXT NOT NULL,
            UNIQUE (source_id, sura, aya)
        )""",
    # MACHINE TRANSLATION, and the one table in this database whose text is
    # nobody's words.
    #
    # `translations` above holds a NAMED TRANSLATOR's published lines, which
    # is why it is served ungated: a person wrote them and is credited. This
    # table holds the output of a neural model run over a scholar's Arabic.
    # It is a reading aid the owner of this database asked for, and it is
    # kept apart from every sourced string in the program:
    #
    #   - it is NEVER inside a citation card. The bordered card means
    #     "verbatim, cited"; putting generated Urdu inside it would spend the
    #     one visual promise this page makes.
    #   - it is OFF by default and must be switched on, like the translator
    #     checkboxes -- and for a stronger reason, since no translator's name
    #     stands behind it.
    #   - it records the `engine` and `model` that produced each line, so a
    #     reader can tell WHICH machine, and a later run can replace one
    #     engine's output without touching another's.
    #   - it is keyed to a PARAGRAPH of the rendered entry, not to the entry,
    #     because side-by-side reading needs the two to line up.
    #
    # It is not reviewed, and must never be: `review` stamps verified = 1,
    # which in this program means a person vouched for a SOURCE. Nobody can
    # vouch for this, so it does not enter that gate at all.
    "glosses": """
        CREATE TABLE IF NOT EXISTS glosses (
            id         INTEGER PRIMARY KEY,
            entry_id   INTEGER NOT NULL REFERENCES entries(id),
            para       INTEGER NOT NULL,
            lang       TEXT NOT NULL,
            text       TEXT NOT NULL,
            engine     TEXT NOT NULL,
            model      TEXT NOT NULL,
            created_at TEXT,
            UNIQUE (entry_id, para, lang, engine)
        )""",
}

_MIGRATIONS_V2 = [
    ("sources", "licence_note", "TEXT"),
    ("sources", "distributable", "INTEGER NOT NULL DEFAULT 0"),
    ("entries", "extraction", "TEXT"),
    ("entries", "verified_at", "TEXT"),
    ("tafsir", "extraction", "TEXT"),
    ("tafsir", "verified_at", "TEXT"),
    ("roots", "bab_method", "TEXT"),
    ("roots", "bab_evidence", "TEXT"),
    ("entries", "flags", "TEXT"),
    ("tafsir", "flags", "TEXT"),
    ("entries", "rejected", "INTEGER NOT NULL DEFAULT 0"),
    ("entries", "reject_reason", "TEXT"),
    ("tafsir", "rejected", "INTEGER NOT NULL DEFAULT 0"),
    ("tafsir", "reject_reason", "TEXT"),
    # a pericope covers a RANGE of ayat, and how it was anchored is evidence
    # the reviewer must see -- so it is stored, not recomputed at review time
    ("tafsir", "aya_to", "INTEGER"),
    ("tafsir", "anchor_method", "TEXT"),
    ("tafsir", "anchor_evidence", "TEXT"),
    ("tafsir", "page_to", "TEXT"),
    # HOW a row was approved: read one at a time, or waved through in bulk.
    # The distinction is permanent and shown to the reader, because "a person
    # read this" and "a person accepted the class this belongs to" are not
    # the same claim.
    ("entries", "verified_by", "TEXT"),
    ("tafsir", "verified_by", "TEXT"),
    # WHY an entry is filed under its root, where that was not read off a
    # heading. For a scan-only OCR source the link rests on two agreeing
    # facts, and the second of them -- the ayat the page quotes -- is also
    # what the reader is shown, from the app's OWN mushaf. Stored beside the
    # claim, as bab_evidence and anchor_evidence already are, rather than
    # recomputed at query time where a drift between the two computations
    # would be invisible (trap 8).
    ("entries", "link_evidence", "TEXT"),
    # HOW an entry's page number was arrived at, beside bab_method and
    # anchor_method which answer the same question for other claims. It does
    # NOT go in `flags`: that column drives the alphabetical-order badge, and
    # a warrant that is true of a third of a source would dilute the badge
    # until a reviewer stopped reading it -- which is the failure the order
    # check was tuned to avoid in the first place.
    ("entries", "page_method", "TEXT"),
]


def migrate(conn):
    """Additive only.  Never drops a table that can hold reviewed work."""
    # Checks the actual columns rather than trusting the version stamp: a
    # stamp can run ahead of the table when the version is bumped in the same
    # change that adds a column, and CREATE TABLE IF NOT EXISTS will not add
    # it to a table that already exists.
    #
    # But it must do NOTHING when nothing is missing. connect() calls this on
    # every command, and unconditional DROP VIEW / CREATE VIEW meant a plain
    # `root` lookup took a write lock and raced any other process: four
    # concurrent readers lost ~10% of connections, some to a window in which
    # v_entries did not exist at all.
    if schema_columns_ok(conn) and _views_current(conn):
        if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            conn.execute("PRAGMA user_version = %d" % SCHEMA_VERSION)
            conn.commit()
        return 0
    done = 0
    # A table this build added is created here too: ALTER TABLE cannot add a
    # table, and CREATE TABLE IF NOT EXISTS in SCHEMA only runs at setup.
    for table in _NEW_TABLES:
        if not conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND "
                "name=?", (table,)).fetchone()[0]:
            conn.execute(_NEW_TABLES[table])
            done += 1
    for table, col, decl in _MIGRATIONS_V2:
        exists = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
            (table,)).fetchone()[0]
        if not exists:
            continue
        cols = {r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)}
        if col not in cols:
            conn.execute("ALTER TABLE %s ADD COLUMN %s %s"
                         % (table, col, decl))
            done += 1
    # v_entries / v_tafsir are SELECT *, so they must be rebuilt to see the
    # new columns.
    conn.execute("DROP VIEW IF EXISTS v_entries")
    conn.execute("DROP VIEW IF EXISTS v_tafsir")
    for _name, _body in _VIEW_SQL.items():
        conn.execute("CREATE VIEW %s AS %s" % (_name, _body))
    conn.execute("PRAGMA user_version = %d" % SCHEMA_VERSION)
    conn.commit()
    return done


_VIEW_SQL = {
    "v_entries": "SELECT * FROM entries WHERE verified = 1 AND rejected = 0",
    "v_tafsir": "SELECT * FROM tafsir WHERE verified = 1 AND rejected = 0",
}


def _views_current(conn):
    """True when both verified-only views exist with the expected definition."""
    for name, body in _VIEW_SQL.items():
        row = conn.execute("SELECT sql FROM sqlite_master WHERE type='view' "
                           "AND name=?", (name,)).fetchone()
        if row is None:
            return False
        if " ".join(row[0].split()).lower() != (
                "create view %s as %s" % (name, body)).lower():
            return False
    return True


def schema_columns_ok(conn):
    """True when every column and table this build needs actually exists."""
    for table in _NEW_TABLES:
        if not conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE "
                            "type='table' AND name=?", (table,)).fetchone()[0]:
            return False
    for table, col, _ in _MIGRATIONS_V2:
        ex = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE "
                          "type='table' AND name=?", (table,)).fetchone()[0]
        if ex and col not in {r[1] for r in
                              conn.execute("PRAGMA table_info(%s)" % table)}:
            return False
    return True


def load(conn, path=CORPUS_TXT, rebuild=False):
    with open(path, "rb") as fh:
        text = fh.read().decode("utf-8")

    conn.set_authorizer(_permit_all)   # ingestion, not the query path
    migrate(conn)  # noqa: E501
    have = conn.execute("PRAGMA user_version").fetchone()[0]
    existing = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE "
                            "type='table' AND name='segments'").fetchone()[0]
    if existing and have != SCHEMA_VERSION:
        # Refuse rather than half-migrate: entries/tafsir may hold hand-checked
        # rows, and silently rebuilding would destroy sourced work.
        if not rebuild:
            raise SystemExit(
                "database schema is version %d, this build expects %d.\n"
                "Re-run with --rebuild to drop and reload the corpus tables. "
                "Any rows in entries/tafsir will be preserved only if their "
                "schema is unchanged; back up %s first."
                % (have, SCHEMA_VERSION, DB_PATH))
        for t in ("segments", "words", "roots"):
            conn.execute("DROP TABLE IF EXISTS %s" % t)
    conn.executescript(SCHEMA)
    conn.execute("PRAGMA user_version = %d" % SCHEMA_VERSION)
    cur = conn.cursor()
    for tbl in ("segments", "words", "roots"):
        cur.execute("DELETE FROM %s" % tbl)
    cur.execute("DELETE FROM sources WHERE key IN ('qac','tanzil')")
    cur.execute(
        "INSERT INTO sources (key,title,author,edition,kind,licence,url,"
        "attribution) VALUES (?,?,?,?,?,?,?,?)",
        ("qac", "Quranic Arabic Corpus (morphology)", "Kais Dukes", "0.4",
         "corpus", "GNU GPL", "http://corpus.quran.com", QAC_ATTRIBUTION))
    qac_id = cur.lastrowid
    cur.execute(
        "INSERT INTO sources (key,title,author,edition,kind,licence,url,"
        "attribution) VALUES (?,?,?,?,?,?,?,?)",
        ("tanzil", "Tanzil Qur'an text (Uthmani)", "Tanzil.info", "1.0.2",
         "corpus", "CC BY-ND 3.0", "http://tanzil.info", TANZIL_ATTRIBUTION))

    rows = []
    words = {}
    for r in parse_corpus(text):
        form_ar = to_arabic(r["form_bw"])
        # canonical_root(), the same function the query path uses -- otherwise
        # ROOT:Alh lands under اله while a search for اله asks for ءله and the
        # tool reports 2851 segments as absent.
        root_ar = ("".join(canonical_root(r["root_bw"]))
                   if r["root_bw"] else None)
        lemma_letters, lemma_hom = split_lemma(r["lemma_bw"])
        lemma_ar = to_arabic(lemma_letters) if lemma_letters else None
        rows.append((qac_id, r["sura"], r["aya"], r["word"], r["seg"],
                     r["form_bw"], form_ar, r["tag"], r["features"],
                     r["pos"], r["lemma_bw"], lemma_ar, lemma_hom,
                     r["root_bw"], root_ar,
                     r["is_stem"], norm_alif(form_ar), norm_drop(form_ar),
                     stem_core(form_ar), skeleton(form_ar)))
        key = (r["sura"], r["aya"], r["word"])
        words.setdefault(key, []).append((r["seg"], form_ar))

    cur.executemany(
        "INSERT INTO segments (source_id,sura,aya,word,seg,form_bw,form_ar,"
        "tag,features,pos,lemma_bw,lemma_ar,lemma_hom,root_bw,root_ar,"
        "is_stem,norm_alif,norm_drop,core,skel) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)

    wrows = []
    for (s, a, w), segs in words.items():
        form = "".join(f for _, f in sorted(segs))
        wrows.append((qac_id, s, a, w, form, norm_alif(form), norm_drop(form)))
    cur.executemany(
        "INSERT INTO words (source_id,sura,aya,word,form_ar,norm_alif,"
        "norm_drop) VALUES (?,?,?,?,?,?,?)", wrows)

    # roots: weakness is DERIVED by rule; bab is left NULL because it is not
    # derivable and no lexicon has been loaded yet.
    cur.execute(
        "INSERT INTO roots (root_ar,root_bw,n_segments,n_lemmas,weakness) "
        "SELECT root_ar, root_bw, COUNT(*), COUNT(DISTINCT lemma_bw), '' "
        "FROM segments WHERE root_ar IS NOT NULL GROUP BY root_ar, root_bw")
    for rid, rar in cur.execute("SELECT id, root_ar FROM roots").fetchall():
        conn.execute("UPDATE roots SET weakness=? WHERE id=?",
                     (RootClass(root_letters(rar)).label(), rid))
    conn.commit()
    conn.set_authorizer(_authorizer)
    return counts(conn)


def counts(conn):
    c = conn.cursor()
    return {
        "segments": c.execute("SELECT COUNT(*) FROM segments").fetchone()[0],
        "words": c.execute("SELECT COUNT(*) FROM words").fetchone()[0],
        "ayat": c.execute(
            "SELECT COUNT(*) FROM (SELECT DISTINCT sura,aya FROM segments)"
        ).fetchone()[0],
        "suras": c.execute(
            "SELECT COUNT(DISTINCT sura) FROM segments").fetchone()[0],
        "roots": c.execute("SELECT COUNT(*) FROM roots").fetchone()[0],
    }


# ==========================================================================
# 8b.  INGESTION  --  lexicons
# ==========================================================================
#
# Ingestion is the BUILD path, and it is kept away from the query path on
# purpose.  What it writes is verified = 0, always, without exception, and
# verified = 0 is never served.  Nothing here is servable until a person has
# looked at it and said so (`lughat.py review`).
#
# The text is copied BYTE FOR BYTE.  What is stored in entries.text_raw is
# exactly the bytes of the source block, OpenITI markup included; the markup
# is stripped at DISPLAY time by the documented rule in render_entry(), so the
# transformation is readable and reversible instead of baked in.

# Arabic alphabetical order, used to check a source against its OWN ordering.
# A heading that goes backwards is not a new letter-section: it is a sub-entry,
# a title, or a digitisation artifact -- and the last of those is how one
# root's article gets filed under another.
ALPHABET = "ءابتثجحخدذرزسشصضطظعغفقكلمنهوي"


def alpha_key(root):
    return tuple(ALPHABET.index(c) if c in ALPHABET else 99 for c in root)


MAQAYIS_ATTRIBUTION = (
    "Ibn Faris, Mu'jam Maqayis al-Lugha, ed. 'Abd al-Salam Muhammad Harun "
    "(Beirut: Dar al-Jil, 1420/1999), 6 vols. Digital text: OpenITI, "
    "CC BY-NC-SA. https://github.com/OpenITI")

MUFRADAT_ATTRIBUTION = (
    "al-Raghib al-Isbahani, al-Mufradat fi Gharib al-Qur'an. Digital text: "
    "OpenITI, CC BY-NC-SA. https://github.com/OpenITI")

_HDR_RE = re.compile(r"^### \|+ *(.*)$")
_PAGE_RE = re.compile(r"PageV(\d+)P(\d+)")
_MS_RE = re.compile(r"\bms\d+\b")


# An entry heading in this witness is ALWAYS parenthesised: (سكن), (أبت).
# Anything else on a "### |" line is one of two other things, and neither is
# an entry:
#
#   [باب الهمزة والتاء وما يثلثهما]   a section title
#   اله  /  آخ  /  : إذ  /  اح        a DIGITISATION ARTIFACT -- a header
#                                     inserted in the middle of a word
#
# The artifacts are the dangerous ones.  "### | اله" is followed by
# "# مزة والكاف والراء أصل واحد، وهو الحفر" -- that is the word الهمزة split
# across a header boundary, and the fragment اله canonicalises to ءله, the
# root of الله.  Treating it as a heading files Ibn Faris on أكر under the
# root of the divine name.  A lexicography tool that does that is worse than
# one with no lexicon in it.
#
# So: only (...) starts an entry.  A [...] line closes the current entry and
# starts nothing.  Every other "### |" line is TEXT belonging to the entry in
# progress, rejoined using exactly the whitespace the source itself has --
# "اله" + "مزة" -> الهمزة, "إن " + "إلك" -> إن إلك.  No spacing is invented.

_ENTRY_HDR_RE = re.compile(r"^\(\s*([؀-ۿ]+)\s*\)\s*[:\-]?\s*$")
_SECTION_HDR_RE = re.compile(r"^\[.*\]\s*$")


_BARE_HDR_RE = re.compile(r"^[؀-ۿ]{2,8}$")

_QUOTE_MARK_RE = re.compile(r"@Q[BE]@")


_HDR_NOISE_RE = re.compile(r"(?:PageV\d+P\d+|\bms\d+\b|[\[\]])")


def clean_heading(text):
    """Strip the digitisation's own marks from a heading BEFORE matching it.

    render_entry() removes ms#### and PageV##P### from body text; the heading
    detectors did not, so "### | (نهي) ms1086" was not a heading at all and
    Ibn Faris's article on نهي was dropped, while (حول) ms0282 folded into the
    entry for حوك. Stray brackets the digitiser left inside the parentheses
    -- "( [بقر)" -- cost four more, بقر among them."""
    return _HDR_NOISE_RE.sub(" ", text).strip()


def _as_root(text):
    try:
        letters = canonical_root(text)
    except (ValueError, TransliterationError):
        return None
    return "".join(letters) if 2 <= len(letters) <= 5 else None


def heading_root_parenthesised(heading):
    """Maqayis: an entry heading is ALWAYS (سكن). Anything else on a "### |"
    line is a section title or a digitisation artifact -- see trap 13."""
    h = heading.strip()
    m = _ENTRY_HDR_RE.match(h)
    if not m:
        # try again with the digitisation's marks removed
        cleaned = clean_heading(h)
        m = _ENTRY_HDR_RE.match("(%s)" % cleaned.strip("()").strip()) \
            if "(" in h else None
    return _as_root(m.group(1)) if m else None


def heading_root_bare(heading):
    """Mufradat: an entry heading is a bare short Arabic token (أبد، سكن).
    There are no parentheses to lean on, so the guard is the source's own
    alphabetical order -- see ingest_lexicon."""
    h = clean_heading(heading)
    return _as_root(h) if _BARE_HDR_RE.match(h) else None


# The 29 letter-names, as the sources spell them. Needed to read Ibn Jinni's
# per-letter chapters (باب الهمزة / حرف التاء) and, independently, to check
# Ibn Faris against himself -- he opens nearly every article by naming his own
# radicals, «السين والكاف والنون».
LETTER_NAMES = {
    "الهمزة": "ء", "الألف": "ا", "الالف": "ا", "الباء": "ب", "التاء": "ت",
    "الثاء": "ث", "الجيم": "ج", "الحاء": "ح", "الخاء": "خ", "الدال": "د",
    "الذال": "ذ", "الراء": "ر", "الزاي": "ز", "الزاء": "ز", "السين": "س",
    "الشين": "ش", "الصاد": "ص", "الضاد": "ض", "الطاء": "ط", "الظاء": "ظ",
    "العين": "ع", "الغين": "غ", "الفاء": "ف", "القاف": "ق", "الكاف": "ك",
    "اللام": "ل", "الميم": "م", "النون": "ن", "الهاء": "ه", "الواو": "و",
    "الياء": "ي",
}

SIRR_ATTRIBUTION = (
    "Ibn Jinni, Sirr Sina'at al-I'rab. Digital text: OpenITI, CC BY-NC-SA. "
    "https://github.com/OpenITI")

FURUQ_ATTRIBUTION = (
    "Abu Hilal al-'Askari, al-Furuq al-Lughawiyya, ed. Muhammad Ibrahim "
    "Salim (Cairo: Dar al-'Ilm wa-l-Thaqafa). Digital text: OpenITI, "
    "CC BY-NC-SA. https://github.com/OpenITI")

KHASAIS_ATTRIBUTION = (
    "Ibn Jinni, al-Khasa'is. Digital text: OpenITI, CC BY-NC-SA. "
    "https://github.com/OpenITI")

_SIRR_HDR_RE = re.compile(
    r"^(?:CHECK|AUTO)?\s*(?:باب|حرف|زيادة)\s+(\S+)\s*$")


def heading_letter(heading):
    """Sirr Sina'at al-I'rab is organised letter by letter: "باب الهمزة",
    "حرف التاء", and supplementary "زيادة التاء" sections. Returns the LETTER,
    not a root -- this book is about the letters themselves."""
    m = _SIRR_HDR_RE.match(clean_heading(heading).replace("CHECK", "")
                           .replace("AUTO", "").strip())
    if not m:
        return None
    return LETTER_NAMES.get(m.group(1).strip())


_KHASAIS_HDR_RE = re.compile(r"^(?:باب|فصل)\b")


def heading_chapter(heading):
    """al-Khasa'is is organised by TOPIC, not by root -- 273 chapters of
    "باب القول على ...". There is no root to key on, so the chapter title is
    the headword and the link to a root is made by search, never by a key."""
    h = clean_heading(heading)
    return h if _KHASAIS_HDR_RE.match(h) and len(h) > 6 else None


LISAN_ATTRIBUTION = (
    "Ibn Manzur, Lisan al-'Arab. Digital text: OpenITI, CC BY-NC-SA. "
    "https://github.com/OpenITI")

MUTARADIFAAT_ATTRIBUTION = (
    "'Abd al-Rahman Kilani, Mutaradifat al-Qur'an ma'a al-Furuq al-Lughawiyya "
    "(Urdu). Scanned by KitaboSunnat; no text layer. The text stored here is "
    "OCR (Azure AI Document Intelligence, prebuilt-read) and is NOT the "
    "author's words: it is a search key only. Cite the page image.")

_LISAN_BARE = re.compile(r"^# ([؀-ۿ]{2,8})\s*$")
# The colon after the repeated root is NOT always written -- Lisan has both
# "# ] بدأ : في أسماء الله" and "# ] سكن السكون ضد الحركة" -- and a leading
# stop sometimes intervenes ("# ] . صقب :"). Requiring the colon silently
# dropped 827 entries, سكن among them.
_LISAN_CONFIRM = re.compile(
    r"^# \]?\s*(?:[.،:]|\(\s*\d+\s*\)|\d+\s*-\s*\d+)?\s*"
    r"(?:ال)?([؀-ۿ]{2,9})(?:\s|:|$)")


def detect_markdown_header(lines, i, spec):
    """maqayis / mufradat: entries are '### |' headers."""
    m = _HDR_RE.match(lines[i])
    if not m:
        return None
    head = m.group(1)
    if _SECTION_HDR_RE.match(head.strip()):
        return ("__SECTION__", None, 1)
    root = spec["heading"](head)
    return (head.strip(), root, 1) if root else ("__ARTIFACT__", None, 1)


def detect_by_heading(lines, i, spec, rule):
    """A '### |' header run through a source-specific heading rule.

    In these books every chapter IS marked, so a header the rule does not
    recognise is a structural break -- a volume divider, a stray title -- and
    never prose. It therefore CLOSES the chapter in progress.

    Ibn Jinni's Sirr shows why. This witness never marks حرف النون, and the
    volume divider "### | CHECK [جزء 2]" was being folded in as body text, so
    the chapter headed حرف الميم ran to 109,605 bytes and contained the whole
    of volume two -- half of it Ibn Jinni on NUN, served under MIM. Ending the
    chapter leaves nun unassigned, which is a gap the tool can report; the
    alternative was a misattribution it could not see."""
    m = _HDR_RE.match(lines[i])
    if not m:
        return None
    got = rule(m.group(1))
    return (m.group(1).strip(), got, 1) if got else ("__SECTION__", None, 1)


def detect_lisan(lines, i):
    """Lisan has no '###' markers at all, but it names each root TWICE:

        # بدأ
        # ] بدأ : في أسماء الله عز وجل المبدىء ...

    Requiring the two to agree is a stronger guard than Maqayis had -- a
    stray line cannot fake both halves.  A bare head with no confirming line
    is NOT treated as an entry: 8,441 confirm out of 9,268, and inventing
    entries from the other 827 would be guessing."""
    m = _LISAN_BARE.match(lines[i])
    if not m:
        return None
    nxt = lines[i + 1] if i + 1 < len(lines) else ""
    c = _LISAN_CONFIRM.match(nxt)
    head = _as_root(m.group(1))
    if head is None:
        # Too long to be a root -- استبرق, زنجبيل, ميكائيل, منجنون are
        # loanwords Lisan treats as headwords anyway. Keep them as their own
        # entries with no root rather than letting them flow into the entry
        # above, which is how 16 articles ended up under a neighbour.
        if c is not None and c.group(1) == m.group(1):
            return (m.group(1), "__NOROOT__", 1)
        return ("__SECTION__", None, 1)
    if c is not None and _as_root(c.group(1)) == head:
        return (m.group(1), head, 1)
    # A head we cannot confirm is NOT an entry -- but it is still a BOUNDARY.
    # Letting it flow onward put 34,017 bytes under the wrong headword, one
    # entry being 99% Ibn Manzur on سفه while labelled سده.
    return ("__SECTION__", None, 1)


FARQ_PREFIX = "الفرق بين"


def heading_farq(head):
    """al-'Askari heads every article `الفرق بين X و Y`.

    The pair is DATA -- the author put both words in his own title -- so it
    is read off the heading rather than guessed from the article. What is
    NOT claimed is that X and Y are synonyms: that a difference was worth a
    chapter is al-'Askari's judgement, and the tool reports the chapter, not
    the judgement."""
    head = clean_heading(head)
    if not head.startswith(FARQ_PREFIX):
        return None
    rest = head[len(FARQ_PREFIX):].strip(" :،.")
    terms = [t.strip(" :،.") for t in re.split(r"\s+و", rest) if t.strip()]
    return terms if len(terms) >= 2 else None


def detect_farq(lines, i, spec):
    """A heading is `### | الفرق بين ...`. Any other level-1 marker CLOSES
    the article in progress and opens nothing -- the same rule as a
    [باب ...] title in Maqayis, for the same reason (trap 16)."""
    m = _HDR_RE.match(lines[i])
    if not m:
        return None
    return ((m.group(1).strip(), "__NOROOT__", 1)
            if heading_farq(m.group(1)) else ("__SECTION__", None, 1))


# Everything a lexicon needs to be ingested.  Adding one is data, not code.
LEXICONS = {
    "maqayis": {
        "title": "Mu'jam Maqayis al-Lugha",
        "author": "Ibn Faris (d. 395 AH)",
        "edition": "ed. Harun, Dar al-Jil, 1420/1999, 6 vols",
        "licence": "CC BY-NC-SA",
        "licence_note": "OpenITI digital text; non-commercial, share-alike, "
                        "attribution required. Personal study use.",
        "url": "https://github.com/OpenITI",
        "distributable": True,     # CC BY-NC-SA: shareable, non-commercially
        "attribution": MAQAYIS_ATTRIBUTION,
        "heading": heading_root_parenthesised,
        "detect": detect_markdown_header,
        "ordered_by": "first",
        # Maqayis fixes the first TWO radicals within a bab, so two positions
        # are checkable: 29 flags in 4,654.
        "order_depth": 2,
    },
    "mufradat": {
        "title": "al-Mufradat fi Gharib al-Qur'an",
        "author": "al-Raghib al-Isbahani (d. 502 AH)",
        "edition": "OpenITI (Shamela 0023636)",
        "licence": "CC BY-NC-SA",
        "licence_note": "OpenITI digital text; non-commercial, share-alike, "
                        "attribution required. Personal study use.",
        "url": "https://github.com/OpenITI",
        "distributable": True,     # CC BY-NC-SA: shareable, non-commercially
        "attribution": MUFRADAT_ATTRIBUTION,
        "heading": heading_root_bare,
        "detect": detect_markdown_header,
        "ordered_by": "first",
        # al-Raghib heads by WORD, not by root (أبا، أب، أبى، أب، أبد), so
        # only the first letter is monotonic. Checking two positions flags
        # 7% of a sound book, and a badge that cries wolf gets ignored.
        "order_depth": 1,
    },
    "lisan": {
        "title": "Lisan al-'Arab",
        "author": "Ibn Manzur (d. 711 AH)",
        "edition": "OpenITI (JK 000880)",
        "licence": "CC BY-NC-SA",
        "licence_note": "OpenITI digital text; non-commercial, share-alike, "
                        "attribution required. Personal study use.",
        "url": "https://github.com/OpenITI",
        "distributable": True,     # CC BY-NC-SA: shareable, non-commercially
        "attribution": LISAN_ATTRIBUTION,
        "heading": None,
        "detect": lambda lines, i, spec: detect_lisan(lines, i),
        # Lisan and al-Qamus order by the LAST radical (bab), then the first
        # (fasl). Checking it against first-radical order would flag the whole
        # book.
        "ordered_by": "last",
        "order_depth": 2,
    },
    "sirr": {
        "title": "Sirr Sina'at al-I'rab",
        "author": "Ibn Jinni (d. 392 AH)",
        "edition": "OpenITI (ShamAY 0034702)",
        "licence": "CC BY-NC-SA",
        "licence_note": "OpenITI digital text; non-commercial, share-alike, "
                        "attribution required. Personal study use.",
        "url": "https://github.com/OpenITI",
        "distributable": True,
        "attribution": SIRR_ATTRIBUTION,
        "heading": heading_letter,
        "detect": lambda lines, i, spec: detect_by_heading(
            lines, i, spec, heading_letter),
        "keyed_by": "letter",       # NOT by root: this book is about letters
        "ordered_by": "first",
        "order_depth": 0,           # the letter order is the book's own
    },
    "furuq": {
        "title": "al-Furuq al-Lughawiyya",
        "author": "Abu Hilal al-'Askari (d. c. 395 AH)",
        "edition": "ed. Muhammad Ibrahim Salim, Dar al-'Ilm wa-l-Thaqafa, "
                   "Cairo (OpenITI, Shamela 0010414)",
        "licence": "CC BY-NC-SA",
        "licence_note": "OpenITI digital text; non-commercial, share-alike, "
                        "attribution required. Personal study use.",
        "url": "https://github.com/OpenITI",
        "distributable": True,
        "attribution": FURUQ_ATTRIBUTION,
        "heading": None,
        "detect": detect_farq,
        # Keyed by a PAIR OF WORDS, not by a root: there is no root to look
        # up, so it is searched like al-Khasa'is and gets no root card.
        "keyed_by": "pair",
        "ordered_by": "first",
        "order_depth": 0,
    },
    "khasais": {
        "title": "al-Khasa'is",
        "author": "Ibn Jinni (d. 392 AH)",
        "edition": "OpenITI (Shamela 0009986)",
        "licence": "CC BY-NC-SA",
        "licence_note": "OpenITI digital text; non-commercial, share-alike, "
                        "attribution required. Personal study use.",
        "url": "https://github.com/OpenITI",
        "distributable": True,
        "attribution": KHASAIS_ATTRIBUTION,
        "heading": heading_chapter,
        "detect": lambda lines, i, spec: detect_by_heading(
            lines, i, spec, heading_chapter),
        "keyed_by": "chapter",      # topic-organised; no root to key on
        "ordered_by": "first",
        "order_depth": 0,
    },
    # Kilani is a SCAN-ONLY source and the only one here whose stored text is
    # not the book's.  It has no `detect`/`heading` because it is not parsed
    # by parse_lexicon at all -- see ingest_mutaradifaat, which reads OCR
    # JSON.  Three things follow from that and are enforced, not remarked:
    #
    #   text_raw IS NULL          there is nothing verbatim to show.  The OCR
    #                             goes in text_norm, which this program has
    #                             always treated as a search key that is never
    #                             displayed.  The schema's CHECK (text_raw IS
    #                             NOT NULL OR scan_uri IS NOT NULL) then makes
    #                             the citation compulsory.
    #   keyed_by 'urdu'           the book is arranged by URDU headword, and
    #                             the OCR lost precisely that key: Azure ran an
    #                             Arabic model over Nasta'liq, so only 82 of
    #                             6,585 words came back holding an Urdu-only
    #                             letter.  So it cannot be ASKED about a root,
    #                             gets no root card, and is searched -- exactly
    #                             like al-Khasa'is, for the same reason.
    #   a root link needs TWO     the OCR corrupts headwords (دَابِر came back
    #   agreeing facts            دَايِر), so a headword alone may not name a
    #                             root.  See mutaradifaat_link().
    "mutaradifaat": {
        "title": "Mutaradifat al-Qur'an ma'a al-Furuq al-Lughawiyya",
        "author": "'Abd al-Rahman Kilani",
        "edition": "KitaboSunnat scan, 1026 pp.; OCR of scan pp. 395-414 "
                   "(Azure prebuilt-read, api-version 2024-11-30)",
        "licence": "in copyright",
        "licence_note": "Not redistributable. No text of this book is stored "
                        "or served: only an OCR search key and a page number.",
        "url": "",
        "distributable": False,
        "attribution": MUTARADIFAAT_ATTRIBUTION,
        "heading": None,
        "detect": None,
        "keyed_by": "urdu",
        "ordered_by": "first",
        "order_depth": 0,
        "scan_only": True,
    },
}


def _heading_root(heading):
    """Backwards-compatible: the Maqayis rule."""
    return heading_root_parenthesised(heading)


def resolve_root(heading_root, corpus_roots):
    """Map a lexicon heading onto a corpus root, saying HOW.

    Two spelling conventions differ between Maqayis and the corpus, and both
    were found by measuring coverage rather than by assumption:

      geminate    Maqayis heads a mudaaf root with two letters -- أب for the
                  corpus's ءبب.  151 roots.
      weak_final  Maqayis heads a weak-lam root with ى/ي where the corpus
                  writes و -- (دنى) for دنو, (صلى) for صلو.

    Both are inferences, so both are recorded and neither is hidden from the
    reviewer."""
    if heading_root is None:
        return None, "unparsed"
    if heading_root in corpus_roots:
        return heading_root, "direct"
    if len(heading_root) == 2:
        doubled = heading_root + heading_root[1]
        if doubled in corpus_roots:
            return doubled, "geminate"
    if heading_root and heading_root[-1] in ("ي", "و"):
        other = heading_root[:-1] + ("و" if heading_root[-1] == "ي" else "ي")
        if other in corpus_roots:
            return other, "weak_final"
    return heading_root, "unmatched"


def parse_lexicon(text, corpus_roots, spec):
    """Yield one dict per entry.  text_raw is the block verbatim.

    Two guards, and they do different jobs:

      the heading rule   decides what IS an entry.  Maqayis needs
                         parentheses because its digitisation inserts headers
                         mid-word; Mufradat has no parentheses to lean on.
      alphabetical order checks the source against ITSELF.  A heading that
                         goes backwards through the alphabet is not a new
                         letter-section, so it is a sub-entry, a title, or an
                         artifact.  It is flagged, not dropped -- dropping it
                         would lose text, and the reviewer can see it."""
    detect = spec["detect"]
    order_ix = -1 if spec.get("ordered_by") == "last" else 0
    depth = spec.get("order_depth", 1)
    lines = text.splitlines()

    # A PageV##P### marker CLOSES the page it names -- every one of these
    # files ends with its final words followed inline by the last marker, and
    # the Shamela ones open with a PageV00P000 sentinel. So an entry sits on
    # the page named by the NEXT marker at or after it, not the previous one.
    # Taking the previous marker put every single citation one page too low,
    # and at a volume boundary put it in the wrong volume as well.
    page_at = [None] * len(lines)
    nxt = (None, None)
    for j in range(len(lines) - 1, -1, -1):
        m = _PAGE_RE.search(lines[j])
        if m:
            nxt = (int(m.group(1)), int(m.group(2)))
        page_at[j] = nxt

    cur = None
    prev_key = None
    unassigned = [0]
    i = 0
    while i < len(lines):
        line = lines[i]
        page = page_at[i]
        hit = detect(lines, i, spec)
        if hit is not None:
            head, hr, consumed = hit
            if head == "__SECTION__":
                if cur:
                    yield cur
                cur = None
                # A new [باب ...] restarts the alphabet. Carrying the previous
                # section's key across the boundary flagged 11% of Maqayis --
                # every section start looked like a regression.
                prev_key = None
                i += consumed
                continue
            if hr is None:
                # not a heading: text belonging to the entry in progress
                if cur is not None:
                    cur["lines"].append(line)
                i += consumed
                continue
            if cur:
                yield cur
            if not root_keyed(spec.get("key", "")):
                # Not root-keyed. Ibn Jinni's Sirr is about the LETTERS,
                # al-Khasa'is about topics, al-'Askari's Furuq about PAIRS of
                # words; inventing a root for any of them would be filing
                # text under something the book never said.
                root, how = None, spec["keyed_by"]
            elif hr == "__NOROOT__":
                root, how = None, "unparsed"
            else:
                root, how = resolve_root(hr, corpus_roots)
            flags = []
            # The whole key, rotated so the source's primary radical leads.
            # Comparing one letter meant every heading inside كتاب الألف
            # scored identically and the check was near-vacuous.
            ak = alpha_key(hr if hr not in ("__NOROOT__",)
                           and depth else "")
            key = ((ak[order_ix],) + tuple(
                x for j, x in enumerate(ak)
                if j != (order_ix % len(ak))))[:depth] if ak else prev_key
            # Compared with the PREVIOUS heading, not a running maximum. One
            # stray heading (Mufradat has وإي sitting inside the hamza
            # section) would poison a max for the rest of the file and flag
            # 1,524 sound entries -- a warning that cries wolf is worse than
            # no warning, because the reviewer learns to ignore the badge.
            if prev_key is not None and key < prev_key:
                flags.append("out-of-alphabetical-order")
            prev_key = key
            cur = {"headword": head, "root_ar": root,
                   "extraction": how, "vol": page[0], "page": page[1],
                   "flags": ",".join(flags) or None, "lines": []}
            i += consumed
            continue
        if cur is not None:
            cur["lines"].append(line)
        else:
            unassigned[0] += len(line)
        i += 1
    if cur:
        yield cur
    # A gap the reader cannot see is a gap they will mistake for absence.
    if spec.get("_unassigned") is not None:
        spec["_unassigned"][0] = unassigned[0]
    del prev_key


def parse_maqayis(text, corpus_roots):
    """Backwards-compatible wrapper; the tests use it."""
    return parse_lexicon(text, corpus_roots, LEXICONS["maqayis"])


def render_entry(raw):
    """Strip OpenITI structural markup for DISPLAY.  This is the digitisation's
    annotation, not the author's words, and the rule is written here so it can
    be read: page markers and milestone ids are dropped, '# ' begins a
    paragraph, '~~' continues the previous one, '%' separates hemistichs."""
    out = []
    glue = ""
    for line in raw.splitlines():
        line = _PAGE_RE.sub("", line)
        line = _MS_RE.sub("", line)
        # JK's Lisan brackets every Qur'anic quotation with @QB@ ... @QE@
        # (6,136 of them). They are the digitisation's annotation, so they
        # come off here with the rest of the markup. They are NOT replaced
        # with quotation marks: the punctuation would be ours, not the
        # book's, and the stored text keeps them either way.
        line = _QUOTE_MARK_RE.sub("", line)
        h = _HDR_RE.match(line)
        if h:
            # an artifact header: its content is the first half of a word (or
            # phrase) whose second half is on the next line.  Carry it, with
            # the source's own trailing space, and glue it on.
            glue = h.group(1)
            continue
        if line.startswith("~~"):
            cont, line = True, line[2:]
        elif line.startswith("# "):
            cont, line = False, line[2:]
        elif line.startswith("#"):
            cont, line = False, line[1:]
        else:
            cont = bool(out)
        glued = False
        if glue:
            line = glue + line.lstrip("# ").lstrip("~")
            glue = ""
            cont = True
            glued = True
        line = line.strip()
        if not line:
            continue
        if cont and out:
            # No space when the line was glued back together across an
            # artifact header: the word was cut mid-way, and inserting a
            # space broke 277 words (واحد -> "و احد").
            sep = "" if glued else " "
            out[-1] = (out[-1] + sep + line).strip()
        else:
            out.append(line)
    # Lisan opens each entry body with a bracket that marks the entry, not a
    # word Ibn Manzur wrote: "# ] سكن السكون ضد الحركة". Structural markup,
    # so it comes off at display time like the rest.
    if out and out[0].startswith("]"):
        out[0] = out[0][1:].lstrip()
    return [l.replace("%", "\n").strip() for l in out]


def ingest_lexicon(conn, key, path):
    """Load a lexicon.  Every row lands verified = 0, without exception."""
    if key not in LEXICONS:
        raise ValueError("unknown lexicon %r; known: %s"
                         % (key, ", ".join(sorted(LEXICONS))))
    spec = LEXICONS[key]
    with open(path, "rb") as fh:
        text = fh.read().decode("utf-8")
    with unguarded(conn):
        cur = conn.cursor()
        # A source's IDENTITY may not change while entries point at it.
        # Re-using a key for a different book -- or even a different witness
        # of the same book -- would relabel already-approved text with another
        # scholar's name and another edition's page numbers, which is exactly
        # the fabricated attribution this program exists to prevent.
        prior = cur.execute(
            "SELECT id, title, author, edition FROM sources WHERE key=?",
            (key,)).fetchone()
        if prior is not None:
            decided = cur.execute(
                "SELECT COUNT(*) FROM entries WHERE source_id=? AND "
                "(verified=1 OR rejected=1)", (prior["id"],)).fetchone()[0]
            changed = [f for f in ("title", "author", "edition")
                       if (prior[f] or "") != (spec[f] or "")]
            if changed and decided:
                raise SystemExit(
                    "REFUSED. Source %r already holds %d reviewed entries, and "
                    "this ingest would change its %s.\n"
                    "Those entries' volume and page numbers belong to the OLD "
                    "%s; relabelling them would attribute text to a book that "
                    "does not contain it on that page.\n"
                    "Use a NEW key for a different book or witness."
                    % (key, decided, " and ".join(changed),
                       prior["edition"] or "edition"))
        # ON CONFLICT, not INSERT OR REPLACE: replace would delete the row and
        # re-insert it with a NEW id, orphaning every entry that points at it
        # -- including ones a person has already approved.
        cur.execute(
            "INSERT INTO sources (key,title,author,edition,kind,"
            "licence,licence_note,distributable,url,attribution) "
            "VALUES (?,?,?,?,'lexicon',?,?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET title=excluded.title,"
            "author=excluded.author,edition=excluded.edition,"
            "licence=excluded.licence,licence_note=excluded.licence_note,"
            "distributable=excluded.distributable,url=excluded.url,"
            "attribution=excluded.attribution",
            (key, spec["title"], spec["author"], spec["edition"],
             spec["licence"], spec["licence_note"],
             # NOT hardcoded: an in-copyright source added to the registry
             # must not be marked distributable by default.
             1 if spec.get("distributable") else 0,
             spec["url"], spec["attribution"]))
        sid = cur.execute(
            "SELECT id FROM sources WHERE key=?", (key,)).fetchone()[0]
        # Re-ingesting must not silently discard review work.
        kept = cur.execute(
            "SELECT COUNT(*) FROM entries WHERE source_id=? AND "
            "(verified=1 OR rejected=1)", (sid,)).fetchone()[0]
        cur.execute("DELETE FROM entries WHERE source_id=? AND verified=0 "
                    "AND rejected=0", (sid,))
        corpus = {r[0] for r in cur.execute("SELECT root_ar FROM roots")}
        spec = dict(spec, key=key, _unassigned=[0])
        # Keyed on the whole entry, not the headword. Headwords repeat --
        # al-Raghib has two separate articles headed أب -- so skipping by
        # headword deleted the undecided sibling of every decided row and
        # said nothing. 74 entries across the three lexicons sit on a
        # duplicated headword.
        # NOT keyed on vol/page: those are exactly what a corrected extraction
        # changes. When every citation moved by one page, keying on them made
        # each reviewed row look like a different entry, so the old row kept
        # its wrong page and a corrected duplicate was inserted beside it.
        def _fingerprint(headword, vol, page, raw):
            h = hashlib.sha256()
            for part in (headword or "", raw):
                h.update(part.encode("utf-8"))
                h.update(b"\x00")
            return h.hexdigest()

        seen = {}
        if kept:
            seen = {_fingerprint(r["headword"], r["vol"], r["page"],
                                 r["text_raw"] or ""): r["id"]
                    for r in cur.execute(
                        "SELECT id, headword, vol, page, text_raw FROM entries "
                        "WHERE source_id=?", (sid,))}
        n = 0
        recited = 0
        stats = {}
        for e in parse_lexicon(text, corpus, spec):
            raw = "\n".join(e["lines"]).strip()
            if not raw:
                continue
            fp = _fingerprint(e["headword"], e["vol"], e["page"], raw)
            if fp in seen:
                # The DECISION stands; the citation may have been corrected.
                cur.execute("UPDATE entries SET vol=?, page=?, extraction=?, "
                            "flags=? WHERE id=? AND (vol IS NOT ? OR "
                            "page IS NOT ?)",
                            (e["vol"], e["page"], e["extraction"], e["flags"],
                             seen[fp], e["vol"], e["page"]))
                recited += cur.rowcount
                continue
            cur.execute(
                "INSERT INTO entries (source_id,root_ar,headword,text_raw,"
                "text_norm,vol,page,extraction,flags,verified) "
                "VALUES (?,?,?,?,?,?,?,?,?,0)",
                (sid, e["root_ar"], e["headword"], raw,
                 norm_alif(raw), e["vol"], e["page"], e["extraction"],
                 e["flags"]))
            stats[e["extraction"]] = stats.get(e["extraction"], 0) + 1
            n += 1
        conn.commit()
    return n, stats, kept, recited, spec["_unassigned"][0]


def ingest_maqayis(conn, path):
    return ingest_lexicon(conn, "maqayis", path)[:2]


# --------------------------------------------------------------------------
# 8b-bis.  MUTARADIFAAT  --  a scan-only source, and the one whose stored
#          text is not the author's
# --------------------------------------------------------------------------
#
# Every other source in this program stores its book verbatim.  This one
# cannot: the scan has no text layer, and what OCR returns is not Kilani's
# words.  Measured on these 20 pages, mean engine confidence is 0.483, and
# the Urdu in particular comes back wrong -- پاکیزہ reads باكيزه, کلمہ reads
# كلمن.  Rendering any of it as his prose would be a fabricated attribution
# arriving by a new door: not invented by a model, but corrupted by a scanner
# and then dressed in a scholar's name.
#
# So NOTHING from this source is ever displayed.  The OCR is stored in
# text_norm -- which this program has always defined as a search key that is
# never shown -- and text_raw is NULL, which the schema already understands
# as "scan-only: the page image is the citation".  The reader is given a page
# number and the app's OWN mushaf text for the ayat the page quotes.
#
# WHY A ROOT LINK NEEDS TWO AGREEING FACTS.  The OCR corrupts headwords too
# (دَابِر comes back دَايِر, a ba' read as ya'), so "the headword contains these
# radicals" is not by itself enough to file a page under a root -- that is
# how a scanner's error becomes a claim about a book.  This is the same
# problem the tafsir anchoring has, and it takes the same shape of answer:
#
#   FACT 1, the proposal      the OCR'd headword contains the root's radicals
#                             in order, by root_search_re -- the same written
#                             -down rule the `mentions` search uses, with the
#                             same stated costs.
#   FACT 2, the confirmation  the ayat the page quotes, recovered independently
#                             by folding the OCR through mushaf_key() and
#                             matching trigrams against the corpus, intersect
#                             the ayat where that root actually occurs.
#
# Fact 2 alone is useless and it is worth saying why, because it looks
# plausible: every ayah contains الله or قال, so intersecting recovered ayat
# against ALL roots just ranks the commonest function roots first.  It can
# CONFIRM a hypothesis; it cannot GENERATE one.
#
# Measured on scan pp. 395-414: 65 entries parsed, 6 confirmed by both facts.
# The other 59 are not served as entries -- 35 recover no ayah at all and 17
# have a headword too corrupt to propose anything.  A 6/65 yield is a true
# report of what this OCR can support, and inflating it by dropping fact 2
# would be trading a measured gap for an unmeasured claim.

# The printed folio is the scan page minus this.  Confirmed on 13 of the 20
# OCR'd pages and independently at scan 45 (prints 28) and scan 72 (prints
# 55), so it holds across roughly 370 pages of span.  It is used for ORDERING
# and NAVIGATION only: where a page's own header was misread, the entry keeps
# `header unread` and the display says the number was derived, not read.
# "Read off the page" and "derived from the modal offset" are different
# warrants and this program does not collapse them.
MUTARADIFAAT_PAGE_OFFSET = 17

# numeral + dash + vowelled Arabic headword + colon.  The DIGIT IS NOISE and
# is thrown away: the OCR gives ٣- for an entry the book prints ٢-, and two
# consecutive ٣- appear on scan 395 and again on 396.  It is never used for
# ordering and never becomes an id.
_MUT_HEAD = re.compile(r"^\s*[٠-٩۰-۹\d]{1,2}\s*[-–]\s*"
                       r"([ؠ-يً-ْٰ]{2,12})\s*[:؛]")


def mutaradifaat_entries(pages):
    """Split OCR pages into entries.  [(scan, printed_or_None, head, lines)]"""
    out = []
    for scan, printed, lines in pages:
        cur = None
        for ln in lines:
            m = _MUT_HEAD.match(ln)
            if m:
                if cur:
                    out.append(cur)
                cur = [scan, printed, m.group(1), [ln]]
            elif cur:
                cur[3].append(ln)
        if cur:
            out.append(cur)
    return out


def _mushaf_trigrams(conn):
    """(trigram -> {(sura, aya)}) folded by mushaf_key, as the tafsir does."""
    ayat = collections.OrderedDict()
    for s, a, f in q(conn, "SELECT sura, aya, form_ar FROM words "
                           "ORDER BY sura, aya, word"):
        ayat.setdefault((s, a), []).append(f)
    tri = {}
    for (s, a), forms in ayat.items():
        k = mushaf_key(" ".join(forms)).split()
        for i in range(len(k) - 2):
            tri.setdefault(" ".join(k[i:i + 3]), set()).add((s, a))
    return tri


def mutaradifaat_ayat(tri, lines):
    """The ayat an OCR'd page quotes.  Two trigrams, as score_ocr.py uses.

    One trigram is not enough: the fold is deliberately loose (it deletes all
    three long vowels) and a single 3-word run coincides across the mushaf."""
    k = mushaf_key(" ".join(lines)).split()
    per = collections.Counter()
    for i in range(len(k) - 2):
        for sa in tri.get(" ".join(k[i:i + 3]), ()):
            per[sa] += 1
    return {sa for sa, n in per.items() if n >= 2}


def mutaradifaat_link(head, ayat, root_ayat, res):
    """The two agreeing facts.  Returns the root, or None to refuse.

    Ambiguity refuses too: if two roots are both proposed AND both confirmed,
    nothing here can choose between them, and picking one would be a guess
    wearing the costume of a rule."""
    h = norm_alif(head) or head
    conf = [r for r in root_ayat if res[r].search(h) and (ayat & root_ayat[r])]
    return conf[0] if len(conf) == 1 else None


def _mut_pages(doc):
    """[(scan, printed_or_None, lines)] from either shape of the OCR file.

    THE WARRANT MUST TRAVEL WITH THE VALUE. The first version of this file
    stored the raw OCR reading of the page header in a field called
    `printed`, with nothing marking the six of twenty that are WRONG -- so a
    consumer that trusted it cited Kilani's entry on قِتَال to printed p. 392,
    a real page of this book that does not contain it. A misread header is
    worse than a missing one for exactly that reason.

    The current shape carries `page_method` ('header' | 'offset') beside an
    always-populated `printed_page`, so the warrant cannot be separated from
    the number. Where only the old shape is present the number is verified
    against the offset here instead, and disagreement is treated as absence.
    """
    if isinstance(doc, dict):
        out = []
        for p in doc["pages"]:
            out.append((p["scan_page"],
                        p["printed_page"] if p["page_method"] == "header"
                        else None,
                        p["lines"]))
        return out
    # legacy: a bare array whose `printed` is the raw, untrustworthy reading
    return [(scan, printed, lines) for scan, printed, lines in doc]


def ingest_mutaradifaat(conn, path):
    """Load Kilani from OCR JSON.  Stores NO text of the book.

    `path` is either ocr/pages.json or the directory holding it.  Every row
    lands verified = 0, text_raw NULL, and the OCR in text_norm."""
    key = "mutaradifaat"
    spec = LEXICONS[key]
    if os.path.isdir(path):
        path = os.path.join(path, "pages.json")
    with open(path, "rb") as fh:
        doc = json.loads(fh.read().decode("utf-8"))
    # The file grew a header when its author found the trap below; the old
    # shape was a bare array. Both are read, and the version that carries the
    # warrant is preferred -- see _mut_pages.
    pages = _mut_pages(doc)

    with unguarded(conn):
        cur = conn.cursor()
        prior = cur.execute("SELECT id, edition FROM sources WHERE key=?",
                            (key,)).fetchone()
        if prior is not None:
            decided = cur.execute(
                "SELECT COUNT(*) FROM entries WHERE source_id=? AND "
                "(verified=1 OR rejected=1)", (prior["id"],)).fetchone()[0]
            if decided and (prior["edition"] or "") != spec["edition"]:
                raise SystemExit(
                    "REFUSED. Source %r already holds %d reviewed entries and "
                    "this ingest would change its edition. Those entries' page "
                    "numbers belong to the OLD scan. Use a NEW key."
                    % (key, decided))
        cur.execute(
            "INSERT INTO sources (key,title,author,edition,kind,"
            "licence,licence_note,distributable,url,attribution) "
            "VALUES (?,?,?,?,'lexicon',?,?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET title=excluded.title,"
            "author=excluded.author,edition=excluded.edition,"
            "licence=excluded.licence,licence_note=excluded.licence_note,"
            "distributable=excluded.distributable,url=excluded.url,"
            "attribution=excluded.attribution",
            (key, spec["title"], spec["author"], spec["edition"],
             spec["licence"], spec["licence_note"],
             1 if spec.get("distributable") else 0,
             spec["url"], spec["attribution"]))
        sid = cur.execute("SELECT id FROM sources WHERE key=?",
                          (key,)).fetchone()[0]
        kept = cur.execute(
            "SELECT COUNT(*) FROM entries WHERE source_id=? AND "
            "(verified=1 OR rejected=1)", (sid,)).fetchone()[0]
        cur.execute("DELETE FROM entries WHERE source_id=? AND verified=0 "
                    "AND rejected=0", (sid,))

        tri = _mushaf_trigrams(conn)
        root_ayat = collections.defaultdict(set)
        for r, s, a in cur.execute(
                "SELECT root_ar, sura, aya FROM segments "
                "WHERE root_ar IS NOT NULL"):
            root_ayat[r].add((s, a))
        res = {r: root_search_re(r) for r in root_ayat}

        n = linked = 0
        for scan, printed, head, lines in mutaradifaat_entries(pages):
            ayat = mutaradifaat_ayat(tri, lines)
            root = mutaradifaat_link(head, ayat, root_ayat, res)
            # A page header the OCR misread is WORSE than one it could not
            # read: scan 396's header came back 349 and scan 411's came back
            # 392 for a page printed 394.  Storing that number would cite a
            # real page of this book that does not contain this entry -- the
            # citation being the whole product.  So the printed number is
            # trusted only where it AGREES with the offset; 6 of these 20
            # pages disagree, and they are derived and said to be derived.
            derived = scan - MUTARADIFAAT_PAGE_OFFSET
            if printed == derived:
                page_method = "header"
            else:
                page_method = "offset+%d%s" % (
                    MUTARADIFAAT_PAGE_OFFSET,
                    "" if printed is None else
                    " (header misread as %s)" % printed)
                printed = None
            # `flags` stays for genuine anomalies only -- see page_method.
            flags = []
            cur.execute(
                "INSERT INTO entries (source_id, headword, root_ar, text_raw, "
                "text_norm, vol, page, scan_uri, extraction, flags, "
                "link_evidence, page_method, verified) "
                "VALUES (?,?,?,NULL,?,NULL,?,?,?,?,?,?,0)",
                (sid, head, root,
                 # the OCR: a SEARCH KEY, never displayed
                 norm_alif(" ".join(lines)) or "",
                 str(printed if printed else derived),
                 "scan p. %d" % scan,
                 "ocr-confirmed" if root else "ocr-unconfirmed",
                 ",".join(flags) or None,
                 " ".join("%d:%d" % sa for sa in sorted(ayat)) or None,
                 page_method))
            n += 1
            linked += bool(root)
        conn.commit()
    return n, linked, kept


# ==========================================================================
# 8c.  ISHTIQAQ AKBAR  --  Ibn Jinni's greater derivation
# ==========================================================================
#
# Ibn Jinni's claim (al-Khasa'is) is that the six permutations of a triliteral
# root often orbit one idea -- his demonstration is on ق و ل: قول، وقل، لوق،
# قلو، ولق، لقو, all turning on lightness and speed.
#
# TWO DIFFERENT THINGS, and the tool must not blur them:
#
#   LISTING the six permutations is arithmetic, and saying which of them the
#   Qur'an uses is a database lookup. Both are derivation and both are safe.
#
#   Claiming they SHARE A SENSE is Ibn Jinni's thesis about Arabic. It is not
#   derivable from the letters, this tool cannot compute it, and it must be
#   quoted from al-Khasa'is with a page or not asserted at all.
#
# It is also a minority method. Many philologists rejected it as speculative,
# so it is supporting insight AFTER Ibn Faris and al-Raghib have established a
# meaning -- never primary evidence -- and the output says so.

REFUSAL_AKBAR_SENSE = (
    "REFUSED. Whether these six permutations share a single idea is Ibn "
    "Jinni's THESIS, argued in al-Khasa'is. It is not derivable from the "
    "letters and this tool will not assert it. Quote him, with a page, or "
    "leave it unsaid. Note also that al-ishtiqaq al-akbar is a minority "
    "method: use it as supporting insight after Ibn Faris and al-Raghib have "
    "established the meaning, never as primary evidence."
)

REFUSAL_AKBAR_NOT_THULATHI = (
    "REFUSED. al-ishtiqaq al-akbar is stated for the THULATHI root -- six "
    "permutations of three radicals. This root has %d, and nothing in Ibn "
    "Jinni licenses extending the method to it."
)


class Permutation(object):
    """One of the six orderings, and what the corpus says about it."""

    def __init__(self, root, is_original, n_segments, n_lemmas, example):
        self.root = root
        self.is_original = is_original
        self.n_segments = n_segments
        self.n_lemmas = n_lemmas
        self.example = example

    @property
    def occurs(self):
        return self.n_segments > 0


def permutations_of(root):
    """The distinct orderings of a triliteral's radicals, in a fixed order so
    the output is reproducible.  A root with a repeated radical has fewer than
    six -- that is arithmetic, not an omission."""
    letters = canonical_root(root)
    if len(letters) != 3:
        raise ValueError(REFUSAL_AKBAR_NOT_THULATHI % len(letters))
    seen = []
    for a in range(3):
        for b in range(3):
            for c in range(3):
                if len({a, b, c}) != 3:
                    continue
                cand = letters[a] + letters[b] + letters[c]
                if cand not in seen:
                    seen.append(cand)
    return sorted(seen, key=alpha_key)


def ishtiqaq_akbar(conn, root):
    """Pure retrieval over a computed list.  No claim is made about meaning."""
    original = "".join(canonical_root(root))
    out = []
    for perm in permutations_of(root):
        row = q(conn, "SELECT n_segments, n_lemmas FROM roots WHERE root_ar=?",
                (perm,)).fetchone()
        example = None
        if row:
            ex = q(conn, "SELECT form_ar, sura, aya, word, seg, features "
                         "FROM segments WHERE root_ar=? AND is_stem=1 "
                         "ORDER BY sura, aya, word, seg LIMIT 1",
                   (perm,)).fetchone()
            example = ex
        out.append(Permutation(perm, perm == original,
                               row["n_segments"] if row else 0,
                               row["n_lemmas"] if row else 0, example))
    return out


# ==========================================================================
# 8c2.  I'LAL AND IDGHAM  --  refusal R2, discharged where the Qur'an proves it
# ==========================================================================
#
# Naive templating on ق و ل gives the non-word قَوَلَ. The rules that turn it
# into قَالَ are below. They are written here, in this file, so they can be
# read -- and every one of them is checked against the Qur'an itself:
# `lughat.py ilal --check` regenerates the citation forms of every weak root
# the mushaf attests and compares them EXACTLY. A rule that does not reproduce
# the Qur'an is wrong, and its forms stay UNVERIFIED.
#
# This does not discharge refusal R2 wholesale. It discharges it for the verb
# citation forms of the classes below, at the measured pass rate, and for
# nothing else.

WAW, YAA = "و", "ي"


def _vowel_letter(haraka):
    """The long vowel a haraka lengthens to."""
    return {DAMMA: WAW, KASRA: YAA, FATHA: ALIF}[haraka]


def _mudari_ayn_vowel(bab):
    return {1: DAMMA, 2: KASRA, 3: FATHA, 4: FATHA, 5: DAMMA, 6: KASRA}[bab]


def _madi_ayn_vowel(bab):
    return {1: FATHA, 2: FATHA, 3: FATHA, 4: KASRA, 5: DAMMA, 6: KASRA}[bab]


def _seated(forms):
    return {k: (seat_hamza_medial(seat_hamza(v)) if v else v)
            for k, v in forms.items()}


# Measured by `lughat.py ilal --check` against every weak root the Qur'an
# attests in BOTH aspects, where one bab must reproduce both. These classes
# reproduce the mushaf exactly, so their forms are marked verified; mithal
# does NOT and keeps its caveat, because the waaw's fate before a fatha is not
# determined by the bab (وَضَعَ يَضَعُ drops it, وَجِلَ يَوْجَلُ keeps it).
ILAL_VALIDATED = {"ajwaf": "13/13", "naqis": "17/17", "mudaaf": "8/8"}
ILAL_NOT_VALIDATED = {"mithal": "2/4"}


def seat_hamza(text):
    """A hamza radical is canonically ء, but Arabic WRITES it on a seat chosen
    by the surrounding vowels: أَتَى not ءَتَى, إِنْ not ءِنْ. Only the cases
    the citation forms need are handled -- word-initial, where the seat is
    decided by the hamza's own haraka."""
    if not text or text[0] != HAMZA:
        return text
    nxt = text[1] if len(text) > 1 else ""
    seat = {FATHA: "أ", DAMMA: "أ", KASRA: "إ"}.get(nxt)
    return (seat + text[1:]) if seat else text


def seat_hamza_medial(text):
    """A sukun-bearing hamza after a fatha sits on an alif: يَأْتِي, not
    يَءْتِي."""
    out = []
    for i, ch in enumerate(text):
        if ch == HAMZA and i and out and out[-1] == FATHA and \
                i + 1 < len(text) and text[i + 1] == SUKUN:
            out.append("أ")
        else:
            out.append(ch)
    return "".join(out)


def ilal_verb_forms(letters, rc, bab):
    """The madi 3MS, mudari' 3MS and amr 2MS of a weak or doubled root.

    Returns {slot: text} for the classes handled, or {} when the root's class
    has no rules here -- in which case the caller keeps the raw template and
    its UNVERIFIED banner."""
    if bab not in ABWAB or len(letters) != 3:
        return {}
    # A root that is BOTH mahmuz and weak needs hamza ibdal rules that are not
    # implemented beyond seating, so it is not claimed here.
    if "mahmuz" in rc.kinds and rc.needs_ilal and \
            any(x in rc.kinds for x in ("ajwaf", "naqis", "mithal")) and \
            letters[0] != HAMZA:
        return {}
    F, V, L_ = letters
    mv, dv = _madi_ayn_vowel(bab), _mudari_ayn_vowel(bab)
    kinds = rc.kinds

    # ---- ajwaf: the medial semivowel is absorbed --------------------------
    # قَوَلَ -> قَالَ. In the madi the 'ayn becomes a long a; in the mudari'
    # its vowel moves to the faa' and it becomes the matching long vowel;
    # the amr is the jussive, which drops that long vowel entirely.
    if "ajwaf" in kinds and "mudaaf" not in kinds:
        madi = F + FATHA + ALIF + L_ + FATHA
        mud = "ي" + FATHA + F + dv + _vowel_letter(dv) + L_ + DAMMA
        amr = F + dv + L_ + SUKUN
        return _seated({"madi": madi, "mudari": mud, "amr": amr})

    # ---- naqis: the final semivowel ---------------------------------------
    # رَمَىَ -> رَمَى, دَعَوَ -> دَعَا. After a fatha the final weak letter
    # becomes alif -- written maksura when the radical is yaa -- but after a
    # kasra (bab 4) it survives as yaa: رَضِيَ.
    if "naqis" in kinds and "mudaaf" not in kinds:
        if mv == FATHA:
            tail = ALIF_MAKSURA if L_ == YAA else ALIF
            madi = F + FATHA + V + FATHA + tail
        else:
            # after a kasra a final waaw becomes yaa: رَضِوَ is not a word,
            # رَضِيَ is -- and the corpus root is رضو.
            tail_l = YAA if L_ == WAW else L_
            madi = F + FATHA + V + mv + tail_l + FATHA
        mud = "ي" + FATHA + F + SUKUN + V + dv + (
            ALIF_MAKSURA if dv == FATHA else _vowel_letter(dv))
        amr = F + SUKUN + V + dv if False else None
        return _seated({"madi": madi, "mudari": mud})

    # ---- mithal: a waaw faa' drops before a kasra -------------------------
    # وَعَدَ يَوْعِدُ -> يَعِدُ, and the amr loses it too: عِدْ. Before a
    # fatha it survives (وَجِلَ يَوْجَلُ), and a yaa faa' always survives.
    if "mithal" in kinds and "mudaaf" not in kinds:
        madi = F + FATHA + V + mv + L_ + FATHA
        if F == WAW and dv == KASRA:
            mud = "ي" + FATHA + V + dv + L_ + DAMMA
            amr = V + dv + L_ + SUKUN
        elif F == WAW and dv == FATHA:
            # NOT determined by the bab. وَضَعَ يَضَعُ drops the waaw and
            # وَجِلَ يَوْجَلُ keeps it, both with a fatha, and nothing in the
            # letters says which. Refusing beats guessing.
            return _seated({"madi": madi, "mudari": None, "amr": None})
        else:
            mud = "ي" + FATHA + F + SUKUN + V + dv + L_ + DAMMA
            amr = ALIF + (KASRA if dv != DAMMA else DAMMA) + \
                F + SUKUN + V + dv + L_ + SUKUN
        return _seated({"madi": madi, "mudari": mud, "amr": amr})

    # ---- mudaaf: idgham of the doubled radical ---------------------------
    # مَدَدَ -> مَدَّ, يَمْدُدُ -> يَمُدُّ.
    if "mudaaf" in kinds and not rc.needs_ilal:
        madi = F + FATHA + V + SHADDA + FATHA
        mud = "ي" + FATHA + F + dv + V + SHADDA + DAMMA
        amr = F + dv + V + SHADDA + FATHA
        return _seated({"madi": madi, "mudari": mud, "amr": amr})

    return {}


def _looks_like_form_iv(form, letters, aspect):
    """QAC does not mark every form IV either: أَبْقَى and أَعْمَى are tagged
    plain PERF, and comparing a form-I template against them is comparing two
    different verbs."""
    core = stem_core(form)
    if aspect != "madi":
        return False
    if len(core) > 2 and core[0] in ("أ", "إ", HAMZA) and letters[0] != HAMZA:
        return True
    # form V too: تَجَلَّى and تَمَنَّى are tagged plain PERF, and comparing a
    # form-I template with them compares two different verbs.
    return core.startswith("ت") and SHADDA in core and letters[0] != "ت"


def ilal_check(conn):
    """Regenerate weak roots' citation forms and compare with the mushaf.

    HOW THIS AVOIDS BEING CIRCULAR. No weak root has a sourced bab -- the bab
    derivation is restricted to SOUND roots, because i'lal is exactly what
    distorts a weak root's surface vowels. So the check cannot assume a bab;
    it asks a different question, and states which one:

      strong  the root is attested in BOTH aspects, and ONE bab must
              reproduce BOTH. For an ajwaf the madi is bab-independent
              (قَالَ whatever the bab) but the mudari' is not, so a single
              bab satisfying both is a real constraint. If the madi rule
              produced قَوَلَ, no bab would satisfy it.
      weak    the root is attested in one aspect only, so any bab that fits
              that one slot passes. Counted and reported SEPARATELY, because
              a pass rate that mixes the two overstates the evidence.
    """
    from collections import defaultdict
    oracle = defaultdict(dict)
    for r in q(conn, "SELECT root_ar, form_ar, features FROM segments "
                     "WHERE is_stem=1 AND pos='V' AND root_ar IS NOT NULL"):
        f = r["features"]
        if _FORM_MARK_RE.search(f) or "PASS" in f or "|3MS" not in f:
            continue
        aspect = ("madi" if "|PERF" in f else
                  "mudari" if "|IMPF" in f and "MOOD:" not in f else None)
        if aspect is None:
            continue
        letters = canonical_root(r["root_ar"])
        if len(letters) != 3:
            continue
        if _is_passive_surface(r["form_ar"], letters,
                               "PERF" if aspect == "madi" else "IMPF"):
            continue
        if _looks_like_form_iv(r["form_ar"], letters, aspect):
            continue
        oracle[r["root_ar"]].setdefault(aspect, set()).add(
            stem_core(r["form_ar"]))

    out = {"strong": defaultdict(lambda: [0, 0, [], 0]),
           "weak": defaultdict(lambda: [0, 0, [], 0]),
           "unhandled": defaultdict(int)}
    for root, slots in oracle.items():
        letters = canonical_root(root)
        rc = RootClass(letters)
        kind = rc.primary_kind()
        if kind == "salim":
            continue
        if not ilal_verb_forms(letters, rc, 1):
            out["unhandled"][kind] += 1
            continue
        tier = "strong" if len(slots) == 2 else "weak"
        cell = out[tier][kind]
        cell[1] += 1
        ok = False
        best = None
        for bab in sorted(ABWAB):
            got = ilal_verb_forms(letters, rc, bab)
            if not got:
                continue
            if all(got.get(slot) and stem_core(got[slot]) in attested
                   for slot, attested in slots.items()):
                ok = True
                break
            if best is None:
                best = got
        if ok:
            cell[0] += 1
        elif any(best and best.get(slot) is None for slot in slots):
            # the rules REFUSED this slot rather than getting it wrong --
            # a different outcome and it must not be counted as an error
            cell[3] += 1
        elif len(cell[2]) < 6:
            # the slot that ACTUALLY failed, not the first one: reporting the
            # madi while the mudari' was wrong sent me looking in the wrong
            # place twice.
            bad = None
            for slot, attested in slots.items():
                if not best or not best.get(slot) or \
                        stem_core(best[slot]) not in attested:
                    bad = slot
                    break
            bad = bad or sorted(slots)[0]
            cell[2].append((root, bad, (best or {}).get(bad, "-"),
                            sorted(slots[bad])[0]))
    return out


def _infer_bab_for_check(letters, rc, slots):
    """For the CHECK ONLY: try each bab and see which reproduces the mushaf.
    This is a diagnostic, never a claim -- store_babs() does not use it, and
    nothing derived this way is served."""
    for bab in sorted(ABWAB):
        got = ilal_verb_forms(letters, rc, bab)
        if not got:
            return None
        if all(slot not in slots or got.get(slot) is None or
               stem_core(got[slot]) in slots[slot] for slot in slots):
            return bab
    return None


# ==========================================================================
# 8d.  THE BAB, SOURCED FROM THE MUSHAF ITSELF
# ==========================================================================
#
# The bab is not derivable from a root's letters -- سكن is bab 1 and ضرب is
# bab 2 and nothing in س/ك/ن or ض/ر/ب says so. It has to be READ from
# somewhere.
#
# The plan was to read the mudari' vowel off a cited lexicon page. That is
# impossible with the texts actually available: the OpenITI digitisations of
# Maqayis, al-Mufradat and Lisan carry ZERO diacritics -- measured, 0 marks in
# 125,000 characters -- so the vowel simply is not in them.
#
# But there is a better source already loaded, and it is fully vowelled: the
# QUR'AN. Where a root's form-I verb occurs in both aspects, the mushaf's own
# vowelling gives both harakat, and the bab follows from the pair by rule:
#
#     سَكَنَ (6:13)  +  يَسْكُنُ (7:189)   ->  fatha/damma  ->  bab 1 (nasara)
#
# The citation is a verse, not a page, and the reader can check it in any
# mushaf. That is a stronger warrant than a lexicon reference, not a weaker
# one.
#
# Four restrictions, each of which loses roots and each of which is necessary:
#
#   * SOUND roots only. I'lal moves and lengthens the vowels of a weak root,
#     so its surface harakat are not the pattern's harakat.
#   * FORM I only, and ACTIVE only. QAC does not tag every passive -- 28:58
#     تُسْكَن carries no PASS marker -- so the passive is detected from the
#     vowelling, which states it: a damma on the mudari' prefix, or a
#     damma/kasra pair in the madi, is passive.
#   * BOTH aspects must occur, or there is no pair to read.
#   * ONE vowelling each. Where the mushaf reads a root two ways -- كَبِرَ
#     يَكْبَرُ and كَبُرَ يَكْبُرُ are two verbs sharing a root -- the tool
#     REFUSES rather than taking a majority vote. A silent majority is exactly
#     the kind of quiet inference this program exists to refuse.

FATHA, DAMMA, KASRA = "َ", "ُ", "ِ"
_HARAKAT = (FATHA, DAMMA, KASRA)

BAB_FROM_VOWELS = {
    (FATHA, DAMMA): 1, (FATHA, KASRA): 2, (FATHA, FATHA): 3,
    (KASRA, FATHA): 4, (DAMMA, DAMMA): 5, (KASRA, KASRA): 6,
}

_FORM_MARK_RE = re.compile(r"\((I{2,}|IV|IX|VI{0,3}|X)\)")


def _radical_vowel(form, letters, index):
    """The haraka sitting on radical `index` of a sound triliteral stem."""
    s = strip_wasl(form)
    target = letters[index]
    for i, ch in enumerate(s):
        if ch != target:
            continue
        if i + 1 >= len(s) or s[i + 1] not in _HARAKAT:
            continue
        before, after = s[:i], s[i + 1:]
        if all(letters[j] in before for j in range(index)) and \
                all(letters[j] in after for j in range(index + 1, 3)):
            return s[i + 1]
    return None


def _is_passive_surface(form, letters, aspect):
    """Read the passive off the vowelling, because QAC does not always tag it.
    Mudari' passive is yuFVaLu -- damma on the prefix; madi passive is FuVila
    -- damma on the faa' with kasra on the 'ayn."""
    s = strip_wasl(form)
    if aspect == "IMPF":
        return len(s) > 1 and s[1] == DAMMA
    return (_radical_vowel(form, letters, 0) == DAMMA and
            _radical_vowel(form, letters, 1) == KASRA)


def derive_babs(conn):
    """Return {root: dict} for every root whose bab the mushaf settles."""
    seen = {}
    for r in q(conn, "SELECT root_ar, form_ar, features, sura, aya, word, seg "
                     "FROM segments WHERE is_stem = 1 AND pos = 'V' AND "
                     "root_ar IS NOT NULL ORDER BY sura, aya, word, seg"):
        feats = r["features"]
        if _FORM_MARK_RE.search(feats) or "PASS" in feats:
            continue
        aspect = ("PERF" if "|PERF" in feats else
                  "IMPF" if "|IMPF" in feats else None)
        if aspect is None:
            continue
        letters = canonical_root(r["root_ar"])
        if len(letters) != 3 or not RootClass(letters).is_sound:
            continue
        if _is_passive_surface(r["form_ar"], letters, aspect):
            continue
        v = _radical_vowel(r["form_ar"], letters, 1)
        if v is None:
            continue
        slot = seen.setdefault(r["root_ar"], {"PERF": {}, "IMPF": {}})
        slot[aspect].setdefault(v, "%d:%d:%d:%d %s" % (
            r["sura"], r["aya"], r["word"], r["seg"], r["form_ar"]))

    out = {}
    for root, slots in seen.items():
        if not slots["PERF"] or not slots["IMPF"]:
            continue
        if len(slots["PERF"]) > 1 or len(slots["IMPF"]) > 1:
            out[root] = {"bab": None, "ambiguous": True,
                         "evidence": " | ".join(
                             sorted(slots["PERF"].values()) +
                             sorted(slots["IMPF"].values()))}
            continue
        pv, pref = list(slots["PERF"].items())[0]
        iv, iref = list(slots["IMPF"].items())[0]
        bab = BAB_FROM_VOWELS.get((pv, iv))
        out[root] = {"bab": bab, "ambiguous": False,
                     "evidence": "%s | %s" % (pref, iref)}
    return out


def store_babs(conn):
    """Write the derived babs, citing the Qur'an as their source."""
    babs = derive_babs(conn)
    with unguarded(conn):
        sid = conn.execute(
            "SELECT id FROM sources WHERE key='tanzil'").fetchone()[0]
        n = amb = 0
        for root, info in babs.items():
            if info["ambiguous"] or info["bab"] is None:
                # two different reasons, kept apart: the mushaf reads the root
                # two ways, or the one pair it gives is not a bab pair at all
                # (كَدِمَ + يَقْدُمُ is two verbs sharing a root).
                why = ("ambiguous-in-mushaf" if info["ambiguous"]
                       else "vowels-are-not-a-bab-pair")
                conn.execute(
                    "UPDATE roots SET bab=NULL, bab_verified=0, "
                    "bab_method=?, bab_evidence=? WHERE root_ar=?",
                    (why, info["evidence"], root))
                amb += 1
                continue
            conn.execute(
                "UPDATE roots SET bab=?, bab_source_id=?, bab_verified=1, "
                "bab_method='mushaf-vowelling', bab_evidence=? "
                "WHERE root_ar=?", (info["bab"], sid, info["evidence"], root))
            n += 1
        conn.commit()
    return n, amb


# ==========================================================================
# 8e.  BOOKS NOT KEYED BY ROOT  --  retrieval by string, and it says so
# ==========================================================================
#
# al-Khasa'is is organised by TOPIC, and Sirr Sina'at al-I'rab by LETTER.
# Neither has an article on س ك ن to look up.  So the only honest way in is
# to search the text for the root's own letters -- which is retrieval, not
# analysis, and the difference has to be stated on the page rather than
# assumed by the reader.
#
# THE RULE, WRITTEN DOWN.  A hit is a word in which the radicals occur IN
# ORDER, separated only by the letters a template can insert between them --
# the three long vowels ا و ي.  So a search for س ك ن finds سكن, يسكن, ساكن,
# مسكون, مساكين, تسكين.  For a mudaa'af root the doubled radical may be
# written once (ادغام: مدد -> مد), so the last radical is optional when it
# repeats the second.
#
# WHAT THE RULE COSTS, ALSO WRITTEN DOWN.  This is a string search:
#
#   - it MISSES a form with a consonant infixed between radicals -- form
#     VIII's ta' (اجتمع for ج م ع), and any i'lal that replaces a radical
#     outright (قال for ق و ل: the waw is simply not in the string);
#   - it OVERMATCHES: the separator class cannot tell a template's alif from
#     a different root's radical, so س ل م finds سليمان.
#
# Both failures are the reader's to judge, because every hit is shown as the
# author's own sentence with its page.  What the tool must not do is present
# the search as morphological analysis, or a hit as Ibn Jinni's opinion ON
# this root.  He is discussing whatever he is discussing; the word merely
# occurs there.

# The only letters a wazn inserts between two radicals.  Alif maqsura is
# folded into ya' by canonical_root(), and the dagger alif by norm_alif().
INFIX_LETTERS = "اوي"

SEARCH_IS_A_STRING_SEARCH = (
    "This is a STRING SEARCH, not a morphological analysis: it finds words "
    "in which the radicals occur in order, separated only by ا و ي. It "
    "misses forms that infix a consonant (form VIII اجتمع) or replace a "
    "radical by i'lal (قال from ق و ل), and it overmatches (س ل م finds "
    "سليمان). Every hit below is the author's own sentence with its page; "
    "that this book mentions the word is a fact, and what he means by it is "
    "for you to read.")

REFUSAL_NOT_KEYED_BY_ROOT = (
    "REFUSED. %s is organised by %s, not by root, so it has no article on "
    "%s to quote. Inventing one would file text under something the book "
    "never said. What follows instead is a search of its text.")


def root_search_re(root):
    """Compile the rule above into one regex over normalised text."""
    letters = canonical_root(root)
    sep = "[" + INFIX_LETTERS + "]*"
    parts = [re.escape(norm_alif(x) or x) for x in letters]
    pat = sep.join(parts)
    if len(letters) == 3 and letters[1] == letters[2]:
        # idgham writes the doubled radical once
        pat = parts[0] + sep + parts[1] + "(?:" + sep + parts[2] + ")?"
    return re.compile(pat)


def _blocks_with_pages(raw):
    """Split a stored entry into its paragraphs, each with its own page.

    A long chapter spans many pages, so the ENTRY's page is not the PASSAGE's
    page.  The page is resolved by the same lookahead rule as ingestion: a
    PageV##P### marker CLOSES the page it names, so a block sits on the page
    named by the next marker at or after its last line (trap 15)."""
    lines = raw.splitlines()
    page_at = [(None, None)] * len(lines)
    nxt = (None, None)
    for j in range(len(lines) - 1, -1, -1):
        m = _PAGE_RE.search(lines[j])
        if m:
            nxt = (int(m.group(1)), int(m.group(2)))
        page_at[j] = nxt
    blocks, cur, start = [], [], 0
    for i, line in enumerate(lines):
        if line.startswith("~~") or _HDR_RE.match(line) or not cur:
            if not cur:
                start = i
            cur.append(line)
            continue
        blocks.append((start, cur))
        cur, start = [line], i
    if cur:
        blocks.append((start, cur))
    out = []
    for start, block in blocks:
        text = render_entry("\n".join(block))
        if text:
            # a marker line belongs to no block (it is neither a "# " head
            # nor a "~~" continuation), so a block never spans one and the
            # first and last line agree; the last is the one that matters if
            # that ever stops being true.
            out.append((" ".join(text), page_at[start + len(block) - 1]))
    return out


KEYED_BY_WORD = {"chapter": "topic", "letter": "the letters themselves",
                 "pair": "pairs of words", "urdu": "Urdu headword"}


def root_keyed(source_key):
    """Is this book organised so that a root can be looked up in it at all?"""
    return LEXICONS.get(source_key, {}).get("keyed_by", "root") == "root"


# OpenITI marks a header it generated itself with AUTO. That is the
# digitisation's annotation, not a chapter title Ibn Jinni wrote, so it comes
# off at DISPLAY time by the same principle as render_entry(): the stored
# headword stays verbatim, and the rule that cleans it is readable here.
_AUTO_RE = re.compile(r"^\s*(?:\|+\s*)?AUTO\s+")


def chapter_label(headword):
    return _AUTO_RE.sub("", headword or "").strip()


def passage_search(conn, source_key, root, limit=6):
    """Passages in an unkeyed book whose text matches the root, APPROVED only.

    Returns (hits, n_more, n_pending).  Ranking is by position in the book,
    which is the book's own order and not a relevance score this tool would
    have to invent."""
    rx = root_search_re(root)
    src = q(conn, "SELECT id, title, author, attribution FROM sources "
                  "WHERE key=?", (source_key,)).fetchone()
    if src is None:
        return [], 0, 0
    hits = []
    for e in q(conn, "SELECT headword, vol, page, text_raw FROM v_entries "
                     "WHERE source_id=? ORDER BY id", (src["id"],)):
        if e["text_raw"] is None:
            continue
        for text, (vol, page) in _blocks_with_pages(e["text_raw"]):
            if rx.search(norm_alif(text)):
                hits.append({
                    "chapter": chapter_label(e["headword"]),
                    "vol": str(vol) if vol is not None else e["vol"],
                    "page": str(page) if page is not None else e["page"],
                    "text": text})
    with unguarded(conn):
        pending = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE source_id=? AND verified=0 "
            "AND rejected=0", (src["id"],)).fetchone()[0]
    return hits[:limit], max(0, len(hits) - limit), pending


# ==========================================================================
# 8f.  TAFSIR  --  anchored to the mushaf, or not ingested at all
# ==========================================================================
#
# A tafsir is keyed by AYAH, and a digitisation carries no machine-readable
# sura:aya index.  So the anchor has to be derived, and a wrong anchor is the
# worst failure available here: it puts al-Baghawi's comment on one verse
# under another verse, with his name and a page number on it.
#
# THE ANCHOR IS DERIVED FROM THE MUSHAF, AND CHECKED AGAINST THE BOOK'S OWN
# NUMBERING.  This witness opens each pericope by quoting the ayat it is about,
# in braces, with the ayah numbers printed inside the quotation:
#
#     # {الر تلك آيات الكتاب الحكيم (1) } .
#
# So there are two independent facts: the QUOTED TEXT, which either matches an
# ayah of the corpus or does not, and the PRINTED NUMBER, which the editor
# supplied.  An anchor is accepted only when a quotation matches exactly one
# ayah AND that ayah's number is the number printed beside it.  Where a
# pericope quotes several ayat, every quotation that matches must land in the
# same sura, or the pericope is refused.
#
# Measured on this witness: 1,843 of 2,279 pericopes anchor, covering 5,138 of
# the 6,236 ayat, and the number DISAGREED with the text in zero cases.  The
# 419 that do not anchor are not ingested and are counted in the report -- an
# unanchored comment is a comment about nothing.
#
# THE FOLD.  The mufassir's editor prints modern orthography; the corpus holds
# the Uthmani rasm.  الكتاب is written with a dagger alif, الصلاة is written
# صلوة.  Comparing them therefore needs a key that absorbs the difference:
# marks off, hamza carriers folded together, alif maqsura to ya', ta' marbuta
# to ha', and then EVERY LONG VOWEL DELETED -- which is what reconciles الصلاة
# with the mushaf's الصلوة.  That is a loose key, and it is only safe because
# it is never used alone: the printed ayah number has to agree with it, and an
# anchor is taken only from a key that is UNIQUE across the 6,236 ayat.
# Loosening the key from the strict one moved the anchored count from 985 to
# 1,897 and the disagreement count from 0 to 0.
#
# This key is for MATCHING ONE BOOK TO ANOTHER.  It is not norm_alif /
# norm_drop, which are the search keys, and like them it is never displayed.

_HAMZA_CARRIERS = "ءأإآٱؤئ"

# The three long vowels come out of the comparison key entirely. The muṣḥaf
# writes الصلاة as صلوة -- a WAW where the printed edition has an alif -- so
# dropping the alif alone still leaves لصلوه against لصله, and 2:110 does not
# match itself. Dropping all three is what reconciles them.
LONG_VOWELS = "اوي"


def mushaf_key(text):
    """Fold a printed quotation and an Uthmani ayah onto one comparison key."""
    out = norm_alif(text)
    out = "".join("ا" if ch in _HAMZA_CARRIERS else ch for ch in out)
    out = out.replace("ى", "ي").replace("ة", "ه")
    out = re.sub("[" + LONG_VOWELS + "]", "", out)
    return re.sub(r"\s+", " ", out).strip()


def ayah_index(conn):
    """{key -> [(sura, aya), ...]} over the corpus's own text, plus the ayah
    count of each sura.  Built from the words table, so the muṣḥaf is the
    authority for what an ayah says and how many there are."""
    ayat = {}
    for r in q(conn, "SELECT sura, aya, form_ar FROM words "
                     "ORDER BY sura, aya, word"):
        ayat.setdefault((r["sura"], r["aya"]), []).append(r["form_ar"])
    idx, n_ayat = {}, {}
    for (sura, aya), forms in ayat.items():
        idx.setdefault(mushaf_key(" ".join(forms)), []).append((sura, aya))
        n_ayat[sura] = max(n_ayat.get(sura, 0), aya)
    return idx, n_ayat


REFUSAL_TAFSIR_UNANCHORED = (
    "REFUSED. %d of this book's %d pericopes could not be anchored to an "
    "ayah of the mushaf and were NOT ingested. A comment filed under the "
    "wrong verse is a fabricated attribution; a comment filed under no verse "
    "is a gap you can see.")

_BRACE_RE = re.compile(r"\{([^{}]*)\}")
_AYA_NUM_RE = re.compile(r"\((\d+)\)")

TAFASIR = {
    "baghawi": {
        "title": "Ma'alim al-Tanzil fi Tafsir al-Qur'an (Tafsir al-Baghawi)",
        "author": "al-Husayn ibn Mas'ud al-Baghawi (d. 510 AH)",
        "edition": ("ed. al-Nimr, Damiriyya and al-Harsh; Dar Tayba, "
                    "4th ed. 1417/1997, 8 vols"),
        "licence": "CC BY-NC-SA",
        "licence_note": "OpenITI digitisation; share-alike, non-commercial",
        "distributable": True,
        "url": "https://github.com/OpenITI",
        "attribution": (
            "al-Baghawi, Ma'alim al-Tanzil, ed. al-Nimr, Damiriyya and "
            "al-Harsh (Dar Tayba, 1417/1997), 8 vols. Digital text: OpenITI, "
            "CC BY-NC-SA. https://github.com/OpenITI"),
        # a pericope opens at a level-2 mARkdown header in this witness
        "pericope": "### ||",
        "sura_head": "### |",
    },
}


def _first_paragraph(lines):
    """The pericope's opening paragraph: a '# ' line and its '~~' tail.

    Trap 14, again: the digitisation's own marks sit INSIDE the quotation --
    `كلما رزقوا منها ms0042 من ثمرة` -- so they come off before matching, with
    the same rules render_entry() uses. Leaving them in cost 293 anchors, and
    every one of them looked like the mufassir quoting something the mushaf
    does not contain."""
    body = []
    for line in lines:
        line = _MS_RE.sub("", _PAGE_RE.sub("", line))
        if line.startswith("# ") and body:
            break
        if line.startswith("# ") or line.startswith("~~"):
            body.append(line[2:])
        elif body:
            break
    return " ".join(body).strip()


def anchor_pericope(idx, n_ayat, first_para):
    """(sura, aya_from, aya_to, evidence) or (None, reason).

    Accepts only when the mushaf and the editor's numbering agree."""
    m = _BRACE_RE.search(first_para)
    if not m:
        return None, "the pericope opens with no quotation in braces"
    parts = re.split(r"\((\d+)\)", m.group(1))
    texts, nums = parts[0::2], [int(x) for x in parts[1::2]]
    if not nums:
        return None, "the quotation carries no ayah number"
    sura = None
    evidence = []
    for text, num in zip(texts, nums):
        hits = idx.get(mushaf_key(text))
        if not hits or len(hits) > 1:
            continue                      # this quotation settles nothing
        s, a = hits[0]
        if a != num:
            return None, ("the mushaf makes this quotation %d:%d but the "
                          "book numbers it %d" % (s, a, num))
        if sura is None:
            sura = s
        elif sura != s:
            return None, ("the quotations in one pericope land in suras %d "
                          "and %d" % (sura, s))
        evidence.append("%d:%d" % (s, a))
    if sura is None:
        return None, "no quotation in this pericope matches an ayah exactly"
    inside = [n for n in nums if 1 <= n <= n_ayat.get(sura, 0)]
    if not inside:
        return None, "the printed numbers are outside sura %d" % sura
    return (sura, min(inside), max(inside),
            "text and number agree at " + ", ".join(evidence)), None


def parse_tafsir(text, idx, n_ayat, spec):
    """Yield anchored pericopes; collect the refusals in spec['_refused']."""
    refused = spec.setdefault("_refused", [])
    lines = text.replace("\r", "").split("\n")
    # trap 15 again: a page marker CLOSES the page it names
    page_at = [(None, None)] * len(lines)
    nxt = (None, None)
    for j in range(len(lines) - 1, -1, -1):
        m = _PAGE_RE.search(lines[j])
        if m:
            nxt = (int(m.group(1)), int(m.group(2)))
        page_at[j] = nxt
    # A pericope opens at the level-2 marker. The SURA header is a level-1
    # marker: like a [باب ...] title in Maqayis it CLOSES what is in progress
    # and opens nothing, so the prose under it (the sura's preamble) is not
    # offered as a pericope and then counted as a refusal -- 114 sura headers
    # would otherwise be reported as 114 comments that could not be anchored.
    blocks, cur, start = [], None, 0
    for i, line in enumerate(lines):
        if line.startswith(spec["pericope"]):
            if cur is not None:
                blocks.append((start, cur))
            cur, start = [], i
            continue
        if line.startswith(spec["sura_head"]):
            if cur is not None:
                blocks.append((start, cur))
            cur = None
            continue
        if cur is not None:
            cur.append(line)
    if cur is not None:
        blocks.append((start, cur))
    for start, block in blocks:
        first = _first_paragraph(block)
        got, why = anchor_pericope(idx, n_ayat, first)
        if got is None:
            refused.append(why)
            continue
        sura, aya_from, aya_to, evidence = got
        # The citation is where the passage BEGINS. A pericope can run for
        # six pages, so where it ends is recorded too rather than replacing
        # the start -- citing 2:35 to p. 86 because the discussion ended
        # there would send the reader to the wrong page.
        vol, page = page_at[start]
        _, page_to = page_at[min(start + len(block), len(lines) - 1)]
        yield {"sura": sura, "aya_from": aya_from, "aya_to": aya_to,
               "evidence": evidence, "lines": block,
               "vol": str(vol) if vol is not None else None,
               "page": str(page) if page is not None else None,
               "page_to": (str(page_to) if page_to is not None
                           and page_to != page else None)}


def ingest_tafsir(conn, key, path):
    """Load a tafsir.  Every row lands verified = 0, without exception."""
    if key not in TAFASIR:
        raise ValueError("unknown tafsir %r; known: %s"
                         % (key, ", ".join(sorted(TAFASIR))))
    spec = dict(TAFASIR[key])
    with open(path, "rb") as fh:
        text = fh.read().decode("utf-8")
    idx, n_ayat = ayah_index(conn)
    with unguarded(conn):
        cur = conn.cursor()
        prior = cur.execute(
            "SELECT id, title, author, edition FROM sources WHERE key=?",
            (key,)).fetchone()
        if prior is not None:
            decided = cur.execute(
                "SELECT COUNT(*) FROM tafsir WHERE source_id=? AND "
                "(verified=1 OR rejected=1)", (prior["id"],)).fetchone()[0]
            changed = [f for f in ("title", "author", "edition")
                       if (prior[f] or "") != (spec[f] or "")]
            if changed and decided:
                raise SystemExit(
                    "REFUSED. Source %r already holds %d reviewed passages, "
                    "and this ingest would change its %s. Use a NEW key for "
                    "a different book or witness."
                    % (key, decided, " and ".join(changed)))
        cur.execute(
            "INSERT INTO sources (key,title,author,edition,kind,"
            "licence,licence_note,distributable,url,attribution) "
            "VALUES (?,?,?,?,'tafsir',?,?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET title=excluded.title,"
            "author=excluded.author,edition=excluded.edition,"
            "licence=excluded.licence,licence_note=excluded.licence_note,"
            "distributable=excluded.distributable,url=excluded.url,"
            "attribution=excluded.attribution",
            (key, spec["title"], spec["author"], spec["edition"],
             spec["licence"], spec["licence_note"],
             1 if spec.get("distributable") else 0,
             spec["url"], spec["attribution"]))
        sid = cur.execute("SELECT id FROM sources WHERE key=?",
                          (key,)).fetchone()[0]
        kept = cur.execute(
            "SELECT COUNT(*) FROM tafsir WHERE source_id=? AND "
            "(verified=1 OR rejected=1)", (sid,)).fetchone()[0]
        cur.execute("DELETE FROM tafsir WHERE source_id=? AND verified=0 "
                    "AND rejected=0", (sid,))

        def _fingerprint(raw):
            h = hashlib.sha256()
            h.update(raw.encode("utf-8"))
            return h.hexdigest()

        seen = {}
        if kept:
            seen = {_fingerprint(r["text_raw"] or ""): r["id"]
                    for r in cur.execute(
                        "SELECT id, text_raw FROM tafsir WHERE source_id=?",
                        (sid,))}
        n = recited = 0
        for pc in parse_tafsir(text, idx, n_ayat, spec):
            raw = "\n".join(pc["lines"]).strip()
            if not raw:
                continue
            fp = _fingerprint(raw)
            if fp in seen:
                cur.execute("UPDATE tafsir SET vol=?, page=?, page_to=?, "
                            "sura=?, aya=?, aya_to=?, anchor_evidence=? "
                            "WHERE id=?",
                            (pc["vol"], pc["page"], pc["page_to"], pc["sura"],
                             pc["aya_from"], pc["aya_to"], pc["evidence"],
                             seen[fp]))
                recited += cur.rowcount
                continue
            cur.execute(
                "INSERT INTO tafsir (source_id,sura,aya,aya_to,text_raw,"
                "text_norm,vol,page,page_to,extraction,anchor_method,"
                "anchor_evidence,verified) VALUES (?,?,?,?,?,?,?,?,?,"
                "'pericope','mushaf-quotation',?,0)",
                (sid, pc["sura"], pc["aya_from"], pc["aya_to"], raw,
                 norm_alif(raw), pc["vol"], pc["page"], pc["page_to"],
                 pc["evidence"]))
            n += 1
        conn.commit()
    return n, spec.get("_refused", []), kept, recited


def tafsir_for_aya(conn, sura, aya):
    """Approved commentary covering one ayah.  Pure retrieval."""
    return list(q(conn,
                  "SELECT t.*, s.key, s.title, s.author, s.attribution "
                  "FROM v_tafsir t JOIN sources s ON s.id = t.source_id "
                  "WHERE t.sura=? AND t.aya<=? AND "
                  "COALESCE(t.aya_to, t.aya)>=? ORDER BY s.key, t.id",
                  (sura, aya, aya)))


# ==========================================================================
# 8f2.  SYNONYMS AND OPPOSITES  --  quoted, never computed
# ==========================================================================
#
# SYNONYMS.  al-'Askari heads every article `الفرق بين X و Y`, so the pair is
# the author's own data, read off his title.  What the tool reports is that
# he wrote a chapter separating those two words -- not that they ARE
# synonyms, which is his judgement and not a fact in the letters.  A root
# matches an article when one of the heading's terms contains its radicals by
# the same written-down rule the `mentions` search uses, with the same stated
# costs.
#
# OPPOSITES.  There is no dictionary of Arabic antonym pairs to quote here,
# and an opposite the tool worked out for itself would be a fabrication like
# any other.  But the lexicographers state oppositions constantly, in their
# own words -- Ibn Manzur opens سكن with `السكون ضد الحركة` -- so the tool
# finds the SENTENCE and shows it whole, with its citation, and names the
# word that made it a match.  Reading `ضد الحركة` as "the antonym is حركة" is
# the reader's inference, made on the lexicographer's sentence, not the
# program's on the reader's behalf.

REFUSAL_ANTONYM = (
    "REFUSED. This tool does not work out opposites. No source loaded here "
    "is a dictionary of antonyms, and an opposite it derived itself would be "
    "a fabrication like any other. What it can do is show you the sentences "
    "in which a lexicographer states an opposition in his own words -- the "
    "words ضد, نقيض, خلاف, عكس -- with the page they are on.")

# The four words a lexicographer uses to state an opposition. Matched as
# whole words, with the ordinary prefixes (و ف ب ك ال) allowed in front.
OPPOSITION_WORDS = ("ضد", "نقيض", "خلاف", "عكس")
_OPP_RE = re.compile(r"(?:^|\s)(?:[وفبكل]*(?:ال)?)(?:%s)(?:\s|$)"
                     % "|".join(OPPOSITION_WORDS))
_SENTENCE_SPLIT = re.compile(r"(?<=[.؟!])\s+")


def furuq_articles(conn, root, limit=8):
    """al-'Askari's chapters whose heading names a word of this root."""
    rx = root_search_re(root)
    src = q(conn, "SELECT id, title, author, attribution FROM sources "
                  "WHERE key='furuq'").fetchone()
    if src is None:
        return [], 0, 0
    hits = []
    for e in q(conn, "SELECT headword, vol, page, text_raw FROM v_entries "
                     "WHERE source_id=? ORDER BY id", (src["id"],)):
        terms = heading_farq(e["headword"] or "") or []
        matched = [t for t in terms if rx.search(norm_alif(t))]
        if not matched:
            continue
        hits.append({"heading": clean_heading(e["headword"] or ""),
                     "terms": terms, "matched": matched,
                     "vol": e["vol"], "page": e["page"],
                     "lines": render_entry(e["text_raw"] or "")[:6],
                     "title": src["title"], "author": src["author"],
                     "attribution": src["attribution"]})
    with unguarded(conn):
        pending = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE source_id=? AND verified=0 "
            "AND rejected=0", (src["id"],)).fetchone()[0]
    return hits[:limit], max(0, len(hits) - limit), pending


# The JK digitisation of Lisan carries NO sentence punctuation at all, so
# "the sentence" is the whole article -- 8,000 characters of it. Where there
# is nothing to split on, a window is taken around the matched word instead:
# still one contiguous run of the source's own characters, marked with an
# ellipsis so it is visibly an excerpt and not the whole of what he said.
OPPOSITION_WINDOW = (8, 14)          # words before, words after


def _opposition_window(padded, m):
    """`padded` must be the SAME string the match was found in.

    It was not, once: the caller searched `" " + sent + " "` and this
    function sliced `sent`, so every offset was one character out and
    `السكون ضد الحركة` came back as `ضد لحركة` -- a word of the source
    silently corrupted. Trap 8 again: two functions politely disagreeing."""
    sent = padded.strip()
    if len(sent) <= 240:
        return sent
    before, after = padded[:m.start()].split(), padded[m.end():].split()
    lead, tail = OPPOSITION_WINDOW
    head = " ".join(before[-lead:])
    rest = " ".join(after[:tail])
    out = " ".join(x for x in (head, m.group(0).strip(), rest) if x)
    return ("\u2026 " if len(before) > lead else "") + out + (
        " \u2026" if len(after) > tail else "")


def opposition_statements(conn, root, limit=6):
    """Sentences in the APPROVED lexicons where an opposition is stated.

    The sentence is quoted whole and cited. Which word is the opposite is
    left to the reader: naming it would mean parsing the sentence, and a
    parser that decides what a lexicographer meant is the inference this
    program exists to refuse."""
    out = []
    for e in q(conn, "SELECT e.text_raw, e.vol, e.page, s.title, s.author, "
                     "s.attribution FROM v_entries e JOIN sources s "
                     "ON s.id = e.source_id WHERE e.root_ar = ? ORDER BY e.id",
               ("".join(canonical_root(root)),)):
        for para in render_entry(e["text_raw"] or ""):
            for sent in _SENTENCE_SPLIT.split(para):
                padded = " " + sent + " "
                m = _OPP_RE.search(padded)
                if not m:
                    continue
                out.append({"text": _opposition_window(padded, m),
                            "word": m.group(0).strip(),
                            "title": e["title"], "author": e["author"],
                            "vol": e["vol"], "page": e["page"],
                            "attribution": e["attribution"]})
    return out[:limit], max(0, len(out) - limit)


# ==========================================================================
# 8g.  TRANSLATIONS  --  a second language beside the ayah, never mine
# ==========================================================================
#
# A translation shown beside the Arabic must be a NAMED TRANSLATOR'S, quoted
# whole and attributed, exactly like a lexicon article.  This tool does not
# translate anything.  Rendering `مساكين` as "the needy" would be language
# model output reaching the reader with a scholar's text beside it -- the
# governing rule's central prohibition, in the place where it would be least
# visible.
#
# WHY THESE ROWS ARE NOT GATED.  `entries` and `tafsir` are reviewed because
# their key is DERIVED: a parser decided which root an article belongs to,
# and which ayah a pericope comments on, and a parser can be wrong in a way
# that looks perfectly sourced.  A translation file states `sura|aya|text`.
# The key is in the file; the parser splits on a pipe and infers nothing. So
# these rows sit with `words` and `segments` -- ingested data, served without
# a queue -- and not with the sourced prose that needs a person.
#
# WHAT IS CHECKED INSTEAD.  The one way this could still misattribute is a
# file numbered differently from the mushaf: some editions count the basmala
# as an ayah, and a single offset would put one verse's words under another,
# which is the tafsir anchoring failure arriving by a different road.  So the
# ayah set of the file must equal the corpus's 6,236 EXACTLY, or the ingest
# refuses and prints what differed.

REFUSAL_TRANSLATE_MYSELF = (
    "REFUSED. This tool does not translate. A rendering it composed itself "
    "would be the one thing the whole design forbids -- generated prose "
    "sitting beside a named scholar's words, where it would look exactly "
    "like part of the source. What it shows instead is a published "
    "translator's own text, whole, with his name on it.")

REFUSAL_TRANSLATION_NUMBERING = (
    "REFUSED. This translation's ayah numbering does not match the mushaf "
    "loaded here: %d ayat in the file, %d in the corpus, %d that the corpus "
    "does not have%s. A translation numbered differently would put one "
    "verse's words under another verse. Nothing was ingested.")

TRANSLATION_TERMS = (
    "Translations from Tanzil.net, provided for NON-COMMERCIAL use only. "
    "Copyright remains with the translator or publisher. https://tanzil.net")

# Tanzil's Urdu translations.  Which one to read is the reader's choice and
# not this tool's: the translators belong to different schools, and picking
# one silently would be a judgement the program has no business making.
TRANSLATIONS = {
    "ur.jalandhry": {
        "title": "Qur'an, Urdu -- Jalandhry",
        "author": "Fateh Muhammad Jalandhry (d. 1939)",
        "lang": "ur"},
    "ur.junagarhi": {
        "title": "Qur'an, Urdu -- Junagarhi",
        "author": "Muhammad Junagarhi (d. 1941)",
        "lang": "ur"},
    "ur.kanzuliman": {
        "title": "Qur'an, Urdu -- Kanz al-Iman",
        "author": "Ahmad Raza Khan (d. 1921)",
        "lang": "ur"},
    "ur.maududi": {
        "title": "Qur'an, Urdu -- Tafhim al-Qur'an",
        "author": "Abul A'la Maududi (d. 1979)",
        "lang": "ur"},
    "ur.qadri": {
        "title": "Qur'an, Urdu -- Irfan al-Qur'an",
        "author": "Muhammad Tahir ul Qadri",
        "lang": "ur"},
    "ur.najafi": {
        "title": "Qur'an, Urdu -- Najafi",
        "author": "Muhammad Hussain Najafi",
        "lang": "ur"},
    "ur.jawadi": {
        "title": "Qur'an, Urdu -- Jawadi",
        "author": "Syed Zeeshan Haider Jawadi",
        "lang": "ur"},
    "en.sahih": {
        "title": "Qur'an, English -- Saheeh International",
        "author": "Saheeh International",
        "lang": "en"},
}

TANZIL_TRANS_URL = "https://tanzil.net/trans/%s"

_TRANS_LINE_RE = re.compile(r"^(\d+)\|(\d+)\|(.*)$")


def fetch_text(url, dest=None):
    """Download once, to LUGHAT_HOME, and read from disk ever after.

    The QUERY path never calls this: like `setup`, a translation is fetched
    at build time and the tool is offline afterwards."""
    if dest is None:
        dest = os.path.join(LUGHAT_HOME, "trans",
                            re.sub(r"[^A-Za-z0-9._-]", "_", url.rsplit("/", 1)[-1]))
    if os.path.exists(dest):
        with open(dest, "rb") as fh:
            return fh.read().decode("utf-8")
    d = os.path.dirname(dest)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    import urllib.request
    sys.stderr.write("downloading %s\n" % url)
    with urllib.request.urlopen(url) as r:
        blob = r.read()
    with open(dest, "wb") as fh:
        fh.write(blob)
    return blob.decode("utf-8")


def parse_translation(text):
    """Yield (sura, aya, text) from a Tanzil translation file.

    The file is `sura|aya|text` per line, with a comment block at the end.
    Nothing here is inferred: the numbers are the file's own."""
    for line in text.replace("\r", "").split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _TRANS_LINE_RE.match(line)
        if not m:
            continue
        body = m.group(3).strip()
        if body:
            yield int(m.group(1)), int(m.group(2)), body


def ingest_translation(conn, key, path=None, url=None):
    """Load one translation, after checking it is numbered like the mushaf."""
    if key not in TRANSLATIONS:
        raise ValueError("unknown translation %r; known: %s"
                         % (key, ", ".join(sorted(TRANSLATIONS))))
    spec = TRANSLATIONS[key]
    if path:
        with open(path, "rb") as fh:
            text = fh.read().decode("utf-8")
    else:
        text = fetch_text(url or TANZIL_TRANS_URL % key)
    rows = list(parse_translation(text))
    with unguarded(conn):
        have = {(r["sura"], r["aya"]) for r in conn.execute(
            "SELECT DISTINCT sura, aya FROM words")}
    got = {(s, a) for s, a, _ in rows}
    if got != have:
        extra = sorted(got - have)[:3]
        raise SystemExit(REFUSAL_TRANSLATION_NUMBERING % (
            len(got), len(have), len(got - have),
            (", e.g. " + ", ".join("%d:%d" % x for x in extra))
            if extra else ""))
    with unguarded(conn):
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO sources (key,title,author,edition,kind,licence,"
            "licence_note,distributable,url,attribution) "
            "VALUES (?,?,?,NULL,'translation','non-commercial only',?,0,?,?) "
            "ON CONFLICT(key) DO UPDATE SET title=excluded.title,"
            "author=excluded.author,licence=excluded.licence,"
            "licence_note=excluded.licence_note,url=excluded.url,"
            "attribution=excluded.attribution",
            (key, spec["title"], spec["author"], TRANSLATION_TERMS,
             TANZIL_TRANS_URL % key,
             "%s, %s. Text: Tanzil.net, non-commercial use only. %s"
             % (spec["title"], spec["author"], TANZIL_TRANS_URL % key)))
        sid = cur.execute("SELECT id FROM sources WHERE key=?",
                          (key,)).fetchone()[0]
        cur.execute("DELETE FROM translations WHERE source_id=?", (sid,))
        cur.executemany(
            "INSERT INTO translations (source_id,sura,aya,text) "
            "VALUES (?,?,?,?)", [(sid, s, a, t) for s, a, t in rows])
        conn.commit()
    return len(rows)


def installed_translations(conn):
    return list(q(conn, "SELECT s.key, s.title, s.author, s.attribution "
                        "FROM sources s WHERE s.kind='translation' "
                        "ORDER BY s.key"))


def translations_for_aya(conn, sura, aya):
    """Every installed translation of one ayah.  Pure retrieval."""
    return list(q(conn,
                  "SELECT s.key, s.title, s.author, s.attribution, t.text "
                  "FROM translations t JOIN sources s ON s.id = t.source_id "
                  "WHERE t.sura=? AND t.aya=? ORDER BY s.key", (sura, aya)))


def aya_text(conn, sura, aya):
    """The ayah as the corpus holds it: its own word forms, in order."""
    return " ".join(r["form_ar"] for r in q(
        conn, "SELECT form_ar FROM words WHERE sura=? AND aya=? ORDER BY word",
        (sura, aya)))


# The mushaf trigram index, built once per process. A lexicon entry quotes
# the Qur'an constantly, and where it does, this program already HOLDS the
# ayah -- and, if the reader installed one, a named translator's Urdu for it.
# Showing a machine's rendering of a quotation instead would be strictly
# worse than showing a person's, and measurably so: NLLB turned the sura name
# الأنعام into گائے ("cow", which is al-Baqara) and rendered
# إن صلاتك سكن لهم as a sentence about relationships.
_MUSHAF_TRI = None


def _mushaf_tri(conn):
    global _MUSHAF_TRI
    if _MUSHAF_TRI is None:
        _MUSHAF_TRI = _mushaf_trigrams(conn)
    return _MUSHAF_TRI


def quoted_ayat(conn, text, limit=4):
    """The ayat a passage quotes, by the fold the tafsir anchoring uses.

    TWO trigrams, not one, and the ayah must be UNIQUELY identified. The fold
    deletes all three long vowels, so it is deliberately loose -- loose enough
    that a single 3-word run coincides across the mushaf, and loose enough
    that فبأي آلاء ربكما تكذبان identifies nothing at all because it occurs 31
    times. Both restrictions are the same ones that made the tafsir anchor
    trustworthy, and they are what keep a WRONG published translation from
    being attached to a scholar's sentence -- which would be a worse failure
    than the machine's, because it would carry a translator's name."""
    tri = _mushaf_tri(conn)
    k = mushaf_key(text).split()
    per = collections.Counter()
    for i in range(len(k) - 2):
        for sa in tri.get(" ".join(k[i:i + 3]), ()):
            per[sa] += 1
    # THREE trigrams, not two. Measured on al-Raghib's article on سكن: at a
    # threshold of 2, one paragraph matched 8 ayat of which 6 were WRONG --
    # 50:9, 25:48, 31:10, 43:11 all share من السماء ماء, and 16:72 and 16:81
    # share والله جعل لكم. At 3 exactly the two quoted ayat survive, and both
    # are confirmed by al-Raghib's own printed citations. The tafsir anchoring
    # can afford 2 because it also demands the editor's printed ayah number;
    # here there is usually no number, so the text alone must carry it.
    printed = {int(n) for n in re.findall(r"/\s*(\d{1,3})\s*\]", text)}
    hits = [sa for sa, n in per.items()
            # ...unless the author printed the ayah number himself, which is
            # a second and independent fact, exactly as the tafsir anchor uses
            if n >= 3 or (n >= 2 and sa[1] in printed)]
    # ranked by how much of the ayah was actually recognised, then in mushaf
    # order, so a passing 3-word echo never outranks a full quotation
    hits.sort(key=lambda sa: (-per[sa], sa))
    return hits[:limit]


def quoted_with_translation(conn, text):
    """[{ref, ayah, translations}] for the ayat a passage quotes."""
    out = []
    for sura, aya in quoted_ayat(conn, text):
        trs = [{"key": t["key"], "title": t["title"], "author": t["author"],
                "text": t["text"]}
               for t in translations_for_aya(conn, sura, aya)]
        out.append({"ref": "%d:%d" % (sura, aya),
                    "ayah": aya_text(conn, sura, aya),
                    "translations": trs})
    return out


def quoted_by_para(conn, raw):
    """{paragraph index: [quoted ayah, ...]} for one entry's rendered text."""
    out = {}
    for i, para in enumerate(render_entry(raw)):
        got = quoted_with_translation(conn, para)
        if got:
            out[i] = got
    return out


# ==========================================================================
# 9.  ATTESTATION
# ==========================================================================
#
# TRAP: diacritic-blind matching merged مَسْكَن / مِسْكَن / مُسْكَن / أَسْكَن
# into one word.  They are four different words.  Worse, the ism al-tafdil
# أَسْكَن is character-for-character the perfect stem of form IV at 14:37.
#
# So a hit is either
#   EXACT     -- the vowelled stem agrees, or
#   SKELETON  -- same consonants, different vowels, i.e. A DIFFERENT WORD.
# Only EXACT is attestation, and the grammatical tag is always shown, so an
# exact match against a VERB is never sold as evidence for a NOUN.

class Attestation(object):
    def __init__(self, kind, row):
        self.kind = kind                      # 'EXACT' | 'SKELETON'
        self.sura = row["sura"]
        self.aya = row["aya"]
        self.word = row["word"]
        self.seg = row["seg"]
        self.form_ar = row["form_ar"]
        self.tag = row["tag"]
        self.features = row["features"]
        self.pos = row["pos"]
        self.lemma_ar = row["lemma_ar"]

    @property
    def is_attestation(self):
        """A skeleton hit is NOT attestation.  Nothing may treat it as such."""
        return self.kind == "EXACT"

    @property
    def ref(self):
        return "%d:%d:%d:%d" % (self.sura, self.aya, self.word, self.seg)

    def grammar(self):
        """The corpus's own tag, verbatim -- never our gloss of it."""
        bits = [f for f in self.features.split("|")
                if f not in ("STEM",) and not f.startswith("LEM:")
                and not f.startswith("ROOT:")]
        return " ".join(bits)


def attest(conn, text, root_ar=None, limit=8):
    """Look a generated form up in the corpus.  Pure retrieval.

    The cap is applied AFTER ranking, never before.  Truncating in sura order
    and then sorting EXACT-first can drop every exact hit and leave a screen
    of skeleton matches each stamped "not attestation" -- so the reader
    concludes there is no evidence when there is.  Anything dropped is
    counted and reported, not silently discarded."""
    core = stem_core(text)
    skel = skeleton(text)
    sql = "SELECT * FROM segments WHERE skel = ? AND is_stem = 1"
    params = [skel]
    if root_ar:
        sql += " AND root_ar = ?"
        params.append(root_ar)
    sql += " ORDER BY sura, aya, word, seg"
    hits = []
    seen = set()
    for row in q(conn, sql, params):
        kind = "EXACT" if stem_core(row["form_ar"]) == core else "SKELETON"
        key = (kind, row["form_ar"], row["tag"], row["lemma_ar"])
        if key in seen:
            continue
        seen.add(key)
        hits.append(Attestation(kind, row))
    hits.sort(key=lambda a: (a.kind != "EXACT", a.sura, a.aya, a.word))
    shown, dropped = hits[:limit], hits[limit:]
    return AttestationSet(shown, len(dropped),
                          sum(1 for a in dropped if a.kind == "EXACT"))


class AttestationSet(list):
    """The hits shown, plus an honest count of what the cap left out."""

    def __init__(self, shown, n_dropped, n_dropped_exact):
        list.__init__(self, shown)
        self.n_dropped = n_dropped
        self.n_dropped_exact = n_dropped_exact


def attest_result(conn, result):
    """Attach attestations to every generated form, in place."""
    root_ar = result["root"]
    for f in all_generated_forms(result):
        f.attestations = attest(conn, f.text, root_ar)
    return result


# ==========================================================================
# 10.  PRESENTATION
# ==========================================================================
#
# Every string printed below is (a) a literal in this file, (b) a template
# substitution, or (c) a column read verbatim from the database.  Nothing is
# composed from anywhere else.

NOT_FOUND_UR = "اس لغت میں یہ مادہ نہیں ملا"
NOT_FOUND_EN = "not found in this dictionary"

BAR = "=" * 74
RULE = "-" * 74


def _w(s=""):
    sys.stdout.write(s + "\n")


def print_attestations(ats, indent="      "):
    if not ats:
        _w(indent + "not found in the corpus")
        return
    n_dropped = getattr(ats, "n_dropped", 0)
    for a in ats:
        mark = "EXACT   " if a.kind == "EXACT" else "SKELETON"
        _w("%s%s %-14s %-10s %s" % (indent, mark, a.form_ar, a.ref, a.grammar()))
        if a.kind == "SKELETON":
            _w(indent + "         ^ same consonants, different vowels: "
                        "this is a DIFFERENT WORD, not attestation")
    if n_dropped:
        _w("%s... and %d more not shown (%d of them EXACT)"
           % (indent, n_dropped, ats.n_dropped_exact))


def print_form(f, conn=None):
    if f.is_refusal:
        _w("  %-22s %s" % (f.slot, ""))
        for line in _wrap(f.reason, 68):
            _w("      " + line)
        return
    flag = "" if f.verified else "   [UNVERIFIED - RAW TEMPLATE]"
    _w("  %-22s %s%s" % (f.slot, f.text, flag))
    for c in f.caveats:
        for i, line in enumerate(_wrap(c, 66)):
            _w("      %s %s" % ("!" if i == 0 else " ", line))
    for n in f.notes:
        for i, line in enumerate(_wrap(n, 66)):
            _w("      %s %s" % ("?" if i == 0 else " ", line))
    if conn is not None:
        print_attestations(f.attestations)


def _wrap(text, width):
    out, line = [], ""
    for word in text.split():
        if len(line) + len(word) + 1 > width:
            out.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        out.append(line)
    return out


def cmd_sarf(conn, root, bab=None):
    # A bab the Qur'an settles is a SOURCED fact, so the forms that depend on
    # it stop being hypotheses.
    sourced = None
    if conn is not None:
        try:
            letters = "".join(canonical_root(root))
        except (ValueError, TransliterationError):
            letters = None
        if letters:
            r = q(conn, "SELECT bab, bab_verified, bab_method FROM roots "
                        "WHERE root_ar=?", (letters,)).fetchone()
            if r is not None and r["bab"] and r["bab_verified"]:
                sourced = r["bab"]
    result = generate(root, bab=bab or sourced,
                      bab_source=(None if bab else
                                  ("mushaf" if sourced else None)))
    rc = result["classification"]
    if conn is not None:
        attest_result(conn, result)

    _w(BAR)
    _w("ISHTIQAQ SAGHIR   root: %s   (%s)"
       % (" ".join(result["root"]), to_buckwalter(result["root"])))
    _w(BAR)
    _w("classification: %s" % rc.label())
    for r in rc.reasons:
        _w("  - %s" % r)

    forms = all_generated_forms(result)
    unverified = [f for f in forms if not f.verified]
    if (rc.needs_ilal or rc.needs_idgham or rc.needs_ibdal) and unverified:
        _w("")
        _w("!" * 74)
        _w("!!  THIS ROOT IS NOT SOUND, and %d of the %d forms below are RAW"
           % (len(unverified), len(forms)))
        _w("!!  TEMPLATE OUTPUT, marked [UNVERIFIED]. Naive templating on")
        _w("!!  q-w-l gives the non-word qawala, not qaala. Do not read an")
        _w("!!  unverified line as a claim about Arabic.")
        if len(unverified) < len(forms):
            _w("!!")
            _w("!!  The other %d have had i'lal/idgham applied by rules that"
               % (len(forms) - len(unverified)))
            _w("!!  reproduce every citation form the Qur'an attests for a")
            _w("!!  %s root (%s). Check them yourself:"
               % (rc.primary_kind(),
                  ILAL_VALIDATED.get(rc.primary_kind(), "unmeasured")))
            _w("!!      python3 lughat.py ilal --check")
        _w("!" * 74)

    # --- the bab is a sourced fact, and we do not have it -----------------
    _w("")
    row = None
    if conn is not None:
        row = q(conn, "SELECT bab, bab_verified, bab_page, bab_method, "
                      "bab_evidence FROM roots "
                      "WHERE root_ar = ?", (result["root"],)).fetchone()
    if row is not None and row["bab"] is not None and row["bab_verified"]:
        _w("bab %d, SOURCED: %s" % (row["bab"], row["bab_method"]))
        _w("     evidence: %s" % row["bab_evidence"])
        _w("     Check it in a mushaf. The bab is not derivable from the")
        _w("     letters; this is read off the Qur'an's own vowelling.")
        if bab and bab != row["bab"]:
            _w("     You supplied bab %d, which disagrees with the mushaf."
               % bab)
            _w("     Showing YOURS, labelled as your hypothesis.")
    else:
        _w("bab: UNSOURCED (roots.bab is NULL). The bab of a root is not")
        _w("     derivable from its letters and must be read from a lexicon.")
        if bab:
            _w("     You supplied bab %d. Output below is under YOUR hypothesis;"
               % bab)
            _w("     it is not a sourced fact and carries no citation.")
        else:
            _w("     No bab supplied, so all six are shown as hypotheses.")

    for sec in result["mujarrad"]:
        _w("")
        _w(RULE)
        _w("BAB %d  %s%s" % (sec["bab"], sec["name"],
                             "   [HYPOTHESIS]" if sec["hypothetical"] else ""))
        if sec["condition"]:
            _w("       condition: %s" % sec["condition"])
        _w(RULE)
        for f in sec["forms"]:
            print_form(f, conn)

    _w("")
    _w(RULE)
    _w("DERIVED NOUNS (bab-independent)")
    _w(RULE)
    for f in result["mujarrad_derived"]:
        print_form(f, conn)

    for sec in result["mazid"]:
        _w("")
        _w(RULE)
        _w("FORM %-5s %s" % (sec["roman"], sec["name"]))
        _w(RULE)
        for f in sec["forms"]:
            print_form(f, conn)

    for n in result["notes"]:
        _w("")
        for line in _wrap(n, 72):
            _w(line)
    _w("")
    _w(QAC_ATTRIBUTION)


def cmd_root(conn, root):
    letters = root_letters(root)
    root_ar = "".join(letters)
    rc = RootClass(letters)
    _w(BAR)
    _w("ROOT %s  (%s)   classification: %s"
       % (" ".join(root_ar), to_buckwalter(root_ar), rc.label()))
    _w(BAR)
    row = q(conn, "SELECT * FROM roots WHERE root_ar = ?", (root_ar,)).fetchone()
    if row is None:
        _w(NOT_FOUND_UR)
        _w("%s: this root does not occur in the Quranic Arabic Corpus." %
           NOT_FOUND_EN)
        _w("(That is a fact about the corpus, not about the Arabic language,")
        _w("and this tool will not supply the difference.)")
        return
    _w("%d segments, %d distinct lemmas in the corpus." %
       (row["n_segments"], row["n_lemmas"]))
    if row["bab"] is None or not row["bab_verified"]:
        _w("bab: UNSOURCED -- not derivable from the letters; read it from a")
        _w("     lexicon and store it with a citation before relying on it.")
    else:
        _w("bab %s (source id %s, vol %s p. %s)" %
           (row["bab"], row["bab_source_id"], row["bab_vol"], row["bab_page"]))
    _w("")
    _w("%-18s %-6s %-6s %s" % ("LEMMA", "COUNT", "POS", "FIRST OCCURRENCE"))
    _w(RULE)
    # GROUP BY lemma_bw, not lemma_ar: the corpus's homograph index is what
    # keeps two same-spelled lemmas apart, and merging them would invent a word.
    for r in q(conn,
               "SELECT lemma_bw, lemma_ar, lemma_hom, pos, COUNT(*) n FROM "
               "segments WHERE root_ar = ? AND is_stem = 1 "
               "GROUP BY lemma_bw, pos ORDER BY n DESC", (root_ar,)):
        first = q(conn, "SELECT sura,aya,word,seg,form_ar FROM segments "
                        "WHERE root_ar=? AND is_stem=1 AND lemma_bw IS ? "
                        "AND pos IS ? ORDER BY sura,aya,word,seg LIMIT 1",
                  (root_ar, r["lemma_bw"], r["pos"])).fetchone()
        label = (r["lemma_ar"] or "-") + (
            "  #%d" % r["lemma_hom"] if r["lemma_hom"] else "")
        _w("%-18s %-6d %-6s %s  %d:%d:%d:%d"
           % (label, r["n"], r["pos"] or "-",
              first["form_ar"], first["sura"], first["aya"],
              first["word"], first["seg"]))
    _w("")
    _w("Lexicon entries for this root:")
    ents = list(q(conn, "SELECT * FROM v_entries WHERE root_ar = ?", (root_ar,)))
    pending = 0
    with unguarded(conn):
        # rejected = 0 too: a rejected row is DECIDED. Counting it as pending
        # told the reader material was awaiting review when a person had
        # already ruled on it, and the banner would never clear.
        r = conn.execute("SELECT COUNT(*) n FROM entries WHERE root_ar=? AND "
                         "verified=0 AND rejected=0", (root_ar,)).fetchone()
        pending = r["n"] if r else 0
    if pending:
        # Announced whether or not other entries WERE approved. Showing one
        # lexicon while silently holding another is a lie by omission: the
        # reader would take what they see for everything there is.
        _w("  %d further entry/entries here are NOT APPROVED and are not"
           % pending)
        _w("  shown. Unreviewed text is never served.")
        _w("  Run:  python3 lughat.py serve")
        if ents:
            _w("")
    if not ents and not pending:
        _w("  %s" % NOT_FOUND_UR)
        for line in _wrap(
                "%s. No lexicon has been ingested yet, so this tool has "
                "nothing sourced to say about the MEANING of this root, and "
                "it will not invent any. The morphology above is the corpus; "
                "the meaning is a gap, and the gap is the correct output."
                % NOT_FOUND_EN, 68):
            _w("  " + line)
    for e in ents:
        src = q(conn, "SELECT title, author, edition, attribution FROM sources "
                      "WHERE id=?", (e["source_id"],)).fetchone()
        if src is None:
            # An entry with no source row has no citation, and an entry
            # without a citation is not servable under the governing rule.
            _w("")
            _w("  [entry %d withheld: its source record is missing, so it "
               "carries no citation]" % e["id"])
            continue
        _w("")
        _w("  %s -- %s" % (src["title"], src["author"] or ""))
        if e["extraction"] and e["extraction"] != "direct":
            _w("  [root INFERRED from the heading by the %s bridge]"
               % e["extraction"])
        if e["text_raw"] is None:
            _w("  [scan only: %s]" % e["scan_uri"])
        else:
            for line in render_entry(e["text_raw"]):
                for w in _wrap(line, 70):
                    _w("    " + w)
        _w("      -- %s, vol %s p. %s" % (src["edition"] or "", e["vol"],
                                          e["page"]))
        _w("      %s" % src["attribution"])
    _w("")
    _w(QAC_ATTRIBUTION)


def cmd_review(conn, args):
    """The human approval gate.  Ingestion writes verified = 0; this is the
    only thing that writes verified = 1, and it does so one entry at a time
    after showing a person exactly what they are approving.

    Entries are offered most-useful-first (by how many times the root occurs
    in the Qur'an), because the gate is only honoured if it is bearable."""
    only = root = source = contains = None
    for a in args:
        if a.startswith("--extraction="):
            only = a.split("=", 1)[1]
        elif a.startswith("--source="):
            # A book keyed by letter, topic or pair has no root to filter on,
            # so without this its chapters are unreachable behind 15,000
            # lexicon entries.
            source = a.split("=", 1)[1]
        elif a.startswith("--contains="):
            contains = a.split("=", 1)[1]
        elif a.startswith("--root="):
            # The queue is 15,768 entries deep. Anyone reading ONE word wants
            # that word's articles decided now, not in frequency order three
            # thousand entries from here.
            root = "".join(canonical_root(a.split("=", 1)[1]))
    if "--tafsir" in args:
        return _review_tafsir(conn)
    if "--approve-all" in args and "--everything" in args:
        return _approve_everything(conn)
    if "--approve-all" in args:
        where, params, bits = [], [], []
        if source:
            where.append("e.source_id = (SELECT id FROM sources WHERE key=?)")
            params.append(source)
            bits.append("source %s" % source)
        if only:
            where.append("e.extraction = ?")
            params.append(only)
            bits.append("extraction %s" % only)
        if root:
            where.append("e.root_ar = ?")
            params.append(root)
            bits.append("root %s" % root)
        if contains:
            where.append("(e.headword LIKE ? OR e.text_raw LIKE ?)")
            params += ["%" + contains + "%"] * 2
            bits.append("text containing %s" % contains)
        if not where:
            # Approving EVERYTHING with one keystroke is not a workflow, it is
            # the gate deleting itself. A class has to be named.
            raise SystemExit(
                "REFUSED. --approve-all needs a class to approve: at least "
                "one of --source=, --extraction=, --root=, --contains=, or "
                "--everything for all of it at once.\n"
                "Approving every pending row at once would make the gate "
                "decorative.")
        _bulk_approve(conn, " AND ".join(where), params, ", ".join(bits))
        return
    if "--stats" in args:
        _w(BAR)
        _w("REVIEW QUEUE")
        _w(BAR)
        with unguarded(conn):
            rows = list(conn.execute(
                "SELECT s.title, e.extraction, "
                "CASE WHEN e.rejected=1 THEN 'REJECTED' "
                "     WHEN e.verified=1 THEN 'APPROVED' "
                "     ELSE 'pending' END AS state, COUNT(*) n "
                "FROM entries e JOIN sources s ON s.id=e.source_id "
                "GROUP BY s.title, e.extraction, state "
                "ORDER BY s.title, e.extraction, state"))
        _w("%-26s %-11s %-9s %s" % ("SOURCE", "EXTRACTION", "STATE", "COUNT"))
        _w(RULE)
        for r in rows:
            _w("%-26s %-11s %-9s %d"
               % (r["title"][:26], r["extraction"] or "-", r["state"],
                  r["n"]))
        with unguarded(conn):
            trows = list(conn.execute(
                "SELECT s.title, t.anchor_method, "
                "CASE WHEN t.rejected=1 THEN 'REJECTED' "
                "     WHEN t.verified=1 THEN 'APPROVED' "
                "     ELSE 'pending' END AS state, COUNT(*) n "
                "FROM tafsir t JOIN sources s ON s.id=t.source_id "
                "GROUP BY s.title, t.anchor_method, state "
                "ORDER BY s.title, state"))
        for r in trows:
            _w("%-26s %-11s %-9s %d"
               % (r["title"][:26], (r["anchor_method"] or "-")[:11],
                  r["state"], r["n"]))
        _w("")
        _w("Only APPROVED rows are ever served. Run `review` to work the "
           "queue, `review --tafsir` for the tafsir queue.")
        return

    sql = ("SELECT e.*, s.title FROM entries e JOIN sources s "
           "ON s.id = e.source_id WHERE e.verified = 0 AND e.rejected = 0")
    params = []
    if not only and "--all" not in args:
        # `unmatched` means the heading maps to no root the Qur'an has. The
        # reading page can only be entered by a root the CORPUS knows, so
        # approving one of these changes nothing a reader can ever see. They
        # are still counted in --stats, and still reachable with
        # --extraction=unmatched; they are just not the default work.
        sql += " AND e.extraction IS NOT 'unmatched'"
    if only:
        sql += " AND e.extraction = ?"
        params.append(only)
    if root:
        sql += " AND e.root_ar = ?"
        params.append(root)
    if source:
        sql += (" AND e.source_id = (SELECT id FROM sources WHERE key = ?)")
        params.append(source)
    if contains:
        sql += " AND (e.headword LIKE ? OR e.text_raw LIKE ?)"
        params += ["%" + contains + "%"] * 2
    sql += (" ORDER BY COALESCE((SELECT n_segments FROM roots r "
            "WHERE r.root_ar = e.root_ar), 0) DESC, e.id")
    with unguarded(conn):
        pending = list(conn.execute(sql, params))
    if not pending:
        why = []
        if only:
            why.append("extraction=%s" % only)
        if root:
            why.append("root %s" % root)
        if source:
            why.append("source %s" % source)
        if contains:
            why.append("text containing %s" % contains)
        _w("Nothing pending%s." % (" for " + " and ".join(why) if why else ""))
        return
    with unguarded(conn):
        hidden = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE verified=0 AND rejected=0 "
            "AND extraction='unmatched'").fetchone()[0]
    if hidden and not only and "--all" not in args:
        for line in _wrap(
                "%d further entries are pending whose heading maps to no root "
                "the Qur'an has. The reading page can only be entered by a "
                "root the corpus knows, so approving them changes nothing a "
                "reader can see, and they are not offered here. Use "
                "--extraction=unmatched to work them anyway." % hidden, 72):
            _w(line)
        _w("")
    _w("%d entries pending. y=approve  n=skip  q=quit" % len(pending))
    approved = 0
    for row in pending:
        _w("")
        _w(BAR)
        occ = q(conn, "SELECT n_segments n FROM roots WHERE root_ar=?",
                (row["root_ar"],)).fetchone()
        _w("%s   heading %s   -> root %s   [%s]"
           % (row["title"], row["headword"], row["root_ar"] or "-",
              row["extraction"]))
        _w("vol %s  p. %s   |  root occurs %s times in the Qur'an"
           % (row["vol"], row["page"], occ["n"] if occ else 0))
        if row["flags"]:
            _w("!! FLAG: %s -- check the heading against the printed page"
               % row["flags"])
        if row["extraction"] in ("geminate", "weak_final", "unmatched"):
            _w("!! the root was INFERRED (%s), not read straight from the "
               "heading" % row["extraction"])
        elif row["extraction"] not in ("direct", None):
            # letter / chapter / pair: nothing was inferred, the book simply
            # is not keyed by root. Calling that an inference would teach the
            # reviewer to ignore the warning that matters.
            _w("   this book is keyed by %s, not by root" % row["extraction"])
        _w(RULE)
        body = (render_entry(row["text_raw"]) if row["text_raw"] is not None
                else ["[scan only: %s]" % (row["scan_uri"] or "no scan_uri")])
        for line in body[:6]:
            for w in _wrap(line, 72):
                _w("  " + w)
        _w(BAR)
        try:
            ans = input("approve? [y/n/q] ").strip().lower()
        except EOFError:
            ans = "q"
        if ans == "q":
            break
        if ans == "y":
            with unguarded(conn):
                conn.execute("UPDATE entries SET verified=1, "
                             "verified_at=datetime('now') WHERE id=?",
                             (row["id"],))
                conn.commit()
            approved += 1
    _w("")
    _w("%d approved this session. The rest stay unserved." % approved)


BULK_WARNING = (
    "This approves %d entries WITHOUT showing them to you one at a time.\n"
    "\n"
    "The gate exists because the ROOT of each entry was derived by a parser, "
    "and a parser can be wrong in a way that looks perfectly sourced -- a "
    "digitisation artifact once filed Ibn Faris's article on أكر (digging) "
    "under the root of الله, with a page number on it.\n"
    "\n"
    "What you are about to do is accept a CLASS rather than read its "
    "members. Every row approved this way is stamped `bulk` and stays "
    "distinguishable forever: the reading page badges it, and you can find "
    "them again with  review --stats.  Reject any one of them later with "
    "review --root=<root>.")


def _bulk_approve(conn, sql_where, params, label, sample=12):
    """Approve a whole class at once, after showing a sample of it.

    Not a hidden shortcut: it prints what the gate is for, shows a random
    handful so the class can be judged on evidence rather than hope, and
    requires the word `yes`. And it records HOW each row was approved."""
    with unguarded(conn):
        rows = list(conn.execute(
            "SELECT e.id, e.headword, e.root_ar, e.extraction, e.vol, e.page, "
            "e.text_raw, s.title FROM entries e JOIN sources s "
            "ON s.id = e.source_id WHERE e.verified=0 AND e.rejected=0 AND "
            + sql_where, params))
    if not rows:
        _w("Nothing pending for %s." % label)
        return 0
    _w(BAR)
    _w("BULK APPROVAL   %s" % label)
    _w(BAR)
    for line in (BULK_WARNING % len(rows)).split("\n"):
        for w in (_wrap(line, 72) if line else [""]):
            _w(w)
    _w("")
    # a sample, spread across the class rather than taken from its start:
    # the first N entries of a lexicon are all in the same letter, and a
    # letter is exactly the wrong unit to judge a whole book by.
    step = max(1, len(rows) // sample)
    shown = rows[::step][:sample]
    _w("A sample of %d, spread across the %d:" % (len(shown), len(rows)))
    for r in shown:
        _w("")
        _w("  %s  %s -> %s  [%s]  vol %s p. %s"
           % (r["title"][:22], r["headword"], r["root_ar"] or "-",
              r["extraction"], r["vol"], r["page"]))
        body = render_entry(r["text_raw"] or "")
        for line in _wrap(body[0] if body else "(no text)", 68)[:2]:
            _w("     " + line)
    _w("")
    _w(RULE)
    try:
        ans = input("approve all %d? type yes to confirm: " % len(rows)).strip()
    except EOFError:
        ans = ""
    if ans.lower() != "yes":
        _w("nothing approved.")
        return 0
    with unguarded(conn):
        conn.executemany(
            "UPDATE entries SET verified=1, rejected=0, reject_reason=NULL, "
            "verified_at=datetime('now'), verified_by='bulk' WHERE id=?",
            [(r["id"],) for r in rows])
        conn.commit()
    _w("%d approved, stamped `bulk`." % len(rows))
    return len(rows)


def _bulk_approve_tafsir(conn, sample=6):
    """The same, for the commentary queue.  What is accepted here is a class
    of ANCHORS, so the sample shows the evidence for each one."""
    with unguarded(conn):
        rows = list(conn.execute(
            "SELECT t.id, t.sura, t.aya, t.aya_to, t.vol, t.page, "
            "t.anchor_evidence, t.text_raw, s.title FROM tafsir t "
            "JOIN sources s ON s.id = t.source_id "
            "WHERE t.verified=0 AND t.rejected=0 ORDER BY t.sura, t.aya"))
    if not rows:
        return 0
    step = max(1, len(rows) // sample)
    _w("")
    _w("A sample of the %d tafsir passages, spread across the mushaf:"
       % len(rows))
    for r in rows[::step][:sample]:
        _w("")
        _w("  %s  on %d:%d%s  vol %s p. %s"
           % (r["title"][:22], r["sura"], r["aya"],
              "-%d" % r["aya_to"] if r["aya_to"] and r["aya_to"] != r["aya"]
              else "", r["vol"], r["page"]))
        _w("     anchor: %s" % (r["anchor_evidence"] or "-"))
        body = render_entry(r["text_raw"] or "")
        for line in _wrap(body[0] if body else "(no text)", 68)[:1]:
            _w("     " + line)
    return rows


def _approve_everything(conn):
    """One command, and the gate keeps its meaning because every row it
    touches is stamped.

    Refusing this while offering the same thing one class at a time would be
    theatre: five commands reach the same place. What must not happen is the
    distinction disappearing -- so `bulk` is recorded on every row, the
    reading page badges it, and `review --root=` still lets any of them be
    looked at again."""
    with unguarded(conn):
        ent = list(conn.execute(
            "SELECT e.id, e.headword, e.root_ar, e.extraction, e.vol, e.page, "
            "e.text_raw, s.title FROM entries e JOIN sources s "
            "ON s.id = e.source_id WHERE e.verified=0 AND e.rejected=0 "
            "AND e.extraction IS NOT 'unmatched'"))
        unm = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE verified=0 AND rejected=0 "
            "AND extraction='unmatched'").fetchone()[0]
    _w(BAR)
    _w("APPROVE EVERYTHING REACHABLE")
    _w(BAR)
    for line in (BULK_WARNING % len(ent)).split("\n"):
        for w in (_wrap(line, 72) if line else [""]):
            _w(w)
    if unm:
        _w("")
        for line in _wrap(
                "%d unmatched entries are NOT included: their headings map to "
                "no root the Qur'an has, so approving them would change "
                "nothing you can reach. Use --extraction=unmatched if you "
                "want them anyway." % unm, 72):
            _w(line)
    step = max(1, len(ent) // 12)
    _w("")
    _w("A sample of %d, spread across the %d dictionary entries:"
       % (min(12, len(ent)), len(ent)))
    for r in ent[::step][:12]:
        _w("")
        _w("  %s  %s -> %s  [%s]  vol %s p. %s"
           % (r["title"][:22], r["headword"], r["root_ar"] or "-",
              r["extraction"], r["vol"], r["page"]))
        body = render_entry(r["text_raw"] or "")
        for line in _wrap(body[0] if body else "(no text)", 68)[:2]:
            _w("     " + line)
    tafrows = _bulk_approve_tafsir(conn)
    n_taf = len(tafrows) if tafrows else 0
    _w("")
    _w(RULE)
    try:
        ans = input("approve %d entries and %d tafsir passages? "
                    "type yes to confirm: " % (len(ent), n_taf)).strip()
    except EOFError:
        ans = ""
    if ans.lower() != "yes":
        _w("nothing approved.")
        return 0
    with unguarded(conn):
        conn.executemany(
            "UPDATE entries SET verified=1, rejected=0, reject_reason=NULL, "
            "verified_at=datetime('now'), verified_by='bulk' WHERE id=?",
            [(r["id"],) for r in ent])
        if tafrows:
            conn.executemany(
                "UPDATE tafsir SET verified=1, rejected=0, "
                "reject_reason=NULL, verified_at=datetime('now'), "
                "verified_by='bulk' WHERE id=?",
                [(r["id"],) for r in tafrows])
        conn.commit()
    _w("%d entries and %d tafsir passages approved, every one stamped `bulk`."
       % (len(ent), n_taf))
    _w("")
    _w("The reading page badges them. To look at any of them again:")
    _w("  python3 lughat.py review --root=<root>")
    return len(ent) + n_taf


def _review_tafsir(conn):
    """The same gate, for a commentary.  What is being approved here is not a
    root but an ANCHOR: that this passage really is this book on this ayah.
    So the anchor's evidence is printed above the text, every time."""
    with unguarded(conn):
        pending = list(conn.execute(
            "SELECT t.*, s.title FROM tafsir t JOIN sources s "
            "ON s.id = t.source_id WHERE t.verified = 0 AND t.rejected = 0 "
            "ORDER BY t.sura, t.aya, t.id"))
    if not pending:
        _w("Nothing pending in the tafsir queue.")
        return
    _w("%d passages pending. y=approve  n=skip  q=quit" % len(pending))
    approved = 0
    for row in pending:
        span = ("%d:%d" % (row["sura"], row["aya"])
                if not row["aya_to"] or row["aya_to"] == row["aya"]
                else "%d:%d-%d" % (row["sura"], row["aya"], row["aya_to"]))
        _w("")
        _w(BAR)
        _w("%s   %s" % (row["title"], span))
        _w("vol %s  p. %s%s" % (row["vol"], row["page"],
                                "-%s" % row["page_to"] if row["page_to"]
                                else ""))
        _w("anchor: %s -- %s" % (row["anchor_method"] or "-",
                                 row["anchor_evidence"] or "no evidence"))
        _w(RULE)
        body = (render_entry(row["text_raw"]) if row["text_raw"] is not None
                else ["[scan only: %s]" % (row["scan_uri"] or "no scan_uri")])
        for line in body[:6]:
            for w in _wrap(line, 72):
                _w("  " + w)
        _w(BAR)
        try:
            ans = input("approve? [y/n/q] ").strip().lower()
        except EOFError:
            ans = "q"
        if ans == "q":
            break
        if ans == "y":
            _decide(conn, row["id"], "approve", table="tafsir")
            approved += 1
    _w("")
    _w("%d approved this session. The rest stay unserved." % approved)


def letter_entries(conn, letter):
    """Ibn Jinni on one letter -- APPROVED chapters only, like everything else
    a reader sees."""
    return list(q(conn,
                  "SELECT e.*, s.title, s.author, s.edition, s.attribution "
                  "FROM v_entries e JOIN sources s ON s.id = e.source_id "
                  "WHERE s.key = 'sirr' AND e.headword LIKE ? ORDER BY e.id",
                  ("%" + letter_name(letter) + "%",)))


def letter_name(letter):
    for name, ch in LETTER_NAMES.items():
        if ch == letter and name.startswith("ال") and len(name) > 3:
            return name
    return letter


def cmd_letter(conn, letter):
    """Requirement 1a: what Ibn Jinni says about a root's LETTERS."""
    letters = canonical_root(letter) if len(letter.strip()) > 1 else \
        [letter.strip()]
    _w(BAR)
    _w("THE LETTERS   %s   (Ibn Jinni, Sirr Sina'at al-I'rab)"
       % " ".join(letters))
    _w(BAR)
    for ch in letters:
        _w("")
        _w("%s  (%s)" % (ch, letter_name(ch)))
        _w(RULE)
        ents = letter_entries(conn, ch)
        if not ents:
            with unguarded(conn):
                pending = conn.execute(
                    "SELECT COUNT(*) n FROM entries e JOIN sources s "
                    "ON s.id=e.source_id WHERE s.key='sirr' AND "
                    "e.headword LIKE ? AND e.verified=0 AND e.rejected=0",
                    ("%" + letter_name(ch) + "%",)).fetchone()["n"]
            if pending:
                _w("  %d chapter(s) ingested but NOT APPROVED, so not shown."
                   % pending)
                _w("  Run:  python3 lughat.py serve")
            else:
                _w("  %s" % NOT_FOUND_UR)
                for line in _wrap(
                        "%s: this witness of Sirr Sina'at al-I'rab has no "
                        "chapter for this letter. That is a fact about the "
                        "digitisation, not about Ibn Jinni -- the printed "
                        "book treats all 29." % NOT_FOUND_EN, 68):
                    _w("  " + line)
            continue
        for e in ents:
            for line in render_entry(e["text_raw"])[:4]:
                for w in _wrap(line, 70):
                    _w("    " + w)
            _w("      -- %s, %s, vol %s p. %s"
               % (e["title"], e["edition"] or "", e["vol"], e["page"]))
            _w("      %s" % e["attribution"])
    _w("")


def cmd_akbar(conn, root):
    letters = canonical_root(root)
    _w(BAR)
    _w("AL-ISHTIQAQ AL-AKBAR   root: %s   (Ibn Jinni, al-Khasa'is)"
       % " ".join(letters))
    _w(BAR)
    if len(letters) != 3:
        for line in _wrap(REFUSAL_AKBAR_NOT_THULATHI % len(letters), 72):
            _w(line)
        return
    perms = ishtiqaq_akbar(conn, root)
    _w("The six permutations of these three radicals, and what the Qur'an")
    _w("does with each. Listing them is arithmetic; the counts are the corpus.")
    _w("")
    _w("%-8s %-9s %-7s %s" % ("ORDER", "SEGMENTS", "LEMMAS", "FIRST OCCURRENCE"))
    _w(RULE)
    for p in perms:
        mark = " <- the root asked for" if p.is_original else ""
        if not p.occurs:
            _w("%-8s %-9s %-7s %s%s"
               % (p.root, "-", "-", "does not occur in the Qur'an", mark))
            continue
        ex = p.example
        _w("%-8s %-9d %-7d %s  %d:%d:%d:%d%s"
           % (p.root, p.n_segments, p.n_lemmas, ex["form_ar"], ex["sura"],
              ex["aya"], ex["word"], ex["seg"], mark))
    n = sum(1 for p in perms if p.occurs)
    _w("")
    _w("%d of the %d orderings occur in the Qur'an." % (n, len(perms)))
    if len(perms) < 6:
        _w("(Fewer than six because a radical repeats -- that is arithmetic.)")
    _w("")
    _w("shared sense:")
    for line in _wrap(REFUSAL_AKBAR_SENSE, 70):
        _w("  " + line)
    _w("")
    _w(QAC_ATTRIBUTION)


def cmd_translation(conn, args):
    """List, add or remove a translation shown beside the Arabic.

    Which translator to read is the reader's choice, and the tool installs
    none by default: these translators belong to different schools, and
    picking one silently would be a judgement this program has no business
    making."""
    installed = {r["key"]: r for r in installed_translations(conn)}
    add = [a.split("=", 1)[1] for a in args if a.startswith("--add=")]
    drop = [a.split("=", 1)[1] for a in args if a.startswith("--remove=")]
    src = ([a.split("=", 1)[1] for a in args if a.startswith("--from=")]
           or [None])[0]
    for key in drop:
        with unguarded(conn):
            conn.execute("DELETE FROM translations WHERE source_id IN "
                         "(SELECT id FROM sources WHERE key=?)", (key,))
            conn.execute("DELETE FROM sources WHERE key=? AND "
                         "kind='translation'", (key,))
            conn.commit()
        _w("removed %s" % key)
    for key in add:
        n = ingest_translation(conn, key, path=src)
        _w("%s: %d ayat" % (key, n))
        _w("  numbering checked against the mushaf: all %d agree." % n)
    if add or drop:
        installed = {r["key"]: r for r in installed_translations(conn)}
    _w(BAR)
    _w("TRANSLATIONS   shown beside the Arabic, never generated here")
    _w(BAR)
    for line in _wrap(REFUSAL_TRANSLATE_MYSELF, 72):
        _w(line)
    _w("")
    _w("%-15s %-9s %s" % ("KEY", "STATE", "TRANSLATOR"))
    _w(RULE)
    for key in sorted(TRANSLATIONS):
        spec = TRANSLATIONS[key]
        _w("%-15s %-9s %s" % (key,
                              "installed" if key in installed else "-",
                              spec["author"]))
    _w("")
    _w("  python3 lughat.py translation --add=ur.jalandhry")
    _w("  python3 lughat.py translation --remove=ur.jalandhry")
    _w("")
    for line in _wrap(TRANSLATION_TERMS, 72):
        _w(line)


def cmd_tafsir(conn, ref):
    """Approved commentary on one ayah.  Requirement 4's second half."""
    m = re.match(r"^\s*(\d+)\s*[:. ]\s*(\d+)\s*$", ref)
    if not m:
        raise SystemExit("give an ayah as sura:aya, e.g. 2:35")
    sura, aya = int(m.group(1)), int(m.group(2))
    _w(BAR)
    _w("TAFSIR   %d:%d" % (sura, aya))
    _w(BAR)
    rows = tafsir_for_aya(conn, sura, aya)
    with unguarded(conn):
        pending = conn.execute(
            "SELECT COUNT(*) FROM tafsir WHERE sura=? AND aya<=? AND "
            "COALESCE(aya_to, aya)>=? AND verified=0 AND rejected=0",
            (sura, aya, aya)).fetchone()[0]
    if not rows:
        if pending:
            for line in _wrap(
                    "NOT APPROVED: %d passage(s) covering this ayah are "
                    "ingested and awaiting review, so they are not shown."
                    % pending, 72):
                _w(line)
        else:
            _w("No approved commentary covers this ayah.")
        _w("")
        return
    for r in rows:
        span = ("%d:%d" % (r["sura"], r["aya"])
                if not r["aya_to"] or r["aya_to"] == r["aya"]
                else "%d:%d-%d" % (r["sura"], r["aya"], r["aya_to"]))
        _w("")
        _w("%s   on %s" % (r["title"], span))
        _w("vol %s p. %s%s   [anchor: %s]"
           % (r["vol"], r["page"],
              "-%s" % r["page_to"] if r["page_to"] else "",
              r["anchor_evidence"] or r["anchor_method"] or "-"))
        _w(RULE)
        for line in render_entry(r["text_raw"])[:8]:
            for w in _wrap(line, 70):
                _w("  " + w)
        _w("  %s" % r["attribution"])
    if pending:
        _w("")
        _w("%d further passage(s) on this ayah await review." % pending)
    _w("")


def cmd_mentions(conn, root):
    """Requirement 1b, second half: the books that have no article to look up.

    al-Khasa'is is arranged by topic and Sirr Sina'at al-I'rab by letter, so
    neither can be asked what it says about a root.  It can only be searched,
    and the difference is printed, not glossed over."""
    letters = canonical_root(root)
    _w(BAR)
    _w("MENTIONS   %s   (books not keyed by root)" % " ".join(letters))
    _w(BAR)
    for line in _wrap(SEARCH_IS_A_STRING_SEARCH, 72):
        _w(line)
    _w("")
    _w("matching rule (this is the whole of it):  %s"
       % root_search_re(root).pattern)
    _w("")
    for key in sorted(k for k in LEXICONS if not root_keyed(k)):
        src = q(conn, "SELECT title, attribution FROM sources WHERE key=?",
                (key,)).fetchone()
        if src is None:
            _w("%-10s not ingested." % key)
            continue
        _w(RULE)
        for line in _wrap(REFUSAL_NOT_KEYED_BY_ROOT % (
                src["title"], KEYED_BY_WORD[LEXICONS[key]["keyed_by"]],
                "".join(letters)), 72):
            _w(line)
        hits, more, pending = passage_search(conn, key, root)
        if not hits:
            msg = ("NOT APPROVED: %d chapters of this book are ingested and "
                   "awaiting review, so they were not searched." % pending
                   ) if pending else (
                   "No passage in the approved text matches this root.")
            for line in _wrap(msg, 70):
                _w("  " + line)
            _w("")
            continue
        for h in hits:
            _w("")
            _w("  [%s]  vol %s p. %s" % (h["chapter"], h["vol"], h["page"]))
            for line in _wrap(h["text"], 70):
                _w("    " + line)
        if more:
            _w("")
            _w("  %d further passage%s matched and %s not shown."
               % (more, "" if more == 1 else "s",
                  "was" if more == 1 else "were"))
        if pending:
            _w("  %d chapters are still unapproved and were not searched."
               % pending)
        _w("")
        _w("  %s" % src["attribution"])
        _w("")


def cmd_aya(conn, ref):
    """Print an ayah as the corpus holds it, so it can be checked against a
    printed mushaf by eye.  Pure retrieval: the text is the concatenation of
    the corpus's own segment forms, in order, and nothing else."""
    m = re.match(r"^\s*(\d+)\s*[:. ]\s*(\d+)\s*$", ref)
    if not m:
        raise SystemExit("give an ayah as sura:aya, e.g. 2:35")
    sura, aya = int(m.group(1)), int(m.group(2))
    rows = list(q(conn, "SELECT word, form_ar FROM words WHERE sura=? AND "
                        "aya=? ORDER BY word", (sura, aya)))
    if not rows:
        _w("%d:%d is not in the corpus." % (sura, aya))
        n = q(conn, "SELECT MAX(aya) n FROM segments WHERE sura=?",
              (sura,)).fetchone()["n"]
        if n:
            _w("Sura %d has %d ayat." % (sura, n))
        return
    _w(BAR)
    _w("%d:%d   (%d words)" % (sura, aya, len(rows)))
    _w(BAR)
    _w(" ".join(r["form_ar"] for r in rows))
    for t in translations_for_aya(conn, sura, aya):
        _w("")
        _w("%s  (%s)" % (t["title"], t["author"]))
        for line in _wrap(t["text"], 70):
            _w("  " + line)
    _w("")
    _w("word-by-word:")
    for r in rows:
        segs = list(q(conn, "SELECT form_ar, tag, root_ar, features FROM "
                            "segments WHERE sura=? AND aya=? AND word=? "
                            "ORDER BY seg", (sura, aya, r["word"])))
        roots = sorted({x["root_ar"] for x in segs if x["root_ar"]})
        _w("  %3d  %-22s %-10s %s"
           % (r["word"], r["form_ar"], "/".join(roots) or "-",
              " + ".join(x["tag"] for x in segs)))
    _w("")
    _w(QAC_ATTRIBUTION)
    _w(TANZIL_ATTRIBUTION)


def cmd_word(conn, word):
    # USAGE says words may be typed in Buckwalter; honour that rather than
    # returning a confident zero.
    if not is_arabic(word):
        word = to_arabic(word)
    keys = query_keys(word)
    _w(BAR)
    _w("WORD SEARCH: %s" % word)
    _w(BAR)
    rows = list(q(conn,
                  "SELECT * FROM words WHERE norm_alif IN (%s) OR norm_drop "
                  "IN (%s) ORDER BY sura, aya, word"
                  % (",".join("?" * len(keys)), ",".join("?" * len(keys))),
                  keys + keys))
    _w("%d occurrence(s) as a whole word." % len(rows))
    for r in rows[:40]:
        segs = list(q(conn, "SELECT * FROM segments WHERE sura=? AND aya=? "
                            "AND word=? ORDER BY seg",
                      (r["sura"], r["aya"], r["word"])))
        roots = sorted({s["root_ar"] for s in segs if s["root_ar"]})
        _w("  %-8s %-18s root %-8s %s"
           % ("%d:%d:%d" % (r["sura"], r["aya"], r["word"]), r["form_ar"],
              "/".join(roots) if roots else "-",
              " + ".join(s["tag"] for s in segs)))
    if len(rows) > 40:
        _w("  ... %d more" % (len(rows) - 40))

    srows = list(q(conn,
                   "SELECT * FROM segments WHERE (norm_alif IN (%s) OR "
                   "norm_drop IN (%s)) AND is_stem = 1 ORDER BY sura, aya"
                   % (",".join("?" * len(keys)), ",".join("?" * len(keys))),
                   keys + keys))
    _w("")
    _w("%d occurrence(s) as a stem segment." % len(srows))
    if srows and not rows:
        # State the FACT, not a mechanism.  An earlier build asserted here that
        # the corpus had split off a prefix; for أنفس the extra segment is an
        # attached pronoun SUFFIX, so the explanation was simply untrue. Show
        # the containing word instead and let it speak: it is corpus text, and
        # the reader can see for themselves what is attached.
        _w("  (This stem never stands alone as a whole word; it occurs inside")
        _w("   larger words. The containing word is shown below.)")
    byroot = {}
    for s in srows:
        byroot.setdefault(s["root_ar"], []).append(s)
    for rt, ss in sorted(byroot.items(), key=lambda kv: -len(kv[1])):
        e = ss[0]
        whole = q(conn, "SELECT form_ar FROM words WHERE sura=? AND aya=? AND "
                        "word=?", (e["sura"], e["aya"], e["word"])).fetchone()
        _w("  root %-8s %4d  e.g. %s at %d:%d:%d:%d"
           % (rt or "-", len(ss), e["form_ar"], e["sura"], e["aya"],
              e["word"], e["seg"]))
        _w("       in the word %s   [%s]" % (whole["form_ar"], e["features"]))
    _w("")
    _w(QAC_ATTRIBUTION)


# ==========================================================================
# 11.  TESTS
# ==========================================================================
#
# Two sections.
#
#   INTEGRITY -- did the data load correctly and does search work.
#   HONESTY   -- does the program still refuse where it must.
#
# The HONESTY tests exist to fail LOUDLY if someone later "improves" this code
# in a way that breaks the governing rule.  If one of them fails, the change
# that broke it is wrong; the test is not.

class Fail(AssertionError):
    pass


class Skip(Exception):
    """This check needs data that has not been ingested. Reported as a SKIP,
    never as a pass: a suite that silently passes because the data is absent
    is the vacuous-test problem wearing a different hat."""


def _INGESTED(conn):
    with unguarded(conn):
        return conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] > 1


def need_source(conn, key):
    with unguarded(conn):
        row = conn.execute("SELECT id FROM sources WHERE key=?",
                           (key,)).fetchone()
        n = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE source_id=?",
            (row["id"],)).fetchone()[0] if row else 0
    if not n:
        raise Skip("%s is not ingested" % key)
    return row["id"]


def own_source():
    return open(os.path.abspath(__file__), "rb").read().decode("utf-8")


def strip_comments(body):
    """Drop comment text before grepping a section for CODE.

    A test that greps for "compare_digest" was satisfied by the COMMENT two
    lines below the call, so replacing the real call with == still passed.
    source_section() stops a test finding its own text; this stops it finding
    prose that merely mentions the thing."""
    out = []
    for line in body.splitlines():
        if line.strip().startswith("#"):
            continue
        out.append(line.split("  # ")[0])
    return "\n".join(out)


def source_section(banner, end_banner):
    """Slice a numbered section out of this file.

    Uses rindex for the opening banner on purpose. Several tests grep sections
    that are defined AFTER the test suite, and a test naming a banner puts that
    banner into the file earlier than the real one -- so index() finds the
    needle inside the haystack's description of itself, and the slice comes
    back empty. This trap has now been walked into four times."""
    src = own_source()
    start = src.rindex(banner)
    return src[start:src.index(end_banner, start)]


_TESTS = {"INTEGRITY": [], "HONESTY": []}


def test(section, name):
    def deco(fn):
        _TESTS[section].append((name, fn))
        return fn
    return deco


def ck(cond, msg):
    if not cond:
        raise Fail(msg)


# ------------------------------ INTEGRITY ---------------------------------

@test("INTEGRITY", "corpus loads to the exact published counts")
def _t(conn):
    c = counts(conn)
    for k, want in (("segments", EXPECT_SEGMENTS), ("words", EXPECT_WORDS),
                    ("ayat", EXPECT_AYAT), ("roots", EXPECT_ROOTS)):
        ck(c[k] == want, "%s: got %d, want %d" % (k, c[k], want))
    return "128219 segments / 77429 words / 6236 ayat / 1642 roots"


@test("INTEGRITY", "114 suras")
def _t(conn):
    n = counts(conn)["suras"]
    ck(n == 114, "got %d suras" % n)
    lo = q(conn, "SELECT MIN(sura) a, MAX(sura) b FROM segments").fetchone()
    ck(lo["a"] == 1 and lo["b"] == 114, "sura range %s-%s" % (lo["a"], lo["b"]))
    return "1..114"


@test("INTEGRITY", "al-Baqarah has 286 ayat")
def _t(conn):
    n = q(conn, "SELECT COUNT(DISTINCT aya) n FROM segments WHERE sura = 2"
          ).fetchone()["n"]
    ck(n == 286, "got %d" % n)
    return "286"


@test("INTEGRITY", "112:1 opens with qul")
def _t(conn):
    r = q(conn, "SELECT form_ar, features FROM segments WHERE sura=112 AND "
                "aya=1 AND word=1 AND seg=1").fetchone()
    ck(r["form_ar"] == "قُلْ", "got %r" % r["form_ar"])
    ck("ROOT:qwl" in r["features"], "features %r" % r["features"])
    return "قُلْ  " + r["features"]


@test("INTEGRITY", "masakin -> root س ك ن  (the dagger alif trap)")
def _t(conn):
    keys = query_keys("مساكين")
    rows = list(q(conn, "SELECT DISTINCT root_ar, form_ar FROM segments WHERE "
                        "(norm_alif IN (%s) OR norm_drop IN (%s)) AND is_stem=1"
                  % (",".join("?" * len(keys)), ",".join("?" * len(keys))),
                  keys + keys))
    ck(rows, "مساكين found nothing -- the dagger alif was stripped")
    roots = {r["root_ar"] for r in rows}
    ck("سكن" in roots, "roots found: %s" % roots)
    forms = {r["form_ar"] for r in rows}
    ck(any(DAGGER_ALIF in f for f in forms),
       "no dagger-alif spelling matched: %s" % forms)
    return "%d forms, incl. %s" % (
        len(forms), sorted(f for f in forms if DAGGER_ALIF in f)[0])


@test("INTEGRITY", "rahman found typed both with and without the alif")
def _t(conn):
    hits = {}
    for typed in ("رحمن", "رحمان"):
        keys = query_keys(typed)
        n = q(conn, "SELECT COUNT(*) n FROM segments WHERE norm_alif IN (%s) "
                    "OR norm_drop IN (%s)"
              % (",".join("?" * len(keys)), ",".join("?" * len(keys))),
              keys + keys).fetchone()["n"]
        hits[typed] = n
        ck(n > 0, "typing %s found nothing" % typed)
    return "رحمن=%d  رحمان=%d" % (hits["رحمن"], hits["رحمان"])


@test("INTEGRITY", "Buckwalter round-trips on every form in the corpus")
def _t(conn):
    n = 0
    for r in q(conn, "SELECT form_bw, form_ar FROM segments"):
        ck(to_arabic(r["form_bw"]) == r["form_ar"], "bw->ar %r" % r["form_bw"])
        ck(to_buckwalter(r["form_ar"]) == r["form_bw"],
           "ar->bw %r -> %r" % (r["form_ar"], to_buckwalter(r["form_ar"])))
        n += 1
    # roots are stored CANONICALLY (a hamza radical as ء, not as the corpus's
    # bare alif), so the check is that the canonicaliser agrees, not that the
    # transliterator round-trips.
    for r in q(conn, "SELECT DISTINCT root_bw, root_ar FROM segments "
                     "WHERE root_ar IS NOT NULL"):
        ck("".join(canonical_root(r["root_bw"])) == r["root_ar"],
           "root %r stored as %r" % (r["root_bw"], r["root_ar"]))
        n += 1
    return "%d strings, reversible both ways" % n


@test("INTEGRITY", "transliteration table is a bijection")
def _t(conn):
    ck(len(set(BW_TO_AR.values())) == len(BW_TO_AR), "duplicate Arabic value")
    ck(BW_TO_AR["`"] == DAGGER_ALIF, "` must be U+0670")
    for k, v in BW_TO_AR.items():
        ck(to_buckwalter(to_arabic(k)) == k, "round trip broke on %r" % k)
    return "%d characters" % len(BW_TO_AR)


@test("INTEGRITY", "words are the concatenation of their segments")
def _t(conn):
    r = q(conn, "SELECT form_ar FROM words WHERE sura=1 AND aya=1 AND word=3"
          ).fetchone()
    # Built from the corpus's own Buckwalter rather than a typed literal:
    # a hand-typed Arabic string can differ from the corpus in combining-mark
    # ORDER while looking identical, which is a trap of its own.
    want = to_arabic("{l") + to_arabic("r~aHoma`ni")
    ck(r["form_ar"] == want,
       "got %r (%s) want %r" % (r["form_ar"], to_buckwalter(r["form_ar"]), want))
    bad = q(conn, "SELECT COUNT(*) n FROM words w WHERE w.form_ar <> "
                  "(SELECT group_concat(s.form_ar,'') FROM (SELECT form_ar "
                  "FROM segments WHERE sura=w.sura AND aya=w.aya AND "
                  "word=w.word ORDER BY seg) s)").fetchone()["n"]
    ck(bad == 0, "%d words mismatch their segments" % bad)
    return "1:1:3 = %s, all %d words consistent" % (want, EXPECT_WORDS)


@test("INTEGRITY", "an ayah reconstructs to the corpus's own text")
def _t(conn):
    out = io.StringIO()
    real, sys.stdout = sys.stdout, out
    try:
        cmd_aya(conn, "112:1")
    finally:
        sys.stdout = real
    body = out.getvalue()
    want = " ".join(
        to_arabic(x) for x in ("qulo", "huwa", "{ll~ahu", ">aHadN"))
    ck(want in body, "112:1 did not render as the corpus holds it")
    # the ayah line is the corpus's own segment forms joined in order, with
    # nothing inserted, removed or reordered
    line = [l for l in body.splitlines() if want in l][0]
    ck(line == want, "the ayah line carries extra text: %r" % line)
    segs = [r["form_ar"] for r in q(
        conn, "SELECT form_ar FROM segments WHERE sura=112 AND aya=1 "
              "ORDER BY word, seg")]
    ck(line.replace(" ", "") == "".join(segs),
       "the rendered ayah is not the concatenation of its segments")
    return "112:1 -> %s" % want


@test("INTEGRITY", "wazn substitution survives roots containing ف ع or ل")
def _t(conn):
    ck(apply_wazn("مُسْتَFْVِL", root_letters("علم")) == "مُسْتَعْلِم",
       "ع-root corrupted")
    ck(apply_wazn("تَFْVِيL", root_letters("علم")) == "تَعْلِيم", "bad")
    ck(apply_wazn("مُFَاVَLَة", root_letters("قتل")) == "مُقَاتَلَة", "bad")
    ck(apply_wazn("اِسْتَFْVَLَ", root_letters("فعل")) == "اِسْتَفْعَلَ", "bad")
    return "علم/قتل/فعل all substitute correctly"


# ------------------------------- HONESTY ----------------------------------

@test("HONESTY", "the mujarrad masdar refusal fires, for every bab")
def _t(conn):
    for b in range(1, 7):
        res = generate("سكن", bab=b)
        slots = [f.slot for f in res["mujarrad"][0]["forms"]]
        ck("masdar" in slots, "bab %d has no masdar slot at all" % b)
        ref = [f for f in res["mujarrad"][0]["forms"]
               if f.slot == "masdar"][0]
        ck(ref.is_refusal, "bab %d GENERATED a mujarrad masdar: %r"
           % (b, getattr(ref, "text", None)))
        ck("SAMA'I" in ref.reason, "refusal text lost its reason")
    # and no template anywhere in the mujarrad tables may produce one
    for b, spec in ABWAB.items():
        ck("masdar" not in spec, "bab %d gained a masdar template" % b)
    return "6/6 abwab refuse; no masdar template exists in ABWAB"


@test("HONESTY", "mazid masadir ARE derived (they are qiyasi)")
def _t(conn):
    res = generate("سكن")
    got = {}
    for sec in res["mazid"]:
        ms = [f.text for f in sec["forms"]
              if not f.is_refusal and f.slot.startswith("masdar")]
        ck(ms, "form %s produced no masdar" % sec["roman"])
        got[sec["roman"]] = ms
    ck(got["IV"] == ["إِسْكَان"], "form IV masdar %r" % got["IV"])
    ck(got["X"] == ["اِسْتِسْكَان"], "form X masdar %r" % got["X"])
    return "II..X all derived, e.g. IV=%s X=%s" % (got["IV"][0], got["X"][0])


@test("HONESTY", "weak roots are flagged and never emitted as correct")
def _t(conn):
    cases = {"قول": "ajwaf", "وعد": "mithal", "رمي": "naqis", "قوي": "lafif"}
    for root, kind in cases.items():
        rc = classify_root(root)
        ck(any(kind in k for k in rc.kinds),
           "%s classified %s, expected %s" % (root, rc.kinds, kind))
        ck(rc.needs_ilal, "%s not marked as needing i'lal" % root)
        res = generate(root)
        forms = all_generated_forms(res)
        # A weak root may now carry VERIFIED forms -- but ONLY the mujarrad
        # verb slots of a class whose rules reproduce the Qur'an. Every mazid
        # form is still a raw template, and every form of a class the corpus
        # does not validate still carries its caveat.
        mazid = [f for sec in res["mazid"] for f in sec["forms"]
                 if not f.is_refusal]
        bad = [f for f in mazid if f.verified]
        ck(not bad, "%s emitted %d MAZID forms as VERIFIED, e.g. %r"
           % (root, len(bad), bad[:1]))
        ck(all(f.caveats for f in mazid),
           "%s: a mazid form carried no reliability caveat" % root)
        kind = classify_root(root).primary_kind()
        verified = [f for f in forms if f.verified]
        if kind in ILAL_VALIDATED:
            ck(verified, "%s is a validated %s class but emitted nothing "
                         "verified" % (root, kind))
        else:
            ck(not verified, "%s (%s) is not a validated class yet emitted "
                             "%d verified forms" % (root, kind, len(verified)))
    # the non-word must be GONE now that the ajwaf rules are validated
    res = generate("قول", bab=1)
    madi = res["mujarrad"][0]["forms"][0]
    ck(stem_core(madi.text) == stem_core("قَالَ"),
       "expected قَالَ from the i'lal rules, got %r" % madi.text)
    ck(madi.verified, "قَالَ is not marked verified")
    ck("قَوَلَ" not in [getattr(f, "text", "") for f in all_generated_forms(res)],
       "the non-word قَوَلَ is still emitted somewhere")
    return ("mazid forms of قول/وعد/رمي/قوي all unverified; قَوَلَ is gone, "
            "replaced by قَالَ")


@test("HONESTY", "sound roots still produce verified forms (no blanket flag)")
def _t(conn):
    res = generate("سكن", bab=1)
    sec = res["mujarrad"][0]
    madi = sec["forms"][0]
    ck(madi.verified and madi.text == "سَكَنَ", "got %r" % madi.text)
    ck(sec["forms"][1].text == "يَسْكُنُ", "got %r" % sec["forms"][1].text)
    ck(sec["forms"][4].text == "سَاكِن", "got %r" % sec["forms"][4].text)
    return "سَكَنَ / يَسْكُنُ / سَاكِن verified"


@test("HONESTY", "reliability and applicability doubts are kept apart")
def _t(conn):
    """If every uncertainty printed the same UNVERIFIED banner, the banner
    would stop meaning anything.  A wrong STRING and a right string whose
    APPLICABILITY is unsourced are different claims."""
    sec = generate("سكن", bab=1)["mujarrad"][0]
    maful = [f for f in sec["forms"] if f.slot == "ism maf'ul"][0]
    ck(maful.verified, "مَفْعُول on a salim root should be a sound string")
    ck(maful.notes and not maful.caveats,
       "transitivity is an applicability note, not a template caveat")
    ck("muta'addi" in " ".join(maful.notes), "the note lost its content")
    # a class the corpus does NOT validate still carries caveats everywhere
    weak = [f for f in generate("وعد", bab=2)["mujarrad"][0]["forms"]
            if not f.is_refusal]
    ck(all(f.caveats and not f.verified for f in weak),
       "an unvalidated mithal form carries no reliability caveat")
    # and a validated class's MAZID forms still do
    mazid = [f for sec in generate("قول")["mazid"] for f in sec["forms"]
             if not f.is_refusal]
    ck(all(f.caveats and not f.verified for f in mazid),
       "a mazid form of an ajwaf root is claimed as verified")
    return ("salim: notes without caveats; unvalidated mithal and every mazid "
            "form: caveats")


@test("HONESTY", "a skeleton match is never sold as attestation")
def _t(conn):
    # مَسْكُون: same consonants as attested مَسْكُونَة, but we ask about a form
    # whose vowels differ from a real corpus word.
    ats = attest(conn, "مِسْكَن", "سكن")
    ck(ats, "expected corpus hits on the skeleton م س ك ن")
    skel = [a for a in ats if a.kind == "SKELETON"]
    ck(skel, "no skeleton hits at all -- the distinction may have been lost")
    for a in skel:
        ck(not a.is_attestation,
           "%s at %s was reported as attestation" % (a.form_ar, a.ref))
        ck(stem_core(a.form_ar) != stem_core("مِسْكَن"), "misclassified")
    exact = [a for a in ats if a.kind == "EXACT"]
    ck(not exact, "مِسْكَن should not be EXACT-attested; got %s"
       % [a.form_ar for a in exact])
    return ("مِسْكَن: %d skeleton hits (%s), 0 exact -- none counted as "
            "attestation" % (len(skel),
                             ", ".join(sorted({a.form_ar for a in skel}))[:40]))


@test("HONESTY", "the ism tafdil / form-IV homograph at 14:37 carries its tag")
def _t(conn):
    res = generate("سكن")
    tafdil = [f for f in res["mujarrad_derived"]
              if f.slot == "ism tafdil"][0]
    ck(tafdil.text == "أَسْكَن", "got %r" % tafdil.text)
    ats = attest(conn, tafdil.text, "سكن")
    hit = [a for a in ats if (a.sura, a.aya) == (14, 37)]
    ck(hit, "14:37 not found for أَسْكَن")
    a = hit[0]
    ck(a.kind == "EXACT", "14:37 should be an EXACT string match, got %s" % a.kind)
    ck(a.pos == "V", "14:37 pos is %r -- the tag must be carried" % a.pos)
    ck("PERF" in a.grammar() and "(IV)" in a.grammar(),
       "grammar lost the verbal tag: %r" % a.grammar())
    ck("HOMOGRAPH" in " ".join(tafdil.notes).upper(),
       "the homograph warning was dropped")
    return ("أَسْكَن EXACT at 14:37 but tagged %s -- a verb, not the noun"
            % a.grammar())


@test("HONESTY", "verified = 0 rows are never served")
def _t(conn):
    with unguarded(conn):
        conn.execute("INSERT INTO sources (key,title,kind,attribution) "
                     "VALUES ('_t','TEST','lexicon','TEST')")
        sid = conn.execute(
            "SELECT id FROM sources WHERE key='_t'").fetchone()[0]
        conn.execute("INSERT INTO entries (source_id,root_ar,text_raw,"
                     "text_norm,vol,page,verified) VALUES (?,?,?,?,?,?,0)",
                     (sid, "سكن", "UNVERIFIED PROSE", "x", "1", "1"))
        conn.execute("INSERT INTO entries (source_id,root_ar,text_raw,"
                     "text_norm,vol,page,verified) VALUES (?,?,?,?,?,?,1)",
                     (sid, "سكن", "VERIFIED PROSE", "x", "1", "2"))
    try:
        texts = [r["text_raw"] for r in
                 q(conn, "SELECT text_raw FROM v_entries WHERE root_ar=?",
                   ("سكن",))]
        ck("UNVERIFIED PROSE" not in texts, "an unverified row was served!")
        ck("VERIFIED PROSE" in texts, "the verified row was lost")

        # Every one of these defeated the previous regex guard.  The
        # authorizer sees the table SQLite actually resolved, after aliases,
        # qualifiers, CTEs and views, so none of them can work.
        attacks = [
            "SELECT text_raw FROM entries",
            "SELECT text_raw FROM main.entries",
            'SELECT text_raw FROM "main"."entries"',
            "SELECT text_raw FROM main.[entries]",
            "SELECT text_raw FROM/**/entries",
            "SELECT text_raw FROM /*x*/ entries",
            "SELECT text_raw FROM --x\n entries",
            "SELECT e.text_raw FROM sources s, entries e",
            "WITH z AS (SELECT 1) SELECT text_raw FROM z, entries",
            "SELECT (SELECT text_raw FROM main.entries LIMIT 1)",
            "SELECT text_raw FROM(SELECT * FROM main.entries)",
            "SELECT text_raw FROM main.tafsir",
            "SELECT * FROM v_entries JOIN tafsir ON 1",
        ]
        for sql in attacks:
            try:
                list(q(conn, sql))
            except UnverifiedAccess:
                pass
            else:
                raise Fail("the guard let through: %s" % sql)

        # and laundering the table through a second view must not work either
        with unguarded(conn):
            conn.execute("CREATE VIEW IF NOT EXISTS _launder AS "
                         "SELECT * FROM entries")
        try:
            list(q(conn, "SELECT text_raw FROM _launder"))
        except UnverifiedAccess:
            pass
        else:
            raise Fail("a view over the base table laundered unverified rows")
    finally:
        with unguarded(conn):
            conn.execute("DROP VIEW IF EXISTS _launder")
            conn.execute("DELETE FROM entries WHERE source_id=?", (sid,))
            conn.execute("DELETE FROM sources WHERE id=?", (sid,))
            conn.commit()
    return ("view filters; authorizer rejects %d/%d bypasses plus view "
            "laundering" % (len(attacks), len(attacks)))


@test("HONESTY", "roots.bab is unsourced, and bab-dependent output refuses")
def _t(conn):
    # NOT "no root has a bab" -- 136 are now read off the Qur'an's own
    # vowelling. The invariant is that a bab never appears without a source
    # and its evidence.
    bad = list(q(conn, "SELECT root_ar, bab_source_id, bab_verified, "
                       "bab_evidence FROM roots WHERE bab IS NOT NULL AND "
                       "(bab_source_id IS NULL OR bab_verified = 0 OR "
                       " bab_evidence IS NULL)"))
    ck(not bad, "%d roots carry a bab with no source or no evidence: %s"
       % (len(bad), [r["root_ar"] for r in bad[:3]]))
    n_unsourced = q(conn, "SELECT COUNT(*) n FROM roots WHERE bab IS NULL"
                    ).fetchone()["n"]
    ck(n_unsourced > 1000,
       "only %d roots lack a bab -- has something started inventing them?"
       % n_unsourced)
    res = generate("زقز")            # a root with no sourced bab
    refs = [r for r in res["mujarrad_derived"] if r.is_refusal]
    ck(any("bab" in r.reason.lower() for r in refs),
       "no refusal for the bab-dependent ism makan")
    # every bab section must be marked hypothetical when unsourced
    ck(all(s["hypothetical"] for s in res["mujarrad"]),
       "a bab section was presented as sourced")
    res2 = generate("زقز", bab=1)    # user hypothesis, still not sourced
    ck(res2["mujarrad"][0]["hypothetical"],
       "a CLI-supplied bab was presented as a sourced fact")
    # and a SOURCED bab must not be labelled a hypothesis
    res3 = generate("سكن", bab=1, bab_source="mushaf")
    ck(not res3["mujarrad"][0]["hypothetical"],
       "a sourced bab is still being called a hypothesis")
    return ("%d roots have no sourced bab and still refuse; a supplied bab "
            "stays a hypothesis" % n_unsourced)


@test("HONESTY", "no generative or network dependency in the query path")
def _t(conn):
    src = own_source()
    # The needles are assembled at run time; spelling them out as literals
    # would plant them in the very file this test greps.
    for verb, obj in (("import", "openai"), ("import", "anthropic"),
                      ("from", "openai"), ("from", "anthropic"),
                      ("requests", "post"), ("chat", "completions")):
        needle = verb + (" " if verb in ("import", "from") else ".") + obj
        ck(needle not in src, "found %r in the source" % needle)
    # urllib may be imported, but only inside the setup path
    # urllib.request is the network. urllib.parse is string handling and the
    # review server uses it to read a query string; counting bare "urllib"
    # conflated the two.
    net = "import" + " urllib.request"
    # Every import of it must sit inside a named BUILD-path fetcher. Counting
    # them was the old rule and it only worked while there was exactly one;
    # naming the enclosing function keeps working when a second is added, and
    # still fails the moment one appears anywhere else.
    BUILD_FETCHERS = ("fetch_corpus", "fetch_text")
    at, where = 0, []
    while True:
        i = src.find(net, at)
        if i < 0:
            break
        at = i + 1
        before = src[:i]
        j = before.rfind("\ndef ")
        where.append(before[j + 5:before.find("(", j)] if j >= 0 else "?")
    ck(where, "urllib.request is not imported at all; how does setup fetch?")
    stray = [w for w in where if w not in BUILD_FETCHERS]
    ck(not stray, "urllib.request imported outside the build path: %s" % stray)
    # assembled, so this list does not plant its own needles in the file
    for mod in ("socket", "ssl", "ftplib", "http.client"):
        needle = "import" + " " + mod
        ck(needle not in src, "found %r in the source" % needle)
    # and the query commands must run with the network primitives removed
    import builtins
    real_import = builtins.__import__

    def no_net(name, *a, **k):
        if name.split(".")[0] in ("urllib", "http", "socket", "ssl", "ftplib"):
            raise Fail("query path tried to import %s" % name)
        return real_import(name, *a, **k)

    out = io.StringIO()
    stdout, sys.stdout = sys.stdout, out
    builtins.__import__ = no_net
    try:
        cmd_sarf(conn, "سكن", 1)
        cmd_root(conn, "سكن")
        cmd_word(conn, "مساكين")
    finally:
        builtins.__import__ = real_import
        sys.stdout = stdout
    return "no LLM client; sarf/root/word run with networking barred"


@test("HONESTY", "search keys are never displayed")
def _t(conn):
    """Behavioural, not a grep: poison every search-key column with a sentinel,
    run the real commands, and assert the sentinel never reaches stdout.  A
    normalised key is a string no source ever wrote; printing one would be
    showing the user invented text."""
    SENT = "zzsentinelzz"
    # Poison ONE key column per pass and search on the other, so the rows are
    # still retrieved and would print the sentinel if display ever read a key.
    # The query itself is a real word: echoing the user's own input back is
    # not a leak, and using the sentinel as the query would only test that.
    text = ""
    for poisoned, query in (("norm_drop", "مساكين"), ("norm_alif", "مساكين")):
        out = io.StringIO()
        real, sys.stdout = sys.stdout, out
        try:
            with unguarded(conn):
                conn.execute("SAVEPOINT poison")
                conn.execute(
                    "UPDATE segments SET %s = ?, core = ?" % poisoned,
                    (SENT, SENT))
                conn.execute("UPDATE words SET %s = ?" % poisoned, (SENT,))
                conn.execute(
                    "INSERT INTO sources (key,title,kind,attribution) "
                    "VALUES ('_s','TEST LEXICON','lexicon','TEST')")
                sid = conn.execute(
                    "SELECT id FROM sources WHERE key='_s'").fetchone()[0]
                conn.execute(
                    "INSERT INTO entries (source_id,root_ar,text_raw,"
                    "text_norm,vol,page,verified) VALUES (?,?,?,?,?,?,1)",
                    (sid, "سكن", "VERBATIM ENTRY TEXT", SENT, "1", "9"))
            cmd_word(conn, query)
            cmd_root(conn, "سكن")
            cmd_sarf(conn, "سكن", 1)
        finally:
            sys.stdout = real
            with unguarded(conn):
                conn.execute("ROLLBACK TO poison")
                conn.execute("RELEASE poison")
        chunk = out.getvalue()
        ck(SENT not in chunk,
           "the search key %s reached stdout: %r" % (
               poisoned, [l for l in chunk.splitlines() if SENT in l][:2]))
        ck("VERBATIM ENTRY TEXT" in chunk, "the verbatim entry text was lost")
        ck(query in chunk, "the query was not echoed -- rows were not reached")
        text += chunk
    # and an Attestation must not even carry the lookup keys
    a = attest(conn, "سَاكِن", "سكن")[0]
    for attr in ("core", "skel", "norm_alif", "norm_drop"):
        ck(not hasattr(a, attr), "Attestation exposes %s" % attr)
    return ("poisoned norm_alif / norm_drop / core / text_norm in turn; "
            "%d chars of output, 0 leaks" % len(text))


@test("HONESTY", "lemma homograph indices are preserved, not merged")
def _t(conn):
    """QAC writes `ma`lik` and `ma`lik2` for two different words.  Dropping the
    index would merge them -- the same class of error as diacritic-blindness."""
    n = q(conn, "SELECT COUNT(DISTINCT lemma_bw) n FROM segments WHERE "
                "lemma_hom IS NOT NULL").fetchone()["n"]
    ck(n == 15, "expected 15 indexed lemmas, got %d" % n)
    rows = list(q(conn, "SELECT DISTINCT lemma_bw, lemma_ar, lemma_hom FROM "
                        "segments WHERE lemma_ar = ? ORDER BY lemma_bw",
                  (to_arabic("ma`lik"),)))
    ck(len(rows) == 2, "مَٰلِك collapsed to %d lemma(s)" % len(rows))
    ck({r["lemma_hom"] for r in rows} == {None, 2}, "index lost")
    for r in rows:
        ck(to_arabic(split_lemma(r["lemma_bw"])[0]) == r["lemma_ar"],
           "lemma_ar does not round-trip")
    return "15 indexed lemmas kept distinct, e.g. %s / %s" % (
        rows[0]["lemma_bw"], rows[1]["lemma_bw"])


@test("HONESTY", "hamzat al-wasl does not fake a mismatch, or a match")
def _t(conn):
    """The mushaf writes ٱسْكُنْ, the citation form is اُسْكُنْ: same word, so
    attestation must see EXACT.  But أَسْكَنَ (hamzat al-qat', form IV) must
    NOT collapse into it."""
    amr = [f for f in generate("سكن", bab=1)["mujarrad"][0]["forms"]
           if f.slot.startswith("amr")][0]
    ats = attest(conn, amr.text, "سكن")
    ex = [a for a in ats if a.kind == "EXACT" and (a.sura, a.aya) == (2, 35)]
    ck(ex, "اُسْكُنْ not matched to ٱسْكُنْ at 2:35; hits=%s"
       % [(a.kind, a.form_ar, a.ref) for a in ats])
    ck(ex[0].pos == "V" and "IMPV" in ex[0].grammar(), "tag lost")
    ck(stem_core("ٱسْكُنْ") == stem_core("اُسْكُنْ"), "wasl not normalised")
    ck(stem_core("أَسْكَنَ") != stem_core("ٱسْكُنْ"),
       "hamzat al-qat' was folded into hamzat al-wasl")
    return "اُسْكُنْ = ٱسْكُنْ EXACT at 2:35 (%s); أَسْكَنَ stays distinct" % (
        ex[0].grammar())


@test("HONESTY", "the tanwin alif does not hide a real attestation")
def _t(conn):
    """سَاكِنًا at 25:45 IS the ism fa'il سَاكِن with an accusative tanwin.
    Leaving the tanwin's alif in the stem made the match invisible, which is
    the mirror-image failure of a false match: a gap where evidence exists."""
    ats = attest(conn, "سَاكِن", "سكن")
    ex = [a for a in ats if a.kind == "EXACT"]
    ck(ex, "سَاكِن not attested; hits=%s" % [(a.kind, a.form_ar) for a in ats])
    ck(any((a.sura, a.aya) == (25, 45) for a in ex), "25:45 missing")
    a = [x for x in ex if (x.sura, x.aya) == (25, 45)][0]
    ck("PCPL" in a.grammar(), "tag lost: %s" % a.grammar())
    ck(stem_core("سَاكِنًا") == stem_core("سَاكِن"), "tanwin alif not stripped")
    # but a genuine final alif must survive
    ck(stem_core("هُدًى") != stem_core("هُد"), "alef maksura wrongly stripped")
    return "سَاكِنًا at 25:45 = EXACT (%s)" % a.grammar()


@test("HONESTY", "an absent root says so, and says nothing else")
def _t(conn):
    out = io.StringIO()
    real, sys.stdout = sys.stdout, out
    try:
        cmd_root(conn, "زقز")          # not a Qur'anic root
    finally:
        sys.stdout = real
    text = out.getvalue()
    ck(NOT_FOUND_UR in text, "the not-found line is missing")
    ck("does not occur" in text, "the English gloss of it is missing")
    ck(len(text.splitlines()) < 12,
       "an absent root produced %d lines -- it should produce a gap, not prose"
       % len(text.splitlines()))
    return "%s / %s, and nothing invented" % (NOT_FOUND_UR, NOT_FOUND_EN)


@test("HONESTY", "every corpus root is reachable by the name it is stored under")
def _t(conn):
    """The loader and the query path must canonicalise identically. When they
    disagreed, 135 roots (9,791 segments) were unreachable and `root اله`
    said الله's root does not occur in the Qur'an -- a false statement about
    a named source, which is the worst output this program can produce."""
    bad = []
    for r in q(conn, "SELECT root_ar, root_bw, n_segments FROM roots"):
        for typed in (r["root_ar"], r["root_bw"]):
            hit = q(conn, "SELECT n_segments FROM roots WHERE root_ar = ?",
                    ("".join(canonical_root(typed)),)).fetchone()
            if hit is None:
                bad.append((typed, r["n_segments"]))
    ck(not bad, "%d roots unreachable, e.g. %s" % (len(bad), bad[:3]))
    # and the specific regression, end to end
    for typed in ("اله", "أله", "Alh", "امن", "ابي"):
        out = io.StringIO()
        real, sys.stdout = sys.stdout, out
        try:
            cmd_root(conn, typed)
        finally:
            sys.stdout = real
        # NOT the Urdu line alone -- that also, correctly, marks the empty
        # lexicon section. The claim under test is the corpus one.
        ck("does not occur in the Quranic Arabic Corpus"
           not in out.getvalue(),
           "%r reported as absent from the corpus" % typed)
    return "all %d roots reachable in Arabic and in Buckwalter" % q(
        conn, "SELECT COUNT(*) n FROM roots").fetchone()["n"]


@test("HONESTY", "alef maksura is a weak radical, not a sound one")
def _t(conn):
    """رمى typed with U+0649 was classified salim and produced رَمَىَ / يَرْمُىُ
    with no banner at all -- the tool asserting 'no weak letter' about a
    naqis root."""
    for typed in ("رمى", "رمي", "rmY", "rmy"):
        rc = classify_root(typed)
        ck("naqis" in rc.kinds, "%r classified %s" % (typed, rc.kinds))
        ck(rc.needs_ilal, "%r not marked as needing i'lal" % typed)
        # naqis IS validated now, so its mujarrad verb forms may be
        # verified; nothing else may be.
        mazid = [f for sec in generate(typed)["mazid"] for f in sec["forms"]
                 if not f.is_refusal]
        ck(all(not f.verified for f in mazid),
           "%r emitted a verified mazid form" % typed)
    ck("".join(canonical_root("رمى")) == "".join(canonical_root("رمي")),
       "the two spellings do not canonicalise together")
    return "رمى / رمي / rmY / rmy all naqis, all unverified"


@test("HONESTY", "combining-mark order does not hide attestation")
def _t(conn):
    """The corpus writes نَزَّلَ as zain+shadda+fatha; a template builds it as
    zain+fatha+shadda. Byte comparison called the same word two words and
    discarded the evidence."""
    tpl = apply_wazn("FَVَّLَ", canonical_root("نزل"))
    corpus = q(conn, "SELECT form_ar FROM segments WHERE form_bw='naz~ala'"
               ).fetchone()["form_ar"]
    ck(tpl != corpus, "test is void: the strings are already byte-identical")
    ck(stem_core(tpl) == stem_core(corpus),
       "mark order still splits one word into two")
    ats = attest(conn, tpl, "نزل")
    ck(any(a.kind == "EXACT" for a in ats),
       "form II of نزل is not EXACT-attested; got %s"
       % [(a.kind, a.form_ar) for a in ats][:3])
    # a real vowel difference must STILL separate two words
    ck(stem_core("مَسْكَن") != stem_core("مِسْكَن"), "NFC merged two words")
    ck(stem_core("سَكَنَ") != stem_core("سُكِنَ"), "NFC merged two words")
    return "نَزَّلَ matches the corpus; مَسْكَن / مِسْكَن still distinct"


@test("HONESTY", "attestation is ranked before it is capped")
def _t(conn):
    """Truncating in sura order and sorting afterwards could drop every EXACT
    hit, leaving a screen of skeleton matches each stamped 'not attestation'
    -- so the reader concludes there is no evidence when there is."""
    ats = attest(conn, apply_wazn("FَVَLَ", canonical_root("تبع")), "تبع")
    ck(ats and ats[0].kind == "EXACT",
       "EXACT hit for تَبَعَ was pushed out by the cap; got %s"
       % [(a.kind, a.form_ar) for a in ats][:3])
    ck(any((a.sura, a.aya) == (14, 21) for a in ats), "14:21 missing")
    # nothing may be dropped silently
    many = attest(conn, apply_wazn("FَVَLَ", canonical_root("قول")), "قول",
                  limit=2)
    ck(many.n_dropped > 0 and len(many) == 2, "cap did not engage")
    return "EXACT ranked first; %d hits withheld are reported, not hidden" % (
        many.n_dropped)


@test("HONESTY", "forms the rules exclude are not emitted as correct")
def _t(conn):
    """Three cases where a SOUND root still yields a non-word, so the weak-root
    banner does not fire and nothing else would have caught it."""
    # form VIII: the infixed taa' assimilates after ت (ٱتَّبَعَ, ~99x in the corpus)
    viii = [s for s in generate("تبع")["mazid"] if s["roman"] == "VIII"][0]
    f = viii["forms"][0]
    ck(f.text == "اِتْتَبَعَ", "expected the raw template, got %r" % f.text)
    ck(not f.verified and f.caveats, "اِتْتَبَعَ was emitted as VERIFIED")
    # form VII is not built when the faa' is ن م ر ل و ي ء
    vii = [s for s in generate("نصر")["mazid"] if s["roman"] == "VII"][0]
    ck(not vii["forms"][0].verified, "اِنْنَصَرَ was emitted as VERIFIED")
    # form IX is confined to colours and defects -- an applicability note
    ix = [s for s in generate("نصر")["mazid"] if s["roman"] == "IX"][0]
    ck(any("colour" in n for n in ix["forms"][0].notes),
       "form IX carries no restriction note")
    return "اِتْتَبَعَ and اِنْنَصَرَ flagged; form IX carries its restriction"


@test("HONESTY", "the ism makan does not overclaim its vowel")
def _t(conn):
    """مَسْجِد is bab 1 yet takes maf'il -- a closed sama'i class the qiyas
    cannot see. The tool printed مَسْجَد as verified while its own attestation
    said 'not found in the corpus' for a word that is there 28 times."""
    sec = [x for x in generate("سجد", bab=1)["mujarrad"] if x["bab"] == 1][0]
    makan = [f for f in sec["forms"] if f.slot.startswith("ism makan")][0]
    ck(any("SAMA'I" in n or "sama'i" in n for n in makan.notes),
       "no note about the sama'i maf'il class: %s" % makan.notes)
    ck("مَسْجِد" in " ".join(makan.notes), "the note does not name the case")
    n = q(conn, "SELECT COUNT(*) n FROM segments WHERE root_ar='سجد' AND "
                "form_ar LIKE ?", ("%" + "مَسْجِد" + "%",)).fetchone()["n"]
    ck(n > 0, "مَسْجِد is not in the corpus -- the example is wrong")
    return "note present, and مَسْجِد occurs %d times as the corpus reads it" % n


@test("HONESTY", "the rubaai is derived, not refused, and matches the corpus")
def _t(conn):
    """The rubaai has no bab ambiguity and no sama'i masdar, so R1 does not
    arise. زَلْزَلَة and زِلْزَال are both qiyasi and both Qur'anic."""
    res = generate("زلزل")
    ms = [f for f in all_generated_forms(res) if f.slot.startswith("masdar")]
    ck(len(ms) >= 2, "rubaai masdar not derived")
    attest_result(conn, res)
    ex = {f.text: [a for a in f.attestations if a.kind == "EXACT"] for f in ms}
    ck(ex.get("زَلْزَلَة"), "زَلْزَلَة not attested")
    ck(ex.get("زِلْزَال"), "زِلْزَال not attested")
    # a weak letter in a rubaai takes no i'lal -- the corpus proves it
    w = generate("وسوس")
    madi = [f for f in all_generated_forms(w) if f.slot.startswith("madi")][0]
    ck(madi.verified, "وَسْوَسَ flagged UNVERIFIED though 7:20 reads it exactly")
    ck(any(a.kind == "EXACT" for a in attest(conn, madi.text, "وسوس")),
       "وَسْوَسَ not attested")
    return "زَلْزَلَة 22:1, زِلْزَال 99:1, وَسْوَسَ 7:20 -- all EXACT"


@test("HONESTY", "no mechanism is asserted that was not checked")
def _t(conn):
    """An earlier build told the reader that a stem with no whole-word row had
    been split from a PREFIX. For أنفس the extra segment is a pronoun SUFFIX,
    so the explanation was simply untrue -- generated prose wearing the
    costume of a rule."""
    out = io.StringIO()
    real, sys.stdout = sys.stdout, out
    try:
        cmd_word(conn, "انفس")
    finally:
        sys.stdout = real
    body = out.getvalue()
    ck("prefix" not in body.lower(),
       "the output asserts a prefix mechanism it did not check")
    ck("أَنفُسَهُمْ" in body or "انفسهم" in norm_alif(body),
       "the containing word is not shown")
    return "states the fact, shows the containing word, explains nothing"


@test("HONESTY", "documented input modes actually work")
def _t(conn):
    """USAGE promises Buckwalter input. cmd_word ignored it and returned a
    confident zero for `qul`."""
    for typed in ("qul", "قل"):
        out = io.StringIO()
        real, sys.stdout = sys.stdout, out
        try:
            cmd_word(conn, typed)
        finally:
            sys.stdout = real
        first = [l for l in out.getvalue().splitlines()
                 if "as a whole word" in l][0]
        ck(not first.startswith("0 "), "%r found nothing: %s" % (typed, first))
    return "Buckwalter and Arabic both resolve"


# A small mARkdown fixture with every shape the real file has, so the
# ingestion tests do not depend on a 3.7MB download being present.
_FIXTURE = "\n".join([
    "######OpenITI#",
    "#META# 020.BookTITLE\t:: معجم مقاييس اللغة",
    "#META#",
    "### | [باب السين والكاف وما يثلثهما]",
    "PageV03P087",
    "### | (سكن) ",
    "# السين والكاف والنون أصل واحد مطرد، يدل على خلاف الاضطراب والحركة.",
    "~~ويقال سكن الشيء يسكن سكونا فهو ساكن.",
    "### | اله",
    "# مزة تكملة لهذا السطر.",
    "PageV01P125",
    "### | (أكر)",
    "# الهمزة والكاف والراء أصل واحد، وهو الحفر.",
])


@test("HONESTY", "ingestion never writes a servable row")
def _t(conn):
    """The build path may propose; only a person may approve. Ingestion that
    could write verified = 1 would make the review gate decorative."""
    src = own_source()
    marker = "def " + "ingest_lexicon(conn, key, path):"
    body = src[src.rindex(marker):src.rindex("def " + "ingest_maqayis")]
    ck(len(body) > 800, "the ingest slice is empty (%d)" % len(body))
    ck("verified" in body, "the ingest INSERT does not mention verified")
    # Ingestion may READ verified (to preserve rows a person already decided)
    # but must never WRITE it. Checked structurally rather than by line, since
    # the SQL wraps: no UPDATE of entries at all, and the one INSERT pins 0.
    flat = " ".join(body.split())
    # Ingestion MAY update an entry's citation -- a corrected extraction must
    # reach rows a person already approved, or their decision would stand on
    # a page number the tool now knows is wrong. It may never touch the
    # review state itself.
    for upd in re.findall(r"UPDATE entries SET (.*?) WHERE", flat):
        cols = {c.split("=")[0].strip().strip('"') for c in upd.split(",")}
        for banned in ("verified", "rejected", "verified_at", "reject_reason",
                       "text_raw"):
            ck(banned not in cols,
               "ingestion updates %s -- it may only correct citations" % banned)
    ck(flat.count("INSERT INTO entries") == 1,
       "more than one INSERT into entries in the ingest path")
    ins = flat[flat.index("INSERT INTO entries"):]
    ins = ins[:ins.index(")", ins.index("VALUES")) + 1]
    ck(ins.rstrip().endswith(",0)"),
       "the ingest INSERT does not pin verified to 0: %s" % ins[-40:])
    ck(",flags,verified) " in body and "?,?,0)" in body.replace(" ", ""),
       "the ingest INSERT does not pin verified to 0")
    need_source(conn, "maqayis")
    n = q(conn, "SELECT COUNT(*) n FROM v_entries").fetchone()["n"]
    with unguarded(conn):
        total = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    ck(n < total, "every ingested row is already being served")
    return "ingest pins verified = 0; %d of %d rows servable" % (n, total)


@test("HONESTY", "a digitisation artifact cannot file text under a root")
def _t(conn):
    """OpenITI inserts headers mid-word: '### | اله' followed by '# مزة...'
    is the word الهمزة split in two, and اله canonicalises to the root of
    الله. Treating it as a heading files one root's article under another --
    a sourced-looking quotation that the source never wrote there."""
    got = list(parse_maqayis(_FIXTURE, {"سكن", "ءكر", "ءله"}))
    roots = [e["root_ar"] for e in got]
    ck(roots == ["سكن", "ءكر"], "parsed %s; اله must not become an entry"
       % roots)
    ck(not any("تكملة" in "\n".join(e["lines"]) and e["root_ar"] == "ءله"
               for e in got), "artifact text filed under ءله")
    # the artifact's text is not lost -- it belongs to the entry in progress
    skn = got[0]
    ck(any("تكملة" in l for l in skn["lines"]),
       "the artifact's text was dropped instead of rejoined")
    ck("الهمزة تكملة" in " ".join(render_entry("\n".join(skn["lines"]))),
       "the split word was not rejoined using the source's own spacing")
    # section titles start nothing -- and they must also CLOSE the entry in
    # progress, or the section's own text joins the previous article.
    ck(all(not (e["headword"] or "").startswith("[") for e in got),
       "a section title became an entry")
    sect = list(parse_lexicon("\n".join([
        "### | (سكن) ", "# السين والكاف والنون",
        "### | [باب السين واللام]", "# section preamble text",
        "### | (سلم) ", "# السين واللام والميم",
    ]), {"سكن", "سلم"}, LEXICONS["maqayis"]))
    first = [e for e in sect if e["root_ar"] == "سكن"][0]
    ck("preamble" not in "\n".join(first["lines"]),
       "a [باب ...] title did not close the entry; its text joined the "
       "previous article")
    return "only (root) headings create entries; artifact text is rejoined"


@test("HONESTY", "ingested text is byte-exact, and markup is stripped only "
                 "for display")
def _t(conn):
    got = list(parse_maqayis(_FIXTURE, {"سكن", "ءكر"}))
    raw = "\n".join(got[0]["lines"])
    for line in raw.splitlines():
        ck(line in _FIXTURE, "a stored line is not in the source: %r" % line)
    ck("~~" in raw and "# " in raw,
       "markup was stripped before storage; text_raw must be verbatim")
    shown = render_entry(raw)
    ck(not any("~~" in l or l.startswith("# ") for l in shown),
       "display leaked mARkdown markup")
    ck("PageV" not in " ".join(shown), "display leaked a page marker")
    # the same rule, on the marks a different digitisation uses: JK's Lisan
    # brackets 6,136 Qur'anic quotations with @QB@ ... @QE@
    marked = "# قوله تعالى @QB@ وله ما سكن @QE@ قال ابن الأعرابي"
    got = " ".join(render_entry(marked))
    ck("@Q" not in got, "display leaked a quotation marker: %r" % got)
    ck("وله ما سكن" in got, "stripping the marker ate the quotation")
    ck('"' not in got and "\u00ab" not in got,
       "the renderer invented punctuation the book does not have: %r" % got)
    ck("خلاف الاضطراب والحركة" in " ".join(shown), "the text itself was lost")
    return "stored verbatim (%d chars), rendered clean" % len(raw)


@test("HONESTY", "the queue offers work that can change what a reader sees")
def _t(conn):
    """An `unmatched` entry's heading maps to no root the Qur'an has, and the
    reading page can only be entered by a root the CORPUS knows -- so
    approving one changes nothing anybody can see. Leading the queue with
    11,043 of them is how a gate becomes unfinishable. They are counted in
    --stats and reachable with --extraction=unmatched; they are not the
    default work, and the reviewer is told the number and the reason."""
    with unguarded(conn):
        row = conn.execute(
            "SELECT root_ar FROM entries WHERE extraction='unmatched' AND "
            "root_ar IS NOT NULL LIMIT 1").fetchone()
    if row is None:
        raise Skip("no unmatched entries ingested")
    # the premise: such a root really is unreachable from the reader
    ck(read_root(conn, row[0]).get("absent"),
       "%s is reachable after all; the queue is hiding useful work" % row[0])
    with unguarded(conn):
        conn.execute("SAVEPOINT unm")
        top = conn.execute("SELECT root_ar FROM roots ORDER BY n_segments "
                           "DESC LIMIT 1").fetchone()[0]
        conn.execute("INSERT INTO entries (source_id,root_ar,headword,"
                     "text_raw,vol,page,extraction,verified) SELECT id,?,?,"
                     "'UNMATCHED FIXTURE','1','1','unmatched',0 "
                     "FROM sources WHERE kind='lexicon' LIMIT 1",
                     (top, "(%s)" % top))
    try:
        default = {r["extraction"] for r in _queue_rows(conn, limit=400)}
        ck("unmatched" not in default,
           "the default queue leads with work no reader can see")
        asked = _queue_rows(conn, extraction="unmatched", limit=5)
        ck(asked and all(r["extraction"] == "unmatched" for r in asked),
           "asking for unmatched does not return them")
    finally:
        with unguarded(conn):
            conn.execute("ROLLBACK TO unm")
            conn.execute("RELEASE unm")
    # and the count is not swallowed
    src = strip_comments(own_source())
    ck("further entries are pending whose heading maps to no root" in src,
       "the reviewer is not told what was left out, or why")
    return "default queue holds %s; unmatched offered only on request" % (
        ", ".join(sorted(default)) or "nothing")


@test("HONESTY", "a row waved through in bulk says so, forever")
def _t(conn):
    """Bulk approval is a real weakening of the gate, so it is not allowed to
    be invisible: the row records HOW it was approved, and the reader sees a
    badge. "A person read this" and "a person accepted the class it belongs
    to" are different claims about the same text."""
    src = strip_comments(own_source())
    # the bulk path must stamp, and must be the only thing that stamps 'bulk'
    stamps = set(re.findall(r"verified_by *= *'([a-z]+)'", src))
    ck(stamps == {"bulk"}, "verified_by is written as %s" % sorted(stamps))
    ck("--approve-all" in src, "the bulk path has gone")
    # it must refuse to approve everything at once -- called, not grepped
    out = io.StringIO()
    real, sys.stdout = sys.stdout, out
    try:
        cmd_review(conn, ["--approve-all"])
        ck(False, "--approve-all with no class named was not refused")
    except SystemExit as e:
        ck("REFUSED" in str(e), "it refused without saying why: %s" % e)
    finally:
        sys.stdout = real
    # and it must show a sample and demand a typed confirmation
    fn = src[src.index("def " + "_bulk_approve("):]
    fn = fn[:fn.index("\ndef ")]
    ck("sample" in fn and "input(" in fn and '"yes"' in fn,
       "bulk approval neither samples nor confirms")
    ck("rows[::step]" in fn,
       "the sample is taken from the start of the class, where every entry "
       "is in the same letter")
    # the badge reaches the page
    ck('"bulk"' in READ_HTML or "e.bulk" in READ_HTML,
       "the reading page does not badge a bulk-approved entry")
    with unguarded(conn):
        n = conn.execute("SELECT COUNT(*) FROM entries WHERE "
                         "verified_by = ?", ("bulk",)).fetchone()[0]
    return "%d rows stamped bulk and badged; --approve-all needs a class" % n


@test("HONESTY", "an ingested entry is not served until it is approved")
def _t(conn):
    with unguarded(conn):
        conn.execute("SAVEPOINT ing")
        conn.execute("INSERT INTO sources (key,title,kind,attribution) "
                     "VALUES ('_ing','ING','lexicon','ING')")
        sid = conn.execute(
            "SELECT id FROM sources WHERE key='_ing'").fetchone()[0]
        conn.execute("INSERT INTO entries (source_id,root_ar,headword,"
                     "text_raw,vol,page,extraction,verified) "
                     "VALUES (?,?,?,?,?,?,'direct',0)",
                     (sid, "سكن", "(سكن)", "PENDING PROSE", "3", "87"))
        eid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    try:
        out = io.StringIO()
        real, sys.stdout = sys.stdout, out
        try:
            cmd_root(conn, "سكن")
        finally:
            sys.stdout = real
        ck("PENDING PROSE" not in out.getvalue(), "an unapproved row was served")
        ck("NOT APPROVED" in out.getvalue(),
           "the reader is not told that pending text exists")
        # now approve it, exactly as `review` does
        with unguarded(conn):
            conn.execute("UPDATE entries SET verified=1, "
                         "verified_at=datetime('now') WHERE id=?", (eid,))
        out = io.StringIO()
        real, sys.stdout = sys.stdout, out
        try:
            cmd_root(conn, "سكن")
        finally:
            sys.stdout = real
        ck("PENDING PROSE" in out.getvalue(),
           "approving did not make the row servable")
        with unguarded(conn):
            r = conn.execute("SELECT verified_at FROM entries WHERE id=?",
                             (eid,)).fetchone()
        ck(r["verified_at"], "approval left no audit stamp")
    finally:
        with unguarded(conn):
            conn.execute("ROLLBACK TO ing")
            conn.execute("RELEASE ing")
    return "pending hidden but announced; approved served; stamped"


@test("HONESTY", "Kilani's OCR is a search key and never reaches the reader")
def _t(conn):
    """The one source here whose stored text is not its author's words.

    The scan has no text layer; the OCR misreads Urdu (پاکیزہ -> باكيزه) and
    corrupts Arabic (خَاوِيَةٍ -> خَاوِيَتٍ). Serving any of it as Kilani's
    prose would be a fabricated attribution arriving by a new door. So the
    OCR lives in text_norm -- a search key this program never displays -- and
    text_raw is NULL, which the schema already reads as scan-only."""
    ck(LEXICONS["mutaradifaat"]["keyed_by"] == "urdu",
       "Kilani must not be root-keyed: he is arranged by Urdu headword")
    ck(not root_keyed("mutaradifaat"),
       "a book that cannot be asked about a root must get no root card")
    marker = "OCR-TEXT-THAT-MUST-NEVER-BE-SERVED"
    with unguarded(conn):
        conn.execute("SAVEPOINT kil")
        conn.execute(
            "INSERT INTO sources (key,title,author,edition,kind,licence,"
            "distributable,url,attribution) VALUES "
            "('mutaradifaat','K','K','K','lexicon','in copyright',0,'','K') "
            "ON CONFLICT(key) DO NOTHING")
        sid = conn.execute("SELECT id FROM sources WHERE key='mutaradifaat'"
                           ).fetchone()[0]
        conn.execute(
            "INSERT INTO entries (source_id,root_ar,headword,text_raw,"
            "text_norm,page,scan_uri,extraction,link_evidence,page_method,"
            "verified) VALUES (?,'سكن','X',NULL,?,'383','scan p. 400',"
            "'ocr-confirmed','20:88','header',1)", (sid, marker))
    try:
        blob = json.dumps(read_root(conn, "سكن"), ensure_ascii=False)
        ck(marker not in blob,
           "the OCR reached the reading payload -- it is not the book's text")
        syn = read_root(conn, "سكن")["synonyms"]
        ck(syn["entries"], "an approved Kilani entry did not reach its tab")
        e = syn["entries"][0]
        ck("text" not in e and "headword" not in e,
           "the payload carries text or a headword from an OCR'd source")
        ck(e["scan"] and e["page"],
           "a scan-only entry must carry its page: it IS the citation")
        ck(any(a["ref"] == "20:88" for a in e["ayat"]),
           "the ayah evidence did not survive to the reader")
        # and what IS shown is OUR mushaf, not the scan's rendering of it
        ck(e["ayat"][0]["text"] == aya_text(conn, 20, 88),
           "the ayah shown is not this program's own mushaf text")
    finally:
        with unguarded(conn):
            conn.execute("ROLLBACK TO kil")
            conn.execute("RELEASE kil")
    return "OCR stays in text_norm; the reader gets our mushaf and a page"


@test("HONESTY", "a Kilani root link needs two agreeing facts")
def _t(conn):
    """A headword alone cannot file a page under a root: the OCR corrupts
    headwords too (دَابِر came back دَايِر). So the ayat the page quotes must
    independently contain the root -- and where two roots both pass, nothing
    here can choose, so it refuses."""
    root_ayat = {"جسد": {(20, 88), (21, 8)}, "جسم": {(2, 247), (63, 4)}}
    res = {r: root_search_re(r) for r in root_ayat}
    ck(mutaradifaat_link("جَسَد", {(20, 88)}, root_ayat, res) == "جسد",
       "both facts agreeing did not produce a link")
    # fact 1 without fact 2: the headword proposes, nothing confirms
    ck(mutaradifaat_link("جَسَد", set(), root_ayat, res) is None,
       "a headword alone linked a root -- fact 2 is not being required")
    ck(mutaradifaat_link("جَسَد", {(2, 255)}, root_ayat, res) is None,
       "unrelated ayat confirmed a link")
    # fact 2 without fact 1: the page quotes it, but no headword proposes it
    ck(mutaradifaat_link("قِتَال", {(20, 88)}, root_ayat, res) is None,
       "ayat alone linked a root -- fact 2 cannot GENERATE a hypothesis")
    return "neither fact links a root alone; both must agree"


@test("HONESTY", "a misread page header is derived, never trusted")
def _t(conn):
    """Worse than a header the OCR could not read is one it read WRONG: scan
    411 came back 392 for a page printed 394, and storing that would cite a
    real page of this book that does not contain the entry. The number is
    trusted only where it agrees with the offset."""
    pages = [[411, 392, ["٣- قِتَال: x"]],      # misread
             [400, 383, ["٢- جَسَد: y"]],       # agrees
             [395, None, ["١- رابط: z"]]]       # unread
    got = mutaradifaat_entries(pages)
    ck(len(got) == 3, "entry splitting broke")
    for scan, printed, head, _lines in got:
        derived = scan - MUTARADIFAAT_PAGE_OFFSET
        if scan == 400:
            ck(printed == derived, "an agreeing header should be trusted")
        else:
            ck(printed != derived,
               "this fixture must disagree or it tests nothing")
    ck(411 - MUTARADIFAAT_PAGE_OFFSET == 394,
       "the offset no longer yields the page printed on scan 411")
    return "the offset is the warrant where the header disagrees"


@test("HONESTY", "machine Urdu is never a source and never says it is")
def _t(conn):
    """The owner of this database asked for a machine translation to read
    beside the Arabic, knowing it is not a source. That is a legitimate
    reading aid and a standing hazard: generated prose is least visible
    exactly where it sits next to a scholar's words. So it is kept in its own
    table, its own payload key, its own block outside the card, behind a
    switch that is off, and labelled at every appearance."""
    # it is NOT in entries, and so cannot be reviewed into a source
    cols = {r[1] for r in conn.execute("PRAGMA table_info(glosses)")}
    ck({"engine", "model", "para", "lang"} <= cols,
       "a gloss does not record which machine produced it")
    ck("verified" not in cols,
       "glosses have a review flag -- nobody can vouch for a machine")

    h = READ_HTML
    # the card's border means verbatim-and-cited; the gloss must be OUTSIDE
    ck("'</div></div>'+glossBlock(e)" in h,
       "the gloss is not appended outside the closing card div")
    ck("if(!GLOSS) return \"\";" in h,
       "the gloss renders without the switch being on")
    ck('localStorage.getItem("lughat.gloss")==="1"' in h,
       "the gloss switch does not default to off")
    ck("MACHINE TRANSLATION" in h, "the gloss block carries no label")
    ck("esc(g[i].text)" in h, "gloss text reaches innerHTML unescaped")
    # the label must be inside the block, not once at the top of the page
    blk = h[h.index("function glossBlock("):]
    blk = blk[:blk.index("\n}")]
    ck("MACHINE TRANSLATION" in blk,
       "the label is not emitted with every block")
    # the published translation is a DIFFERENT claim and must not borrow the
    # machine's block, nor the machine the published one's attribution
    qblk = h[h.index("function quotedBlock("):]
    qblk = qblk[:qblk.index("\n}")]
    ck("MACHINE" not in qblk,
       "a named translator's Urdu is labelled as machine output")
    ck("esc(t.author)" in qblk,
       "a published translation is shown without its translator")
    ck("esc(q.ayah)" in qblk,
       "the quoted ayah is not this program's own mushaf text")
    ck("if(!GLOSS)" in qblk, "the quoted block ignores the switch")

    # and the payload keeps it in its own key, never merged into `lines`
    marker = "MACHINE-URDU-MUST-NOT-BE-A-LINE"
    with unguarded(conn):
        conn.execute("SAVEPOINT gl")
        row = conn.execute(
            "SELECT e.id FROM entries e JOIN sources s ON s.id=e.source_id "
            "WHERE e.verified=1 AND s.key IN ('maqayis','lisan','mufradat') "
            "AND e.root_ar='سكن' LIMIT 1").fetchone()
    try:
        if row is None:
            raise Skip("no approved entry on سكن to gloss")
        with unguarded(conn):
            # OR REPLACE: this database may already hold a real gloss for
            # this paragraph, and the test must not depend on it being empty
            conn.execute(
                "INSERT OR REPLACE INTO glosses "
                "(entry_id,para,lang,text,engine,model) "
                "VALUES (?,0,'ur',?,'nllb','600M')", (row["id"], marker))
        data = read_root(conn, "سكن")
        for c in data["cards"]:
            for e in c["entries"]:
                ck(marker not in " ".join(e["lines"]),
                   "machine Urdu was merged into the scholar's own lines")
        found = [g for c in data["cards"] for e in c["entries"]
                 for g in e["gloss"].values() if g["text"] == marker]
        ck(found, "a stored gloss did not reach its own payload key")
        ck(found[0]["engine"] == "nllb", "the engine was not carried through")
        ck("MACHINE TRANSLATION" in data["gloss_note"],
           "the payload does not say what a gloss is")
    finally:
        with unguarded(conn):
            conn.execute("ROLLBACK TO gl")
            conn.execute("RELEASE gl")
    return "own table, own key, own block, off by default, labelled"


@test("HONESTY", "an inferred root is recorded as inferred")
def _t(conn):
    """Two spelling bridges map a heading onto a corpus root. Both are
    inferences and the reviewer must see which is which."""
    corpus = {"ءبب", "دنو", "سكن"}
    ck(resolve_root("سكن", corpus) == ("سكن", "direct"), "direct broke")
    ck(resolve_root("ءب", corpus) == ("ءبب", "geminate"), "geminate broke")
    ck(resolve_root("دني", corpus) == ("دنو", "weak_final"), "weak_final broke")
    ck(resolve_root("زقز", corpus) == ("زقز", "unmatched"), "unmatched broke")
    ck(resolve_root(None, corpus) == (None, "unparsed"), "unparsed broke")
    with unguarded(conn):
        rows = dict(conn.execute("SELECT extraction, COUNT(*) FROM entries "
                                 "GROUP BY extraction"))
    if rows:
        ck("direct" in rows, "no extraction provenance recorded: %s" % rows)
    return "direct / geminate / weak_final / unmatched / unparsed all tagged"


@test("HONESTY", "migration is additive: approved work survives it")
def _t(conn):
    """Bumping the schema must never drop a table that can hold rows a person
    has read and approved."""
    src = own_source()
    body = src[src.index("def migrate("):src.index("def schema_columns_ok")]
    for danger in ("DROP TABLE", "DELETE FROM entries", "DELETE FROM tafsir"):
        ck(danger not in body, "migrate() contains %r" % danger)
    loader = src[src.index("def load("):src.index("def counts(")]
    ck("entries" not in loader.split("DROP TABLE")[-1][:200]
       if "DROP TABLE" in loader else True,
       "the loader drops entries")
    ck(schema_columns_ok(conn), "the live schema is missing a column")
    return "no destructive statement in migrate(); live schema complete"


@test("HONESTY", "the review server is the build path and cannot be the reader's")
def _t(conn):
    """It shows UNVERIFIED text -- that is its job -- so it must be impossible
    to mistake for, or reach, the reading surface."""
    ck(REVIEW_HOST == "127.0.0.1", "the review server binds beyond localhost")
    # Sliced by section banner via source_section(), which handles the
    # self-reference trap described there.
    body = source_section("# 11b." + "  THE REVIEW SERVER",
                          "# 11c." + "  THE READING SURFACE")
    ck(len(body) > 2000, "the review section slice is empty (%d)" % len(body))
    ck("0.0.0.0" not in body, "the handler can bind to a public interface")
    # the routes it exposes are the queue, the stats and the decision. No
    # query-path route may appear, or unverified prose acquires a reader.
    routes = set(re.findall(r'u\.path [!=]= "([^"]+)"', body))
    ck(routes == {"/", "/api/queue", "/api/stats", "/api/decide"},
       "unexpected route(s): %s" % sorted(routes))
    for banned in ("cmd_root", "cmd_word", "cmd_sarf", "cmd_aya"):
        ck(banned not in body, "the review server exposes %s" % banned)
    # strip_comments first: this assertion was previously satisfied by the
    # COMMENT two lines below the call, so replacing the real call with ==
    # still passed. A test that a comment can satisfy is not a test.
    code = strip_comments(body)
    ck("secrets.compare_digest(got, token)" in code,
       "the token check is not a constant-time compare_digest call")
    ck("got == token" not in code, "the token is compared with ==")
    ck("frame-ancestors 'none'" in body, "the review page can be framed")
    return "127.0.0.1 only; 4 routes, none of them a reading route"


@test("HONESTY", "approve, reject and undo do exactly what they say")
def _t(conn):
    # No SAVEPOINT here: _decide() commits, and a commit releases every
    # savepoint, so the rollback would fail. Clean up by deleting instead.
    with unguarded(conn):
        conn.execute("DELETE FROM entries WHERE source_id IN "
                     "(SELECT id FROM sources WHERE key='_rv')")
        conn.execute("DELETE FROM sources WHERE key='_rv'")
        conn.execute("INSERT INTO sources (key,title,kind,attribution) "
                     "VALUES ('_rv','RV','lexicon','RV')")
        sid = conn.execute(
            "SELECT id FROM sources WHERE key='_rv'").fetchone()[0]
        conn.execute("INSERT INTO entries (source_id,root_ar,headword,"
                     "text_raw,vol,page,extraction,verified) "
                     "VALUES (?,?,?,?,?,?,'direct',0)",
                     (sid, "سكن", "(سكن)", "REVIEW LOOP PROSE", "3", "87"))
        eid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    try:
        def served():
            out = io.StringIO()
            real, sys.stdout = sys.stdout, out
            try:
                cmd_root(conn, "سكن")
            finally:
                sys.stdout = real
            return "REVIEW LOOP PROSE" in out.getvalue()

        def queued():
            return eid in [r["id"] for r in _queue_rows(conn, limit=9999)]

        ck(not served() and queued(), "a fresh entry should be queued, unserved")
        _decide(conn, eid, "approve")
        ck(served(), "approve did not make it servable")
        ck(not queued(), "an approved entry is still in the queue")
        with unguarded(conn):
            ck(conn.execute("SELECT verified_at FROM entries WHERE id=?",
                            (eid,)).fetchone()["verified_at"],
               "approve left no audit stamp")
        _decide(conn, eid, "reject", "wrong root")
        ck(not served(), "a rejected entry is still being served")
        ck(not queued(), "a rejected entry returns to the queue forever")
        _decide(conn, eid, "unset")
        ck(not served() and queued(), "undo did not restore the pending state")
        try:
            _decide(conn, eid, "approve_all")
        except ValueError:
            pass
        else:
            raise Fail("_decide accepted an unknown decision")
    finally:
        with unguarded(conn):
            conn.execute("DELETE FROM entries WHERE source_id=?", (sid,))
            conn.execute("DELETE FROM sources WHERE id=?", (sid,))
            conn.commit()
    return "approve serves + stamps; reject unserves + retires; undo restores"


@test("HONESTY", "the queue is ordered by what the reader will actually meet")
def _t(conn):
    """The gate is only honoured if it is bearable. Root frequency in the
    Qur'an is steeply skewed, so offering entries most-frequent-first is what
    makes a few hundred decisions worth more than a few thousand."""
    rows = _queue_rows(conn, limit=40)
    if len(rows) < 5:
        return "queue too short to check ordering"
    freqs = [r["freq"] for r in rows]
    ck(freqs == sorted(freqs, reverse=True),
       "the queue is not frequency-ordered: %s" % freqs[:8])
    ck(freqs[0] > 0, "the head of the queue is a root with no occurrences")
    return "head of queue: %s (%d occurrences)" % (rows[0]["root"], freqs[0])


@test("HONESTY", "a rejected row is unservable structurally, not by convention")
def _t(conn):
    """Every writer today pairs verified and rejected correctly. That is a
    claim about all future writers, so the view enforces it instead."""
    sql = q(conn, "SELECT sql FROM sqlite_master WHERE name='v_entries'"
            ).fetchone()["sql"]
    ck("rejected = 0" in sql.replace("rejected=0", "rejected = 0"),
       "v_entries does not filter rejected: %s" % sql)
    with unguarded(conn):
        conn.execute("DELETE FROM entries WHERE source_id IN "
                     "(SELECT id FROM sources WHERE key='_rj')")
        conn.execute("DELETE FROM sources WHERE key='_rj'")
        conn.execute("INSERT INTO sources (key,title,kind,attribution) "
                     "VALUES ('_rj','RJ','lexicon','RJ')")
        sid = conn.execute(
            "SELECT id FROM sources WHERE key='_rj'").fetchone()[0]
        # the contradictory state, written directly past the API
        conn.execute("INSERT INTO entries (source_id,root_ar,text_raw,vol,"
                     "page,verified,rejected) VALUES (?,?,?,?,?,1,1)",
                     (sid, "سكن", "REJECTED YET VERIFIED", "1", "1"))
        conn.commit()
    try:
        texts = [r["text_raw"] for r in
                 q(conn, "SELECT text_raw FROM v_entries WHERE root_ar=?",
                   ("سكن",))]
        ck("REJECTED YET VERIFIED" not in texts,
           "a row marked both verified and rejected was served")
    finally:
        with unguarded(conn):
            conn.execute("DELETE FROM entries WHERE source_id=?", (sid,))
            conn.execute("DELETE FROM sources WHERE id=?", (sid,))
            conn.commit()
    return "v_entries filters both flags; the (1,1) row stays hidden"


@test("HONESTY", "a scan-only entry can be reviewed, not just stored")
def _t(conn):
    """text_raw is NULL for a scan-only source -- the schema says so and the
    Urdu lexicons will all be like this. The reader path handled it; the
    review path crashed, and ONE such row made the entire queue unreachable,
    including the row itself, which could then never be rejected."""
    with unguarded(conn):
        conn.execute("DELETE FROM entries WHERE source_id IN "
                     "(SELECT id FROM sources WHERE key='_sc')")
        conn.execute("DELETE FROM sources WHERE key='_sc'")
        conn.execute("INSERT INTO sources (key,title,kind,attribution) "
                     "VALUES ('_sc','SCAN','scan','SCAN')")
        sid = conn.execute(
            "SELECT id FROM sources WHERE key='_sc'").fetchone()[0]
        conn.execute("INSERT INTO entries (source_id,root_ar,headword,"
                     "text_raw,scan_uri,vol,page,extraction,verified) "
                     "VALUES (?,?,?,NULL,?,?,?,'direct',0)",
                     (sid, "سكن", "(سكن)", "file:///scan/87.png", "3", "87"))
        conn.commit()
    try:
        rows = _queue_rows(conn, limit=9999)
        mine = [r for r in rows if r["source"] == "SCAN"]
        ck(mine or True, "")
        ck(mine, "the scan-only entry is missing from the queue")
        ck(mine[0]["scan_only"] is True, "not flagged as scan-only")
        ck(any("scan" in l.lower() for l in mine[0]["lines"]),
           "the reviewer is shown nothing about the scan: %s" % mine[0]["lines"])
        # and the whole queue must still work with it present
        ck(len(rows) > 1 or not _INGESTED(conn),
           "one scan-only row emptied the queue")
        out = io.StringIO()
        real, sys.stdout = sys.stdout, out
        try:
            cmd_review(conn, ["--stats"])
        finally:
            sys.stdout = real
        ck("SCAN" in out.getvalue(), "stats do not see the scan source")
    finally:
        with unguarded(conn):
            conn.execute("DELETE FROM entries WHERE source_id=?", (sid,))
            conn.execute("DELETE FROM sources WHERE id=?", (sid,))
            conn.commit()
    return "scan-only rows are reviewable and do not poison the queue"


@test("HONESTY", "an entry with no source row is withheld, not crashed on")
def _t(conn):
    """An entry whose source record is gone has no citation, and an entry
    without a citation is not servable. It must also stay VISIBLE to review,
    or it is counted as pending forever while being unreachable."""
    with unguarded(conn):
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DELETE FROM entries WHERE text_raw='ORPHANED PROSE'")
        conn.execute("INSERT INTO entries (source_id,root_ar,headword,"
                     "text_raw,vol,page,extraction,verified) "
                     "VALUES (999999,?,?,?,?,?,'direct',1)",
                     ("سكن", "(سكن)", "ORPHANED PROSE", "1", "1"))
        eid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")
    try:
        out = io.StringIO()
        real, sys.stdout = sys.stdout, out
        try:
            cmd_root(conn, "سكن")          # must not raise
        finally:
            sys.stdout = real
        ck("ORPHANED PROSE" not in out.getvalue(),
           "an entry with no citation was served")
        ck("withheld" in out.getvalue(), "the reader is not told it exists")
        with unguarded(conn):
            conn.execute("UPDATE entries SET verified=0 WHERE id=?", (eid,))
        ck(eid in [r["id"] for r in _queue_rows(conn, limit=9999)],
           "an orphaned entry is invisible to review but counted as pending")
    finally:
        with unguarded(conn):
            conn.execute("DELETE FROM entries WHERE id=?", (eid,))
            conn.commit()
    return "withheld from the reader, still visible to the reviewer"


@test("HONESTY", "the review page never tells the reviewer a comfortable lie")
def _t(conn):
    """Two client-side defects, both of which destroyed or misreported human
    decisions: Undo reached entries that were no longer on screen, and the
    page announced an empty queue while thousands were pending."""
    h = REVIEW_HTML
    ck("esc(e.freq)" in h, "a field reaches innerHTML without escaping")
    for field in ("e.headword", "e.root", "e.extraction", "e.source",
                  "e.vol", "e.page", "e.freq"):
        ck("esc(%s)" % field in h, "%s is interpolated unescaped" % field)
    # esc() must map all five, and the ENTRY BODY must go through it -- that
    # is the one field carrying untrusted third-party prose, and the earlier
    # version of this test omitted it, so removing esc() from it still passed.
    body = h[h.index("function esc("):h.index("function esc(") + 260]
    for pair in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"):
        ck(pair in body, "esc() does not map %s" % pair)
    ck('e.lines.map(l=>"<p>"+esc(l)+"</p>")' in h,
       "the entry body reaches innerHTML without escaping")
    # Undo must be cleared wherever the visible entry changes
    for site in ("function skip()", "async function load()"):
        seg = h[h.index(site):h.index(site) + 400]
        ck("last=null" in seg, "%s does not clear the undo target" % site)
    # and "empty" must be checked against the server, not assumed
    ck("Fetching the next batch" in h and "if(q.length&&!busy)load();" in h,
       "the page can claim an empty queue without asking the server")
    return "every field escaped; undo scoped to the visible entry; no false empty"


_LISAN_FIXTURE = "\n".join([
    "# سكن",
    "# ] سكن السكون ضد الحركة سكن الشيء يسكن سكونا",
    "~~إذا ذهبت حركته",
    "PageV13P210",
    "# سلم",
    "# ] سلم : السلام من أسماء الله عز وجل",
    "# الليث",
    "# و الخلب حبل دقيق -- a bare head with no confirming line",
])


@test("HONESTY", "each lexicon is read by its own rules, not one guess")
def _t(conn):
    """Three sources, three entry conventions. Maqayis marks entries with
    parentheses because its digitisation inserts headers mid-word; Mufradat
    has bare headings; Lisan has no ### markers at all and instead names each
    root TWICE, which is a stronger guard than either."""
    for key in ("maqayis", "mufradat", "lisan"):
        spec = LEXICONS[key]
        for field in ("title", "author", "attribution", "licence", "detect",
                      "ordered_by"):
            ck(spec.get(field), "%s has no %s" % (key, field))
    # Lisan: the two namings must AGREE, and a lone head is not an entry
    got = list(parse_lexicon(_LISAN_FIXTURE, {"سكن", "سلم"},
                             LEXICONS["lisan"]))
    ck([e["root_ar"] for e in got] == ["سكن", "سلم"],
       "Lisan parsed %s" % [e["root_ar"] for e in got])
    ck(all("الليث" not in "".join(e["lines"]) or e["root_ar"] == "سلم"
           for e in got), "an unconfirmed bare head became an entry")
    # the confirming line's colon is optional -- requiring it dropped 827
    # entries from the real text, سكن among them
    ck(_LISAN_CONFIRM.match("# ] سكن السكون ضد الحركة"),
       "the confirmation rule still demands a colon")
    ck(_LISAN_CONFIRM.match("# ] . صقب : الصقب"),
       "a leading stop defeats the confirmation rule")
    ck(not _LISAN_CONFIRM.match("# و الخلب حبل"), "confirmation is too loose")
    return "3 lexicons, 3 entry rules; Lisan requires the root twice"


@test("HONESTY", "a source is checked against its OWN ordering scheme")
def _t(conn):
    """Lisan and al-Qamus order by the LAST radical. Checking them against
    first-radical order would flag the entire book, and a warning that cries
    wolf is worse than none -- the reviewer learns to ignore the badge."""
    ck(LEXICONS["lisan"]["ordered_by"] == "last", "Lisan is checked wrongly")
    ck(LEXICONS["maqayis"]["ordered_by"] == "first", "Maqayis checked wrongly")

    # Exercised against a FIXTURE, not against flags left in the database by
    # an earlier ingest: reading stored rows let the whole flagging branch be
    # deleted with the test still passing.
    # The real case: Lisan's bab boundary. Last radical goes م -> ن, which is
    # ascending and correct. First radical goes ي -> ء, which looks like a
    # regression and would flag the book at every bab if checked that way.
    lisan_ok = "\n".join([
        "# يتم", "# ] يتم : باب الميم فصل الياء",
        "# أبن", "# ] أبن : باب النون فصل الهمزة",
    ])
    got = list(parse_lexicon(lisan_ok, set(), LEXICONS["lisan"]))
    ck(len(got) == 2, "fixture parsed %d entries" % len(got))
    ck(not any(e["flags"] for e in got),
       "last-radical order flagged a correctly ordered Lisan run: %s"
       % [(e["headword"], e["flags"]) for e in got])
    # the same run judged by FIRST radical would flag it -- which is the bug
    first_spec = dict(LEXICONS["lisan"], ordered_by="first")
    wrong = list(parse_lexicon(lisan_ok, set(), first_spec))
    ck(any(e["flags"] for e in wrong),
       "the ordering check does not depend on ordered_by at all")
    # and a genuine regression must be caught
    lisan_bad = "\n".join([
        "# شتم", "# ] شتم : باب الميم",
        "# سلب", "# ] سلب : باب الباء -- backwards",
    ])
    bad = list(parse_lexicon(lisan_bad, set(), LEXICONS["lisan"]))
    ck(any(e["flags"] for e in bad), "a backwards heading was not flagged")

    with unguarded(conn):
        rows = dict(conn.execute(
            "SELECT s.key, COUNT(*) FROM entries e JOIN sources s "
            "ON s.id=e.source_id WHERE e.flags IS NOT NULL GROUP BY s.key"))
        tot = dict(conn.execute(
            "SELECT s.key, COUNT(*) FROM entries e JOIN sources s "
            "ON s.id=e.source_id GROUP BY s.key"))
    for key, n in rows.items():
        share = 100.0 * n / max(1, tot.get(key, 1))
        ck(share < 10, "%s flags %.0f%% of its entries -- the check is wrong "
                       "for this source, not the source" % (key, share))
    return "flagged: %s of %s" % (rows or "none", tot or "none")


@test("HONESTY", "re-ingesting does not discard review work")
def _t(conn):
    """Ingest is re-runnable. If it wiped the table it would destroy every
    decision a person had made, which is the one thing the gate exists to
    accumulate."""
    src = own_source()
    marker = "def " + "ingest_lexicon(conn, key, path):"
    body = src[src.rindex(marker):src.rindex("def " + "ingest_maqayis")]
    flat = " ".join(body.split())
    # the SQL is split across adjacent string literals, so the quote marks
    # survive a whitespace flatten -- strip them before matching
    sql = flat.replace('" "', "").replace('"', "")
    ck("DELETE FROM entries WHERE source_id=? AND verified=0 AND rejected=0"
       in sql, "ingest deletes rows regardless of review state")
    ck("DELETE FROM entries WHERE source_id=?," not in sql,
       "ingest has an unconditional delete of a source's entries")
    with unguarded(conn):
        n_decided = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE verified=1 OR rejected=1"
        ).fetchone()[0]
    return "ingest deletes only undecided rows (%d decided today)" % n_decided


@test("HONESTY", "the reader announces held-back entries even when it has some")
def _t(conn):
    """Showing one lexicon while silently holding another is a lie by
    omission: the reader takes what they see for everything there is."""
    out = io.StringIO()
    real, sys.stdout = sys.stdout, out
    try:
        cmd_root(conn, "سكن")
    finally:
        sys.stdout = real
    body = out.getvalue()
    with unguarded(conn):
        pend = conn.execute("SELECT COUNT(*) FROM entries WHERE root_ar='سكن' "
                            "AND verified=0 AND rejected=0").fetchone()[0]
        appr = conn.execute("SELECT COUNT(*) FROM entries WHERE root_ar='سكن' "
                            "AND verified=1 AND rejected=0").fetchone()[0]
    if pend and appr:
        ck("NOT APPROVED" in body,
           "entries are held back and the reader is not told")
    if appr:
        ck("vol" in body, "an approved entry is shown without its citation")
    return "%d approved shown, %d pending announced" % (appr, pend)


@test("HONESTY", "the digitisation's own marks do not destroy a heading")
def _t(conn):
    """render_entry strips ms#### and PageV##P###; the heading detectors did
    not. So "### | (نهي) ms1086" was not a heading, and Ibn Faris's article on
    نهي was dropped while (حول) ms0282 folded into the entry for حوك. Stray
    brackets the digitiser left inside the parentheses -- "( [بقر)" -- cost
    four more, بقر among them."""
    for raw, want in ((" (نهي) ms1086", "نهي"), ("(حول) ms0282", "حول"),
                      ("( [بقر)", "بقر"), ("(سكن)", "سكن")):
        ck(heading_root_parenthesised(raw) == want,
           "%r -> %r, want %r" % (raw, heading_root_parenthesised(raw), want))
    for raw, want in (("نور ms629", "نور"), ("روح ms265", "روح"),
                      ("سكن", "سكن")):
        ck(heading_root_bare(raw) == want,
           "%r -> %r, want %r" % (raw, heading_root_bare(raw), want))
    ck(heading_root_parenthesised("باب الهمزة") is None, "a title became a root")
    need_source(conn, "maqayis")
    need_source(conn, "mufradat")
    with unguarded(conn):
        for key, root in (("maqayis", "بقر"), ("maqayis", "حول"),
                          ("maqayis", "نهي"), ("mufradat", "نور"),
                          ("mufradat", "روح")):
            n = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE root_ar=? AND source_id="
                "(SELECT id FROM sources WHERE key=?)", (root, key)).fetchone()[0]
            ck(n, "%s has no entry for %s" % (key, root))
    return "ms####, PageV and stray brackets no longer eat a heading"


@test("HONESTY", "a page marker closes the page it names")
def _t(conn):
    """Every one of these files ends with its final words followed inline by
    the last marker, and the Shamela ones open with a PageV00P000 sentinel.
    Taking the PREVIOUS marker put all 15,500 citations one page too low, and
    at a volume boundary in the wrong volume as well. A wrong page is a wrong
    citation."""
    fixture = "\n".join([
        "PageV01P006",
        "### | (أت) ",
        "# الهمزة والتاء أصل",
        "PageV01P007",
        "### | (أث) ",
        "# الهمزة والثاء",
        "PageV02P003",
    ])
    got = {e["headword"]: (e["vol"], e["page"])
           for e in parse_lexicon(fixture, set(), LEXICONS["maqayis"])}
    ck(got["(أت)"] == (1, 7), "(أت) cited at %s, want vol 1 p 7" % (got["(أت)"],))
    ck(got["(أث)"] == (2, 3),
       "(أث) cited at %s -- a volume boundary must take the NEXT marker's "
       "volume, not the previous volume's last page" % (got["(أث)"],))
    return "entry cited to the page its text closes on, volume included"


@test("HONESTY", "only a letter can be a radical")
def _t(conn):
    """canonical_root promises to RAISE on anything that cannot be a radical.
    The Arabic block also holds punctuation and digits, and it was passing
    them through: three entries were filed under roots like صور، ."""
    for bad in ("صور،", "ص٣ر", "سكن؟", "س٫ن"):
        try:
            got = canonical_root(bad)
        except (ValueError, TransliterationError):
            continue
        raise Fail("canonical_root(%r) returned %r instead of raising"
                   % (bad, got))
    ck(canonical_root("سكن") == ["س", "ك", "ن"], "a real root broke")
    ck(canonical_root("رمى") == ["ر", "م", "ي"], "alef maksura fold broke")
    with unguarded(conn):
        n = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE root_ar GLOB "
            "'*[^ءابتثجحخدذرزسشصضطظعغفقكلمنهوي]*'").fetchone()[0]
    ck(n == 0, "%d entries are filed under a root containing a non-letter" % n)
    return "punctuation and digits rejected; 0 non-letter roots stored"


@test("HONESTY", "an unconfirmable heading is a boundary, not more body text")
def _t(conn):
    """In Lisan a head that cannot be confirmed used to flow onward, so its
    article landed under the PREVIOUS root: 34,017 bytes misfiled, one entry
    being 99% Ibn Manzur on سفه while labelled سده."""
    fixture = "\n".join([
        "# سده", "# ] سده : السده شبيه بالدهش",
        "# سفه", "# ] ( 3 ) سفه : السفه خفة الحلم",
        "# نجم", "# ] something else entirely, not a confirmation",
        "# طرق", "# ] طرق : الطريق",
    ])
    got = list(parse_lexicon(fixture, {"سده", "سفه", "طرق"},
                             LEXICONS["lisan"]))
    roots = [e["root_ar"] for e in got]
    ck("سفه" in roots, "a '( 3 )' prefix still defeats confirmation: %s" % roots)
    sade = [e for e in got if e["root_ar"] == "سده"][0]
    ck("السفه" not in "\n".join(sade["lines"]),
       "سده swallowed the article on سفه")
    ck("نجم" not in roots, "an unconfirmed head became an entry")
    safa = [e for e in got if e["root_ar"] == "سفه"][0]
    ck("not a confirmation" not in "\n".join(safa["lines"]),
       "an unconfirmed head's text flowed into the entry ABOVE it -- which is "
       "the direction that misfiled 34,017 bytes")
    # and a head too long to be a root must not flow onward either --
    # استبرق, زنجبيل, ميكائيل are Lisan headwords, and 16 articles ended up
    # under a neighbour because canonical_root rejected the head as too long.
    long_fix = "\n".join([
        "# ءسق", "# ] أسق : شيء",
        "# استبرق", "# ] استبرق : قال الزجاج",
    ])
    lg = list(parse_lexicon(long_fix, {"ءسق"}, LEXICONS["lisan"]))
    first = [e for e in lg if e["root_ar"] == "ءسق"][0]
    ck("الزجاج" not in "\n".join(first["lines"]),
       "a too-long head was swallowed by the entry above it")
    ck(any(e["headword"] == "استبرق" for e in lg),
       "the too-long headword's article was dropped entirely")
    unconf = list(parse_lexicon("\n".join([
        "# ءسق", "# ] أسق : شيء",
        "# منجنون", "# ] no confirmation here at all",
    ]), {"ءسق"}, LEXICONS["lisan"]))
    ck("no confirmation" not in "\n".join(
        [l for e in unconf if e["root_ar"] == "ءسق" for l in e["lines"]]),
       "an unconfirmed too-long head flowed into the entry above it")
    tail = [e for e in got if e["root_ar"] == "طرق"]
    ck(tail, "the entry after an unconfirmed head was lost")
    ck("not a confirmation" not in "\n".join(tail[0]["lines"]),
       "the unconfirmed head's text flowed into the NEXT entry instead")
    return "confirmed heads only; an unconfirmable one closes the entry"


@test("HONESTY", "rejoining a split word does not invent a space")
def _t(conn):
    """CLAUDE.md: rejoined using exactly the whitespace the source itself has.
    When the cut fell between the previous line and the header, a space was
    inserted anyway and broke 277 words -- واحد rendered as 'و احد'."""
    raw = "\n".join(["# وهو أصل و", "### | اح", "# د. قال ابن دريد"])
    shown = " ".join(render_entry(raw))
    ck("واحد" in shown, "the split word was not rejoined: %r" % shown)
    ck("و احد" not in shown, "a space was invented inside the word: %r" % shown)
    # and a source-supplied space must survive
    raw2 = "\n".join(["# قال", "### | إن ", "# إلك في قريش"])
    ck("إن إلك" in " ".join(render_entry(raw2)),
       "a space the source DID write was dropped")
    return "و+اح+د -> واحد; 'إن ' + 'إلك' -> إن إلك"


_PASSAGE_FIXTURE = "\n".join([
    "# وهذا باب من العربية",
    "~~يقال في جمع مسكين مساكين وهو مما جاء على مفاعيل",
    "PageV01P010",
    "# وقالوا اجتمع القوم اجتماعا",
    "PageV01P011",
])


_TAFSIR_FIXTURE = "\n".join([
    "### | سورة الكوثر",
    "### || ",
    "# {إنا أعطيناك الكوثر (1) فصل لربك وانحر (2) } .",
    "~~قال المفسرون في الكوثر أقوالا",
    "PageV05P310",
    "# وقال بعضهم غير ذلك",
    "PageV05P311",
    "### || ",
    "# {إن شانئك هو الأبتر (9) } .",
    "~~هذا التعليق مرقم برقم لا يوافق المصحف",
    "PageV05P312",
    "### || ",
    "# كلام بلا آية مقتبسة بين قوسين",
    "PageV05P313",
])


@test("HONESTY", "an opposite is quoted from a lexicographer, never derived")
def _t(conn):
    """No source loaded here is a dictionary of antonyms, so the tool states
    that and shows the SENTENCE in which a lexicographer states an opposition
    -- `يدل على خلاف الاضطراب والحركة` -- with its page. Which word is the
    opposite is the reader's inference on the scholar's sentence, not the
    program's on the reader's behalf."""
    ck(REFUSAL_ANTONYM.startswith("REFUSED"),
       "the tool does not refuse to derive an opposite")
    # An excerpt must be one contiguous run of the source's own characters.
    # Slicing with offsets taken from a DIFFERENT string turned
    # `السكون ضد الحركة` into `ضد لحركة` -- a word of Ibn Manzur's, corrupted
    # by one character, in a card carrying his name.
    long_sent = ("سكن السكون ضد الحركة " + "و" * 0 +
                 " ".join("كلمة%d" % i for i in range(60)))
    padded = " " + long_sent + " "
    m = _OPP_RE.search(padded)
    ck(m is not None, "the opposition rule does not match ضد")
    got = _opposition_window(padded, m)
    core = got.strip("\u2026 ").strip()
    ck(core in long_sent, "the excerpt is not a run of the source: %r" % core)
    ck("ضد الحركة" in core, "the excerpt dropped a letter: %r" % core[:60])
    ck(got != long_sent and got.endswith("\u2026"),
       "a long article was quoted whole instead of excerpted")
    data = read_root(conn, "سكن")
    opp = data["opposites"]
    ck(opp["refusal"] is REFUSAL_ANTONYM or
       opp["refusal"] == REFUSAL_ANTONYM, "the page drops the refusal")
    for hit in opp["hits"]:
        # every hit is a substring of the source's OWN rendered text
        with unguarded(conn):
            rows = conn.execute(
                "SELECT text_raw FROM entries WHERE root_ar='سكن' AND "
                "verified=1").fetchall()
        blob = " ".join(" ".join(render_entry(r[0] or "")) for r in rows)
        ck(hit["text"] in blob,
           "an 'opposition' sentence is not in any approved article: %r"
           % hit["text"][:60])
        ck(hit["word"] in OPPOSITION_WORDS or
           any(w in hit["word"] for w in OPPOSITION_WORDS),
           "matched on %r, which is not an opposition word" % hit["word"])
        ck(hit["vol"] and hit["page"], "an opposition sentence is uncited")
        # and no field names the opposite: that would be the tool parsing
        # what a lexicographer meant
        ck(set(hit) == {"text", "word", "title", "author", "vol", "page",
                        "attribution"},
           "the payload grew a field beyond the quoted sentence: %s"
           % sorted(hit))
    # al-'Askari is reported as a chapter he WROTE, not as a synonym claim
    blob = json.dumps(data["furuq"], ensure_ascii=False)
    for claim in ("synonym", "means the same", "equivalent"):
        ck(claim not in blob.lower(),
           "the payload asserts synonymy: %r" % claim)
    return "%d opposition sentences, each quoted whole and cited" % len(
        opp["hits"])


@test("HONESTY", "a translation is a translator's, and never this tool's")
def _t(conn):
    """The one place generated prose would be least visible is beside a
    scholar's text in another language. So every translated string served
    here is one published translator's line, whole, carrying his name."""
    ck(REFUSAL_TRANSLATE_MYSELF.startswith("REFUSED"),
       "the tool does not refuse to translate")
    for key, spec in TRANSLATIONS.items():
        ck(spec["author"] and spec["title"],
           "%s is installable without naming a translator" % key)
    # no rendering may be composed here: the only writer of translations.text
    # is the ingest, and it inserts the file's own line
    src = strip_comments(own_source())
    needle = "INSERT INTO " + "translations"
    writes = re.findall(needle + r"[^\"]*", src)
    ck(len(writes) == 1, "translations is written from %d places" % len(writes))
    # and the reader is told, on the page, that the tool did not translate
    data = read_root(conn, "سكن")
    ck(data["translate_refusal"].startswith("REFUSED"),
       "the page does not carry the refusal to translate")
    return "%d translations installable, each named; the tool refuses to " \
           "translate" % len(TRANSLATIONS)


@test("HONESTY", "a translation numbered unlike the mushaf is refused whole")
def _t(conn):
    """Some editions count the basmala as an ayah. A single offset would put
    one verse's words under another verse -- the tafsir anchoring failure
    arriving by a different road -- and it would be invisible, because every
    line would still look like a translation of something."""
    import tempfile
    good = "\n".join("%d|%d|X" % (s, a) for s, a in sorted(
        {(r["sura"], r["aya"]) for r in q(
            conn, "SELECT DISTINCT sura, aya FROM words")}))
    rows = list(parse_translation(good))
    ck(len(rows) == 6236, "the fixture has %d ayat" % len(rows))
    ck(rows[0][:2] == (1, 1) and rows[-1][:2] == (114, 6),
       "the fixture does not span the mushaf: %r .. %r" % (rows[0], rows[-1]))
    for bad, why in ((good + "\n1|8|X", "an ayah the mushaf does not have"),
                     ("\n".join(good.split("\n")[:-1]), "a missing ayah")):
        fh = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                         encoding="utf-8")
        fh.write(bad)
        fh.close()
        try:
            ingest_translation(conn, "ur.jalandhry", path=fh.name)
            ck(False, "%s was ingested anyway" % why)
        except SystemExit as e:
            ck("REFUSED" in str(e), "%s was rejected without saying why" % why)
        finally:
            os.unlink(fh.name)
    # the text itself is copied, not touched
    line = "2|35|" + "اور ہم  نے"
    got = list(parse_translation(line))
    ck(got and got[0][2] == "اور ہم  نے",
       "the translation line was altered on the way in: %r" % (got,))
    return "6,236 required and checked; an extra or missing ayah refuses"


@test("HONESTY", "a tafsir passage is anchored by the mushaf, or dropped")
def _t(conn):
    """The worst thing this layer can do is file al-Baghawi's comment on one
    verse under another verse, with his name and a page on it. So an anchor
    is accepted only when the mushaf and the book's own numbering AGREE, and
    a pericope that cannot be anchored is not ingested at all -- an unanchored
    comment is a comment about nothing."""
    idx, n_ayat = ayah_index(conn)
    spec = dict(TAFASIR["baghawi"], _refused=[])
    got = list(parse_tafsir(_TAFSIR_FIXTURE, idx, n_ayat, spec))
    ck(len(got) == 1, "%d pericopes anchored, expected 1" % len(got))
    pc = got[0]
    ck((pc["sura"], pc["aya_from"], pc["aya_to"]) == (108, 1, 2),
       "anchored to %s:%s-%s" % (pc["sura"], pc["aya_from"], pc["aya_to"]))
    ck("108:1" in pc["evidence"] and "108:2" in pc["evidence"],
       "the anchor's evidence is not recorded: %r" % pc["evidence"])
    # the citation is where the passage BEGINS, and where it ends is kept too
    ck((pc["vol"], pc["page"], pc["page_to"]) == ("5", "310", "311"),
       "cited to vol %s p. %s-%s" % (pc["vol"], pc["page"], pc["page_to"]))
    # and the two that could not be anchored say why, in the source's terms
    ck(len(spec["_refused"]) == 2,
       "refused %r" % (spec["_refused"],))
    why = " | ".join(spec["_refused"])
    ck("108:3" in why and "9" in why,
       "the number/text disagreement is not explained: %s" % why)
    ck("braces" in why, "a pericope with no quotation is not explained: %s"
       % why)
    # the disagreeing pericope must not have been ingested under 108:9 or 108:3
    ck(all(p["aya_from"] != 3 for p in got), "a disagreeing anchor was kept")
    # the fold is loose on purpose, so its two safety conditions are checked
    # here rather than asserted in a comment
    ck(mushaf_key("وأقيموا الصلاة وآتوا الزكاة") ==
       mushaf_key("وَأَقِيمُوا۟ ٱلصَّلَوٰةَ وَءَاتُوا۟ ٱلزَّكَوٰةَ"),
       "the fold does not reconcile the printed الصلاة with the mushaf's صلوة")
    # (1) an anchor is only ever taken from a key that is UNIQUE in the
    # mushaf, so a repeated ayah anchors nothing rather than the wrong thing
    repeated = mushaf_key("فبأي آلاء ربكما تكذبان")
    ck(len(idx.get(repeated, [])) > 1,
       "55:13 is not repeated in the index; the test is not exercised")
    dup = "\n".join(["### || ", "# {فبأي آلاء ربكما تكذبان (13) } .",
                      "~~كلام", "PageV05P400"])
    spec2 = dict(TAFASIR["baghawi"], _refused=[])
    ck(not list(parse_tafsir(dup, idx, n_ayat, spec2)),
       "a quotation that occurs 31 times in the mushaf was used as an anchor")
    # (2) the key is a COMPARISON key, like norm_alif -- never displayed
    reading = source_section("# 11c." + "  THE READING SURFACE",
                             "# 12." + "  CLI")
    ck("mushaf_key" not in strip_comments(reading),
       "the reading surface displays a comparison key")
    return "1 anchored on 2 agreements; 2 refused; repeated ayah refused"


@test("HONESTY", "an ingested tafsir passage is not served until approved")
def _t(conn):
    # NOT a SAVEPOINT: this test calls _decide(), which commits -- and a
    # commit releases every savepoint, so the fixture would survive the test
    # and the next run would trip over its own leftovers. The rows are
    # deleted by hand instead.
    with unguarded(conn):
        conn.execute("DELETE FROM tafsir WHERE source_id IN "
                     "(SELECT id FROM sources WHERE key='_taf')")
        conn.execute("DELETE FROM sources WHERE key='_taf'")
        conn.execute("INSERT INTO sources (key,title,kind,attribution) "
                     "VALUES ('_taf','TAF','tafsir','TAF ATTRIB')")
        sid = conn.execute(
            "SELECT id FROM sources WHERE key='_taf'").fetchone()[0]
        conn.execute(
            "INSERT INTO tafsir (source_id,sura,aya,aya_to,text_raw,vol,page,"
            "anchor_method,anchor_evidence,verified) VALUES "
            "(?,108,1,2,'# PENDING COMMENTARY','5','310','mushaf-quotation',"
            "'text and number agree at 108:1',0)", (sid,))
        tid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    try:
        ck(not tafsir_for_aya(conn, 108, 2), "an unapproved passage was served")
        out = io.StringIO()
        real, sys.stdout = sys.stdout, out
        try:
            cmd_tafsir(conn, "108:2")
        finally:
            sys.stdout = real
        ck("PENDING COMMENTARY" not in out.getvalue(),
           "an unapproved passage was printed")
        ck("NOT APPROVED" in out.getvalue(),
           "the reader is not told that pending commentary exists")
        _decide(conn, tid, "approve", table="tafsir")
        rows = tafsir_for_aya(conn, 108, 2)
        ck(len(rows) == 1, "approving did not make the passage servable")
        ck(rows[0]["aya"] == 1 and rows[0]["aya_to"] == 2,
           "a pericope covering 108:1-2 was not found from ayah 2")
        with unguarded(conn):
            r = conn.execute("SELECT verified_at FROM tafsir WHERE id=?",
                             (tid,)).fetchone()
        ck(r["verified_at"], "approval left no audit stamp")
    finally:
        with unguarded(conn):
            conn.execute("DELETE FROM tafsir WHERE source_id IN "
                         "(SELECT id FROM sources WHERE key='_taf')")
            conn.execute("DELETE FROM sources WHERE key='_taf'")
            conn.commit()
    return "pending hidden but announced; approved served by range; stamped"


@test("INTEGRITY", "no HTML entity is written into a text node")
def _t(conn):
    """textContent does not decode entities, so `&middot;` set that way
    reaches the reader as five literal characters. It did, in the review
    footer, and no API test could see it -- the payload was correct and the
    page was wrong."""
    bad = []
    for page in ("REVIEW_HTML", "READ_HTML"):
        html = globals()[page]
        for m in re.finditer(r"textContent\s*=(.*?);\s*\n", html, re.S):
            if re.search(r"&[a-zA-Z]+;|&#\d+;", m.group(1)):
                bad.append((page, " ".join(m.group(1).split())[:60]))
    ck(not bad, "an HTML entity is assigned to textContent: %s" % bad)
    return "%d text-node assignments, none carrying an entity" % sum(
        len(re.findall(r"textContent\s*=", globals()[p]))
        for p in ("REVIEW_HTML", "READ_HTML"))


@test("INTEGRITY", "the guard is dropped by a callback, never by None")
def _t(conn):
    """set_authorizer(None) removes the authorizer on Python 3.11+ and does
    NOT on 3.10 and earlier -- there it stores None, every authorization
    request then fails, and SQLite is told DENY. The program died with
    `not authorized` while counting rows in sqlite_master, on a Mac, on the
    first command a person ran. This build was developed on 3.11, so no test
    that merely EXERCISES the code can catch it; the check has to be on the
    call itself."""
    # Matched on the CALL, not on the text: this file has to be able to
    # discuss the bug in a docstring without the test finding its own needle.
    src = strip_comments(own_source())
    args = re.findall(r"conn\.set_authorizer\(([A-Za-z_][A-Za-z_0-9]*)\)",
                      src)
    ck(args, "no set_authorizer call found at all; has the guard gone?")
    ck("None" not in args,
       "set_authorizer(None) is back; it denies everything below Python 3.11")
    ck(_permit_all(sqlite3.SQLITE_READ, "entries", "text_raw", "main", None)
       == sqlite3.SQLITE_OK, "the build path's authorizer does not permit")
    # and the guard must still be armed on the way out
    with unguarded(conn):
        conn.execute("SELECT COUNT(*) FROM entries").fetchone()
    try:
        q(conn, "SELECT COUNT(*) FROM entries").fetchone()
        ck(False, "the guard was not re-armed after unguarded()")
    except UnverifiedAccess:
        pass
    return "a permissive callback, not None; guard re-armed after"


@test("HONESTY", "the review gate writes only to the two reviewable tables")
def _t(conn):
    """A table name cannot be a bound parameter, so the queue interpolates one.
    Every such interpolation goes through _table(), which is a whitelist --
    otherwise the decide route would take a table name from an HTTP request."""
    ck(REVIEWABLE == ("entries", "tafsir"), "the whitelist changed: %r"
       % (REVIEWABLE,))
    for bad in ("sources", "roots", "sqlite_master", "entries; DROP"):
        try:
            _table(bad)
            ck(False, "_table accepted %r" % bad)
        except ValueError:
            pass
        for fn in (lambda: _decide(conn, 1, "approve", table=bad),
                   lambda: _queue_stats(conn, table=bad),
                   lambda: _queue_rows(conn, table=bad)):
            try:
                fn()
                ck(False, "a queue function accepted table=%r" % bad)
            except ValueError:
                pass
    # and no interpolation may reach SQL without passing through _table()
    body = strip_comments(source_section(
        "# 11b." + "  THE REVIEW SERVER", "# 11c." + "  THE READING SURFACE"))
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if "UPDATE %s" in line or "FROM %s" in line:
            window = " ".join(lines[max(0, i - 4):i + 5])
            ck("tbl" in window or "_table(" in window,
               "a table is interpolated without the whitelist: %s"
               % line.strip()[:70])
    return "2 tables whitelisted; 4 bad names refused on 3 entry points"


@test("HONESTY", "a book not keyed by root is searched, never quoted at it")
def _t(conn):
    """al-Khasa'is is arranged by topic and Sirr by letter. Neither has an
    article on س ك ن, so the tool must not present one -- and must not print
    an empty card saying "no entry for this root" either, which reads as a
    claim about the book's contents rather than its organisation."""
    ck(not root_keyed("khasais") and not root_keyed("sirr"),
       "a book organised by topic or letter is being treated as root-keyed")
    with unguarded(conn):
        conn.execute("SAVEPOINT pas")
        conn.execute("INSERT INTO sources (key,title,kind,attribution) "
                     "VALUES ('khasais_t','KT','lexicon','KT ATTRIB')")
        sid = conn.execute(
            "SELECT id FROM sources WHERE key='khasais_t'").fetchone()[0]
        for verified in (0, 1):
            conn.execute(
                "INSERT INTO entries (source_id,root_ar,headword,text_raw,"
                "vol,page,extraction,verified) VALUES (?,NULL,?,?,'1','9',"
                "'direct',?)", (sid, "باب", _PASSAGE_FIXTURE, verified))
    try:
        LEXICONS["khasais_t"] = {"keyed_by": "chapter"}
        hits, more, pending = passage_search(conn, "khasais_t", "سكن")
        ck(len(hits) == 1, "%d hits, expected exactly one (the approved row "
                           "matched once; the pending row must not be read)"
           % len(hits))
        ck(pending == 1, "the unsearched pending chapter was not counted")
        h = hits[0]
        ck("مساكين" in h["text"], "the passage itself was not returned")
        ck("PageV" not in h["text"] and "~~" not in h["text"],
           "the passage leaked digitisation markup")
        ck(chapter_label("|| AUTO حرف السين") == "حرف السين",
           "OpenITI's own AUTO marker is shown as if it were a chapter title")
        with unguarded(conn):
            kept = conn.execute("SELECT headword FROM entries WHERE "
                                "source_id=? LIMIT 1", (sid,)).fetchone()[0]
        ck(kept == "باب", "cleaning the label changed the stored headword")
        # trap 15 on a PASSAGE: the marker CLOSES the page it names, so the
        # block that ends before PageV01P010 is ON page 10, not page 9.
        ck((h["vol"], h["page"]) == ("1", "10"),
           "passage cited to vol %s p. %s; the closing marker says 1/10"
           % (h["vol"], h["page"]))
        # and the search must not reach the unapproved chapter
        with unguarded(conn):
            conn.execute("UPDATE entries SET verified=0 WHERE source_id=?",
                         (sid,))
        ck(not passage_search(conn, "khasais_t", "سكن")[0],
           "an unapproved chapter was searched")
    finally:
        LEXICONS.pop("khasais_t", None)
        with unguarded(conn):
            conn.execute("ROLLBACK TO pas")
            conn.execute("RELEASE pas")
    return "searched, page resolved by the closing marker, pending untouched"


@test("HONESTY", "the string search states what it misses, and it is true")
def _t(conn):
    """A stated limit that the code does not actually have is worse than no
    statement: the reader calibrates on it. So the two failures the prose
    admits to are exercised here against the regex itself."""
    rx = lambda root, word: bool(root_search_re(root).search(norm_alif(word)))
    ck(rx("سكن", "مساكين") and rx("سكن", "تسكين") and rx("سكن", "ساكن"),
       "the rule does not find the forms it claims to")
    # the two admitted failures, in the same order the prose admits them
    ck(not rx("جمع", "اجتمع"), "form VIII is found after all; fix the prose")
    ck(not rx("قول", "قال"), "i'lal is found after all; fix the prose")
    ck(rx("سلم", "سليمان"), "the overmatch is gone; fix the prose")
    ck(rx("مدد", "مد"), "idgham writes the doubled radical once")
    for needle in ("STRING SEARCH", "اجتمع", "قال", "سليمان"):
        ck(needle in SEARCH_IS_A_STRING_SEARCH,
           "the notice does not mention %s" % needle)
    ck("REFUSED" in REFUSAL_NOT_KEYED_BY_ROOT,
       "a book with no article on the root does not refuse")
    return "3 forms found, form VIII and i'lal missed, سليمان overmatched -- as stated"


@test("HONESTY", "ishtiqaq akbar lists, and refuses to interpret")
def _t(conn):
    """Listing the six permutations is arithmetic and saying which occur is a
    lookup. Claiming they share a sense is Ibn Jinni's THESIS -- not derivable
    from the letters, and a minority method besides."""
    perms = permutations_of("سكن")
    ck(sorted(perms) == sorted(["سكن", "سنك", "كسن", "كنس", "نسك", "نكس"]),
       "permutations wrong: %s" % perms)
    ck(len(permutations_of("مدد")) == 3,
       "a repeated radical must yield fewer than six -- that is arithmetic")
    got = {p.root: p for p in ishtiqaq_akbar(conn, "سكن")}
    for root in ("سكن", "كنس", "نسك", "نكس"):
        n = q(conn, "SELECT n_segments FROM roots WHERE root_ar=?",
              (root,)).fetchone()
        ck(got[root].n_segments == n["n_segments"],
           "%s counted %d, corpus says %d"
           % (root, got[root].n_segments, n["n_segments"]))
    for root in ("سنك", "كسن"):
        ck(not got[root].occurs, "%s should not occur" % root)
    # Captured SEPARATELY: sharing one buffer let the quadriliteral's refusal
    # satisfy the assertion meant for the shared-sense refusal.
    def render(root):
        out = io.StringIO()
        real, sys.stdout = sys.stdout, out
        try:
            cmd_akbar(conn, root)
        finally:
            sys.stdout = real
        return out.getvalue()

    body = render("سكن")
    quad = render("دحرج")
    ck("REFUSED" in quad and "thulathi" in quad.lower(),
       "a quadriliteral was not refused: akbar is stated for three radicals")
    ck("REFUSED" in body and "THESIS" in body,
       "the shared-sense claim is not refused")
    # asserted on the constant, and on a single word surviving the wrap:
    # a phrase check would break the moment the line width changed
    ck("minority method" in REFUSAL_AKBAR_SENSE,
       "the refusal no longer says the method is a minority one")
    ck("Ibn Faris and al-Raghib" in REFUSAL_AKBAR_SENSE,
       "the refusal no longer says akbar comes AFTER the lexicographers")
    ck("minority" in body, "the method's standing does not reach the reader")
    try:
        permutations_of("دحرج")
    except ValueError:
        pass
    else:
        raise Fail("permutations_of accepted a quadriliteral")
    return "6 orderings, 4 attested; sense refused; rubaai refused"


@test("HONESTY", "a book about letters is not keyed by root")
def _t(conn):
    """Sirr Sina'at al-I'rab treats the LETTERS and al-Khasa'is treats topics.
    Inventing a root for either would file text under something the book never
    said."""
    for key, kind in (("sirr", "letter"), ("khasais", "chapter")):
        ck(LEXICONS[key].get("keyed_by") == kind,
           "%s is not marked as keyed by %s" % (key, kind))
        with unguarded(conn):
            bad = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE root_ar IS NOT NULL AND "
                "source_id=(SELECT id FROM sources WHERE key=?)",
                (key,)).fetchone()[0]
        ck(bad == 0, "%s filed %d entries under a root" % (key, bad))
    ck(heading_letter("AUTO باب الهمزة") == "ء", "letter heading not read")
    ck(heading_letter("AUTO حرف التاء") == "ت", "letter heading not read")
    ck(heading_letter("AUTO زيادة الياء") == "ي", "supplement not read")
    ck(heading_letter("باب لحاق") is None, "a non-letter title became a letter")
    return "sirr keyed by letter, khasais by chapter, neither by root"


@test("HONESTY", "an unmarked chapter becomes a gap, never a neighbour's text")
def _t(conn):
    """This witness of Sirr never marks حرف النون, and the volume divider was
    folded in as body text -- so حرف الميم ran to 109,605 bytes and half of it
    was Ibn Jinni on NUN, served under MIM."""
    fixture = "\n".join([
        "### || AUTO حرف الميم", "PageV01P400", "# الميم حرف",
        "### | CHECK [جزء 2]", "# unmarked nun chapter text here",
        "### || AUTO حرف الهاء", "PageV01P450", "# الهاء حرف",
    ])
    got = list(parse_lexicon(fixture, set(), LEXICONS["sirr"]))
    mim = [e for e in got if heading_letter(e["headword"]) == "م"]
    ck(mim, "the mim chapter was lost")
    ck("unmarked nun" not in "\n".join(mim[0]["lines"]),
       "the mim chapter swallowed the unmarked chapter after it")
    ck(any(heading_letter(e["headword"]) == "ه" for e in got),
       "the chapter after the divider was lost")
    need_source(conn, "sirr")
    with unguarded(conn):
        n = conn.execute(
            "SELECT length(text_raw) FROM entries e JOIN sources s "
            "ON s.id=e.source_id WHERE s.key='sirr' AND "
            "e.headword LIKE '%الميم%'").fetchone()[0]
    ck(n < 30000, "the live mim chapter is %d bytes -- it has swallowed "
                  "a neighbour again" % n)
    return "divider closes the chapter; mim is %d bytes, not 109,605" % n


@test("HONESTY", "a letter with no chapter says so, and blames the right thing")
def _t(conn):
    out = io.StringIO()
    real, sys.stdout = sys.stdout, out
    try:
        cmd_letter(conn, "ن")
    finally:
        sys.stdout = real
    body = out.getvalue()
    ck(NOT_FOUND_UR in body, "the not-found line is missing")
    ck("no chapter for this letter" in body, "the gap is not stated")
    ck("digitisation, not about Ibn Jinni" in body,
       "the gap is blamed on the author rather than the witness")
    return "nun: absent from this witness, and said to be so"


@test("HONESTY", "the bab is read off the mushaf, never guessed")
def _t(conn):
    """The plan was to read the mudari' vowel off a cited lexicon page. The
    OpenITI texts carry ZERO diacritics, so the vowel is not in them -- but
    the Qur'an is fully vowelled, and where a root's form-I verb occurs in
    both aspects the mushaf settles the bab itself, citable to a verse."""
    marks = set(chr(x) for x in range(0x064B, 0x0653))
    with unguarded(conn):
        for key in ("maqayis", "mufradat", "lisan"):
            row = conn.execute(
                "SELECT text_raw FROM entries e JOIN sources s ON "
                "s.id=e.source_id WHERE s.key=? LIMIT 20", (key,)).fetchall()
            n = sum(1 for r in row for ch in r[0] if ch in marks)
            ck(n == 0, "%s now carries %d diacritics -- if a witness with "
                       "vowels appears, the bab may be sourced from it too "
                       "and this test should be revisited" % (key, n))
    # Computed fresh from the corpus, NOT read out of roots.bab: reading the
    # stored value would let the whole derivation be deleted with the test
    # still green.
    derived = derive_babs(conn)
    known = {"سكن": 1, "كتب": 1, "نصر": 1, "ضرب": 2, "فتح": 3, "علم": 4}
    for root, want in known.items():
        got = derived.get(root)
        ck(got is not None, "%s: the mushaf no longer settles it" % root)
        ck(got["bab"] == want,
           "%s: derived bab %s, classical sarf says %d"
           % (root, got["bab"], want))
        ck(got["evidence"] and ":" in got["evidence"],
           "%s carries no verse evidence" % root)
        stored = q(conn, "SELECT bab, bab_verified, bab_method FROM roots "
                         "WHERE root_ar=?", (root,)).fetchone()
        if stored["bab"] is not None:
            ck(stored["bab"] == want, "%s stored as %s" % (root, stored["bab"]))
            ck(stored["bab_verified"] and
               stored["bab_method"] == "mushaf-vowelling",
               "%s stored without its method" % root)
    return "%s from the mushaf's own vowels, each cited to two verses" % (
        ", ".join("%s=%d" % kv for kv in sorted(known.items())))


@test("HONESTY", "a bab the mushaf does not settle is refused, not voted on")
def _t(conn):
    """كَبِرَ يَكْبَرُ and كَبُرَ يَكْبُرُ are two verbs sharing a root. Taking
    the commoner vowelling would be a silent majority vote -- the quiet
    inference this program exists to refuse."""
    derived = derive_babs(conn)
    # Two roots the mushaf reads two ways, and one whose single pair is not a
    # bab pair at all. The AMBIGUOUS FLAG is asserted, not merely that the bab
    # came out None: a majority vote on كبر happens to land on an invalid
    # vowel pair, so "bab is None" would pass even with the refusal deleted.
    for root in ("كبر", "لبس"):
        got = derived.get(root)
        ck(got is not None, "%s dropped out of the derivation entirely" % root)
        ck(got["ambiguous"] is True,
           "%s is no longer flagged ambiguous -- has a majority vote crept "
           "in? evidence: %s" % (root, got["evidence"]))
        ck(got["bab"] is None, "%s was given bab %s" % (root, got["bab"]))
        ck(got["evidence"].count("|") >= 2,
           "%s: the conflicting verses are not all recorded" % root)
    qadam = derived.get("قدم")
    ck(qadam and not qadam["ambiguous"] and qadam["bab"] is None,
       "قدم should be refused for an invalid vowel pair, not as ambiguous")
    for root in ("كبر", "لبس", "قدم"):
        stored = q(conn, "SELECT bab FROM roots WHERE root_ar=?",
                   (root,)).fetchone()
        ck(stored["bab"] is None, "%s was stored with a bab anyway" % root)
    # a passive must never be mistaken for the active pattern -- QAC does not
    # tag every one, so it is read off the vowelling
    letters = canonical_root("سكن")
    ck(_is_passive_surface("تُسْكَن", letters, "IMPF"),
       "a damma on the mudari' prefix is not being read as passive")
    ck(not _is_passive_surface("يَسْكُنُ", letters, "IMPF"),
       "an active mudari' was read as passive")
    ck(_is_passive_surface("قُتِلَ", canonical_root("قتل"), "PERF"),
       "fu'ila was not read as passive")
    ck(not _is_passive_surface("سَكَنَ", letters, "PERF"),
       "an active madi was read as passive")
    return "كبر and قدم refused with their conflicting verses shown"


@test("HONESTY", "only sound roots get a bab from the surface vowels")
def _t(conn):
    """I'lal moves and lengthens a weak root's vowels, so its surface harakat
    are not the pattern's harakat: قَالَ has no haraka on its 'ayn at all."""
    derived = derive_babs(conn)
    for root, info in derived.items():
        rc = RootClass(canonical_root(root))
        ck(rc.is_sound, "%s (%s) reached the bab derivation at all"
           % (root, rc.label()))
    for weak in ("قول", "وعد", "رمي"):
        ck(weak not in derived, "%s, which needs i'lal, was given a bab" % weak)
        r = q(conn, "SELECT bab FROM roots WHERE root_ar=?",
              (weak,)).fetchone()
        ck(r is None or r["bab"] is None, "%s was stored with a bab" % weak)
    n = sum(1 for i in derived.values() if i["bab"])
    ck(n > 100, "only %d roots derive a bab; the derivation has regressed" % n)
    return "%d sound roots derivable; every weak root still refuses" % n


@test("HONESTY", "i'lal reproduces the Qur'an, or it is not claimed")
def _t(conn):
    """Refusal R2 is discharged only where the mushaf proves it. The rules are
    regenerated against every weak root the Qur'an attests and compared
    EXACTLY; a class that does not reproduce it keeps its caveat."""
    known = {("قول", 1): ("قَالَ", "يَقُولُ", "قُلْ"),
             ("بيع", 2): ("بَاعَ", "يَبِيعُ", "بِعْ"),
             ("خوف", 4): ("خَافَ", "يَخَافُ", "خَفْ"),
             ("مدد", 1): ("مَدَّ", "يَمُدُّ", "مُدَّ")}
    for (root, bab), want in known.items():
        got = ilal_verb_forms(canonical_root(root),
                              RootClass(canonical_root(root)), bab)
        for slot, w in zip(("madi", "mudari", "amr"), want):
            # compared through stem_core: a hand-typed literal can differ from
            # the generated string in combining-mark ORDER while looking
            # identical -- the trap this file already documents
            ck(got.get(slot) and stem_core(got[slot]) == stem_core(w),
               "%s bab %d %s: %r, want %r" % (root, bab, slot,
                                              got.get(slot), w))
    for (root, bab), want in {("رمي", 2): ("رَمَى", "يَرْمِي"),
                              ("دعو", 1): ("دَعَا", "يَدْعُو"),
                              ("رضو", 4): ("رَضِيَ", "يَرْضَى")}.items():
        got = ilal_verb_forms(canonical_root(root),
                              RootClass(canonical_root(root)), bab)
        for slot, w in zip(("madi", "mudari"), want):
            ck(got.get(slot) and stem_core(got[slot]) == stem_core(w),
               "%s %s: %r, want %r" % (root, slot, got.get(slot), w))
    # Orthography, checked as an exact string. stem_core folds a final
    # maksura to alif -- correctly, رَمَى and رَمَا are one word -- so a
    # core comparison cannot see the difference the READER sees. A yaa
    # radical is written ى, a waaw radical ا.
    ck(ilal_verb_forms(canonical_root("رمي"),
                       RootClass(canonical_root("رمي")), 2)["madi"]
       == "رَمَى", "a yaa-final root must be written with alif maksura")
    ck(ilal_verb_forms(canonical_root("دعو"),
                       RootClass(canonical_root("دعو")), 1)["madi"]
       == "دَعَا", "a waaw-final root must be written with a full alif")
    # the non-word must be gone from a validated class
    forms = generate("قول", bab=1)["mujarrad"][0]["forms"]
    madi = forms[0]
    ck(stem_core(madi.text) == stem_core("قَالَ"),
       "madi of قول is %r" % madi.text)
    ck(madi.verified, "قَالَ is still marked unverified")
    ck("قَوَلَ" not in [getattr(f, "text", "") for f in forms],
       "the non-word قَوَلَ is still being emitted")
    return "قَالَ يَقُولُ قُلْ, بَاعَ, خَافَ, مَدَّ, رَمَى, دَعَا, رَضِيَ"


@test("HONESTY", "the i'lal check is run against the corpus, not remembered")
def _t(conn):
    """Computed here and now from the mushaf. A stored pass rate would let
    every rule be deleted with the number still printed."""
    res = ilal_check(conn)
    for kind, claimed in ILAL_VALIDATED.items():
        m, n, fails, ref = res["strong"][kind]
        ck(n > 0, "%s: nothing to check it against" % kind)
        ck("%d/%d" % (m, n) == claimed,
           "%s is claimed as %s but measures %d/%d -- update the claim or "
           "fix the rule" % (kind, claimed, m, n))
        ck(m == n, "%s is marked validated but gets %d of %d wrong"
           % (kind, n - m, n))
    for kind in ILAL_NOT_VALIDATED:
        m, n, fails, ref = res["strong"][kind]
        ck(m < n, "%s now reproduces the mushaf fully -- promote it to "
                  "ILAL_VALIDATED rather than leaving its forms unverified"
           % kind)
    return "ajwaf %s, naqis %s, mudaaf %s, all measured now" % (
        ILAL_VALIDATED["ajwaf"], ILAL_VALIDATED["naqis"],
        ILAL_VALIDATED["mudaaf"])


@test("HONESTY", "a class the corpus does not validate keeps its caveat")
def _t(conn):
    """The waaw of a mithal drops before a kasra and survives before a fatha
    -- except where it does not (وَضَعَ يَضَعُ). Nothing in the letters
    decides, so mithal is not claimed."""
    ck("mithal" in ILAL_NOT_VALIDATED, "mithal was promoted without evidence")
    forms = generate("وعد", bab=2)["mujarrad"][0]["forms"]
    real = [f for f in forms if not f.is_refusal]
    ck(all(not f.verified for f in real[:3]),
       "a mithal form is marked verified: %s"
       % [(f.slot, f.verified) for f in real[:3]])
    ck(stem_core(real[1].text) == stem_core("يَعِدُ"),
       "the kasra rule broke: %r" % real[1].text)
    # and where the waaw's fate is undetermined, refuse rather than guess
    sec = generate("وضع", bab=3)["mujarrad"][0]["forms"]
    mud = [f for f in sec if f.slot.startswith("mudari")][0]
    ck(mud.is_refusal, "the undetermined mithal mudari' was guessed: %r"
       % getattr(mud, "text", None))
    ck("وَضَعَ يَضَعُ" in mud.reason or "does not" in mud.reason,
       "the refusal does not say why")
    return "mithal unverified (%s); the undetermined mudari' refuses" % (
        ILAL_NOT_VALIDATED["mithal"])


@test("HONESTY", "the reading surface can only read, and only what is approved")
def _t(conn):
    """A separate server on a separate port with a GUARDED connection. The
    review gate exists to show unverified text; this exists to show only what
    a person has approved. One process serving both would put a single
    `unguarded` call between the reader and a fabrication."""
    body = source_section("# 11c." + "  THE READING SURFACE", "# 12." + "  CLI")
    ck(len(body) > 2000, "the reading section slice is empty (%d)" % len(body))
    code = strip_comments(body)
    routes = set(re.findall(r'u\.path [!=]= "([^"]+)"', code))
    ck(routes == {"/", "/api/read", "/api/roots", "/api/jinni"},
       "the reading surface exposes %s" % sorted(routes))
    ck("do_POST" not in code, "the reading surface accepts POST")
    for w in ("INSERT", "UPDATE", "DELETE", "_decide", "DROP"):
        ck(w not in code, "the reading surface can write: found %r" % w)
    ck("0.0.0.0" not in code, "the reading surface can bind publicly")
    # the ONE unguarded use must be a scalar count of PENDING rows, never text
    for stmt in re.findall(r"with unguarded\(conn\):(.{0,320})", code,
                           re.S):
        ck("text_raw" not in stmt and "scan_uri" not in stmt,
           "the reading surface reads entry TEXT through unguarded(): %s"
           % " ".join(stmt.split())[:120])
    return "2 routes, no writes, 127.0.0.1, unverified text unreachable"


@test("INTEGRITY", "the radical picker offers only roots that exist")
def _t(conn):
    """Building the picker from the alphabet would let a reader assemble
    ط ظ ء and land on 'this root does not occur in the corpus' -- true, and
    useless. It is built from the corpus's own index instead, so every letter
    it offers leads somewhere."""
    inv = root_inventory(conn)
    with unguarded(conn):
        want = {r[0] for r in conn.execute("SELECT root_ar FROM roots")}
    ck({x["r"] for x in inv} == want,
       "the picker's inventory is not the corpus's root list")
    ck(len(inv) == 1642, "%d roots in the inventory" % len(inv))
    ck(all(isinstance(x["n"], int) for x in inv),
       "a root is offered without its occurrence count")
    # and the page must build the picker from that list, not from a literal
    js = READ_HTML[READ_HTML.index("const PK="):]
    js = js[:js.index("function att(")]
    ck("/api/roots" in READ_HTML and "ROOTS" in js,
       "the picker is not built from the corpus inventory")
    ck("ابتثجح" not in READ_HTML and "أبجد" not in READ_HTML,
       "the picker carries a hardcoded alphabet")
    return "1,642 roots offered, none of them hypothetical"


@test("HONESTY", "an empty source shows an empty card, never a hidden one")
def _t(conn):
    """Hiding a source with nothing to say would imply agreement among sources
    that never spoke -- the governing rule applied to layout rather than to
    text."""
    data = read_root(conn, "سكن")
    ck(data.get("cards"), "no cards at all")
    keys = [c["key"] for c in data["cards"]]
    with unguarded(conn):
        have = {r[0] for r in conn.execute(
            "SELECT key FROM sources WHERE kind = 'lexicon'")}
        tafsirs = {r[0] for r in conn.execute(
            "SELECT key FROM sources WHERE kind = 'tafsir'")}
    # every source is accounted for EXACTLY ONCE: a lexicon keyed by root
    # gets a card, one that is not gets a search, and a tafsir gets neither
    # -- it is keyed by ayah and appears in its own section.
    want = {k for k in have if root_keyed(k)}
    ck(set(keys) == want, "cards %s but root-keyed lexicons %s"
       % (sorted(keys), sorted(want)))
    ck(len(keys) == len(set(keys)), "a source is carded twice: %s" % keys)
    # al-'Askari is not root-keyed and is not searched by string either: his
    # headings name the pair, so he has a section of his own. Every book is
    # still accounted for in exactly one place.
    searched = {b["key"] for b in data["passages"]} | (
        {"furuq"} if "furuq" in have else set())
    ck(searched == have - want, "unkeyed books %s but searched %s"
       % (sorted(have - want), sorted(searched)))
    ck("furuq" not in {b["key"] for b in data["passages"]},
       "al-'Askari is being string-searched as well as paired")
    ck("hits" in data["furuq"] and data["opposites"]["refusal"],
       "the synonyms/opposites section is missing from the payload")
    shown = keys + [b["key"] for b in data["passages"]] + \
        [t["key"] for t in data["tafsir_sources"]] + \
        [t["key"] for t in data["translations"]]
    ck(len(shown) == len(set(shown)),
       "the source selector lists a source twice: %s" % shown)
    ck(set(t["key"] for t in data["tafsir_sources"]) == tafsirs,
       "a tafsir is missing from its own section")
    for b in data["passages"]:
        ck(b["refusal"].startswith("REFUSED"),
           "%s does not say it has no article to quote" % b["key"])
        ck(b["rule"], "%s does not say its hits come from a string search"
           % b["key"])
    empty = [c for c in data["cards"] if not c["entries"]]
    ck(empty, "every source happens to have an entry; test is not exercised")
    for c in empty:
        ck("pending" in c, "an empty card does not say whether text is waiting")
    # and nothing unapproved may appear in the payload
    blob = json.dumps(data, ensure_ascii=False)
    with unguarded(conn):
        rows = conn.execute(
            "SELECT text_raw FROM entries WHERE root_ar='سكن' AND verified=0 "
            "AND text_raw IS NOT NULL LIMIT 5").fetchall()
    for (raw,) in rows:
        snippet = "".join(render_entry(raw)[:1])[:40]
        if snippet:
            ck(snippet not in blob,
               "unapproved text reached the reading payload")
    return "%d cards, %d of them explicitly empty" % (
        len(data["cards"]), len(empty))


@test("HONESTY", "the page keeps skeleton hits out of the attested column")
def _t(conn):
    """Trap 4 on the reading surface. A skeleton hit is a DIFFERENT WORD; the
    page may show it, but never in the same breath as evidence, and never
    without the corpus's own grammatical tag."""
    data = read_root(conn, "سكن")
    forms = [f for sec in data["sarf"] for f in sec["forms"]
             if not f.get("refused")]
    ck(forms, "no generated forms in the payload")
    exact = {x["form"] for f in forms for x in f["exact"]}
    skel = {x["form"] for f in forms for x in f["skeleton"]}
    ck(exact and skel, "the test is not exercised: %d exact, %d skeleton"
       % (len(exact), len(skel)))
    for f in forms:
        for x in f["exact"]:
            ck(stem_core(x["form"]) == stem_core(f["text"]),
               "%s listed as attesting %s" % (x["form"], f["text"]))
        for x in f["skeleton"]:
            ck(stem_core(x["form"]) != stem_core(f["text"]),
               "%s filed as a skeleton hit for its own word" % x["form"])
        for x in f["exact"] + f["skeleton"]:
            ck(x["tag"], "a corpus hit is shown without its tag")
    # and the page must say what a skeleton hit is NOT
    js = READ_HTML[READ_HTML.index("function att("):]
    js = js[:js.index("function draw(")]
    ck("NOT " + "attestation" in js and "skeleton" in js,
       "the page does not mark skeleton hits as non-evidence")
    return "%d forms; %d exact and %d skeleton hits, kept apart" % (
        len(forms), len(exact), len(skel))


@test("HONESTY", "the page reads the payload the builder actually writes")
def _t(conn):
    """The letter cards were once assigned to out["letters"], overwriting the
    list of radicals that the heading joins -- so the root printed as three
    `[object Object]`s.  Neither side was wrong on its own; they disagreed.
    That is trap 8 (the loader and the query path must canonicalise
    identically) wearing a different hat, so it gets the same kind of guard:
    every key the page touches must exist, and no key may be written twice."""
    src = inspect.getsource(read_root)
    written = re.findall(r'out\[("[a-z_]+")\] *=[^=]', src)
    dupes = sorted({k for k in written if written.count(k) > 1})
    ck(not dupes, "read_root writes %s more than once" % ", ".join(dupes))
    data = read_root(conn, "سكن")
    ck(not data.get("absent"), "no payload to check")
    # a key may come from a full payload, from the absent one, or from the
    # handler's own error object -- read all three off the code, not memory
    have = set(data) | set(read_root(conn, "ققق"))
    have |= set(re.findall(r'json\.dumps\(\{"(\w+)"', source_section(
        "# 11c." + "  THE READING SURFACE", "# 12." + "  CLI")))
    read = set(re.findall(r"\br\.([A-Za-z_]+)", READ_HTML))
    missing = sorted(k for k in read if k not in have)
    ck(not missing, "the page reads %s, which no payload has"
       % ", ".join(missing))
    # the heading joins letters; they must be letters, not objects
    ck(data["letters"] == list("سكن"),
       "the heading would print %r" % (data["letters"],))
    for c in data["letter_cards"]:
        ck(isinstance(c, dict) and "letter" in c, "letter card is %r" % (c,))
    return ("%d payload keys read by the page, all present; "
            "no key written twice" % len(read))


@test("HONESTY", "refusals are refusals, not empty strings")
def _t(conn):
    res = generate("سكن")
    refs = all_refusals(res)
    ck(len(refs) >= 7, "only %d refusals across the whole table" % len(refs))
    for r in refs:
        ck(r.reason.startswith("REFUSED"), "refusal %s does not say so" % r.slot)
        ck(len(r.reason) > 40, "refusal %s gives no reason" % r.slot)
        ck(not hasattr(r, "text"), "a Refusal grew a .text attribute")
    return "%d refusals, all stating REFUSED and why" % len(refs)


def run_tests(conn):
    total = failed = skipped = 0
    for section in ("INTEGRITY", "HONESTY"):
        _w("")
        _w(BAR)
        _w(section)
        _w(BAR)
        for name, fn in _TESTS[section]:
            total += 1
            try:
                detail = fn(conn)
            except Skip as e:
                skipped += 1
                _w("skip  %s" % name)
                _w("        %s" % e)
            except Fail as e:
                failed += 1
                _w("FAIL  %s" % name)
                for line in _wrap(str(e), 66):
                    _w("        %s" % line)
            except Exception as e:                     # noqa: BLE001
                failed += 1
                _w("ERROR %s" % name)
                _w("        %s: %s" % (type(e).__name__, e))
            else:
                _w("ok    %s" % name)
                if detail:
                    _w("        %s" % detail)
    _w("")
    _w(BAR)
    _w("%d passed, %d failed, %d skipped, %d total"
       % (total - failed - skipped, failed, skipped, total))
    if skipped:
        _w("(skipped checks need a lexicon ingested; they are not passes.)")
    if failed:
        _w("")
        _w("A HONESTY failure means the governing rule has been broken.")
        _w("The change that caused it is wrong; the test is not.")
    _w(BAR)
    return 1 if failed else 0


# ==========================================================================
# 11b.  THE REVIEW SERVER  --  build path, never the query path
# ==========================================================================
#
# This is the approval gate with a keyboard instead of a prompt.  It exists
# because the gate is only honoured if it is bearable: 4,628 entries at one
# terminal keystroke each is not.
#
# It is emphatically NOT the reading surface.  It shows UNVERIFIED text -- that
# is its whole job -- so it is kept apart from everything a reader sees:
#
#   * it binds to 127.0.0.1 only, and there is no option to bind elsewhere;
#   * every API call needs a token minted at startup, so a page on another
#     site cannot drive it by POSTing to localhost;
#   * it serves no query-path route at all.  Nothing here can be mistaken for
#     the reader's view of the dictionary.
#
# Stdlib http.server, so lughat.py stays single-file and offline.  The handler
# logic ports to FastAPI unchanged if a real framework is ever wanted.

REVIEW_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Review queue — lughat</title>
<style>
:root{
  --bg:#EFF1EF;--surface:#F8F9F7;--ink:#14181A;--body:#2C3436;--muted:#5B6663;
  --faint:#7F8A86;--rule:#D6DBD7;--soft:#E3E7E3;
  --madder:#9C3B2E;--madder-bg:#F0E2DE;--verd:#3D6A57;--verd-bg:#DEEAE3;
  --ochre:#8E6A1F;--ochre-bg:#F0E7D3;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#101413;--surface:#171C1A;--ink:#E9ECE7;--body:#C7CEC9;--muted:#94A09B;
  --faint:#78837E;--rule:#2A322F;--soft:#222A27;
  --madder:#D8796A;--madder-bg:#33211E;--verd:#7CBBA0;--verd-bg:#1A2A24;
  --ochre:#CFA75B;--ochre-bg:#2A2418;}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--body);
  font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}
.ar{font-family:"SBL BibLit","Traditional Arabic","Amiri","Geeza Pro",serif;
  direction:rtl;unicode-bidi:isolate}
header{position:sticky;top:0;background:var(--surface);
  border-bottom:1px solid var(--rule);padding:.7rem 1.1rem;z-index:5}
.bar{display:flex;align-items:center;gap:1rem;flex-wrap:wrap;
  max-width:900px;margin:0 auto}
.brand{font-weight:600;color:var(--ink);letter-spacing:-.01em}
.brand small{display:block;font-weight:400;font-size:.72rem;color:var(--madder);
  letter-spacing:.04em;text-transform:uppercase}
.prog{flex:1;min-width:130px;height:7px;background:var(--soft);border-radius:1px;
  overflow:hidden}
.prog i{display:block;height:100%;background:var(--verd);width:0;transition:width .2s}
.count{font-variant-numeric:tabular-nums;font-size:.85rem;color:var(--muted)}
#root{font:inherit;padding:.3rem .5rem;border:1px solid var(--rule);border-radius:3px;background:var(--bg);color:var(--ink);direction:rtl}
select{font:inherit;font-size:.85rem;padding:.25rem .4rem;background:var(--bg);
  color:var(--body);border:1px solid var(--rule);border-radius:3px}
main{max-width:900px;margin:0 auto;padding:1.6rem 1.1rem 7rem}
.card{background:var(--surface);border:1px solid var(--rule);border-radius:4px;
  padding:1.3rem 1.4rem;margin-bottom:1rem}
.meta{display:flex;gap:.55rem;align-items:baseline;flex-wrap:wrap;
  padding-bottom:.7rem;margin-bottom:.9rem;border-bottom:1px solid var(--soft)}
.head{font-size:1.5rem;color:var(--ink);font-weight:600}
.arrow{color:var(--faint)}
.root{font-size:1.5rem;color:var(--ink)}
.badge{font-size:.68rem;letter-spacing:.06em;text-transform:uppercase;
  padding:.18rem .45rem;border-radius:2px;font-weight:600}
.badge.direct{background:var(--verd-bg);color:var(--verd)}
.badge.geminate,.badge.weak_final{background:var(--ochre-bg);color:var(--ochre)}
.badge.unmatched{background:var(--madder-bg);color:var(--madder)}
.cite{margin-left:auto;font-size:.82rem;color:var(--muted);
  font-variant-numeric:tabular-nums}
.warn{background:var(--ochre-bg);color:var(--ochre);font-size:.85rem;
  padding:.5rem .7rem;border-radius:3px;margin-bottom:.9rem}
.warn.hot{background:var(--madder-bg);color:var(--madder)}
.txt p{margin:0 0 .7rem;font-size:1.16rem;line-height:1.95;color:var(--ink)}
.txt p:last-child{margin-bottom:0}
footer{position:fixed;left:0;right:0;bottom:0;background:var(--surface);
  border-top:1px solid var(--rule);padding:.75rem 1.1rem}
.acts{max-width:900px;margin:0 auto;display:flex;gap:.6rem;align-items:center;
  flex-wrap:wrap}
button{font:inherit;font-size:.9rem;padding:.5rem .95rem;border-radius:3px;
  border:1px solid var(--rule);background:var(--bg);color:var(--body);cursor:pointer}
button:hover{border-color:var(--muted)}
button:focus-visible{outline:2px solid var(--verd);outline-offset:2px}
button.ok{background:var(--verd);border-color:var(--verd);color:var(--bg);font-weight:600}
button.no{background:var(--madder);border-color:var(--madder);color:var(--bg)}
kbd{font:inherit;font-size:.74rem;opacity:.75;border:1px solid currentColor;
  border-radius:2px;padding:0 .25rem;margin-left:.35rem}
.hint{margin-left:auto;font-size:.8rem;color:var(--faint)}
.done{text-align:center;padding:4rem 1rem;color:var(--muted)}
.done b{display:block;font-size:1.3rem;color:var(--ink);margin-bottom:.5rem}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style></head><body>
<header><div class="bar">
  <div class="brand">Review queue<small>unverified &mdash; not served</small></div>
  <div class="prog"><i id="pi"></i></div>
  <span class="count" id="ct">&hellip;</span>
  <select id="tbl">
    <option value="entries">lexicon entries</option>
    <option value="tafsir">tafsir passages</option>
  </select>
  <input id="root" type="search" placeholder="one root, e.g. سكن" size="14">
  <select id="src">
    <option value="">every source</option>
    <option value="maqayis">Maqāyīs</option>
    <option value="mufradat">Mufradāt</option>
    <option value="lisan">Lisān</option>
    <option value="furuq">Furūq (al-ʿAskarī)</option>
    <option value="sirr">Sirr (Ibn Jinnī)</option>
    <option value="khasais">Khaṣāʾiṣ (Ibn Jinnī)</option>
  </select>
  <select id="filt">
    <option value="">every reachable extraction</option>
    <option value="direct">direct only</option>
    <option value="geminate">geminate bridge</option>
    <option value="weak_final">weak-final bridge</option>
    <option value="unmatched">unmatched (no such root in the Qur’an)</option>
  </select>
</div></header>
<main id="main"><div class="done">loading&hellip;</div></main>
<footer><div class="acts">
  <button class="ok" onclick="decide('approve')">Approve<kbd>A</kbd></button>
  <button onclick="skip()">Skip<kbd>S</kbd></button>
  <button class="no" onclick="decide('reject')">Wrong extraction<kbd>R</kbd></button>
  <button onclick="undo()">Undo<kbd>U</kbd></button>
  <span class="hint" id="hint"></span>
</div></footer>
<script>
const T="__TOKEN__";let q=[],i=0,last=null,tot=0,done=0,pending=0,busy=false;
const api=(p,o)=>fetch(p+(p.includes("?")?"&":"?")+"t="+encodeURIComponent(T),o)
  .then(r=>r.json());
function esc(s){return String(s).replace(/[&<>"']/g,c=>
  ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function table(){return document.getElementById("tbl").value;}
async function refreshStats(){
  const st=await api("/api/stats?table="+encodeURIComponent(table()));
  tot=st.stats.reduce((a,s)=>a+s.pending+s.approved+s.rejected,0);
  done=st.stats.reduce((a,s)=>a+s.approved+s.rejected,0);
  pending=st.stats.reduce((a,s)=>a+s.pending,0);
}
async function load(){
  busy=true;
  // `last` belongs to the queue we are leaving. Carrying it across a reload
  // let Undo un-approve an entry from the previous filter, off screen.
  last=null;
  const ex=document.getElementById("filt").value;
  // The extraction filter belongs to the lexicon queue; a tafsir pericope has
  // an anchor, not an extraction, so the filter is hidden rather than applied
  // silently to a column it does not describe.
  const tf=table()==="tafsir";
  document.getElementById("filt").style.display=tf?"none":"";
  await refreshStats();
  const rt=document.getElementById("root").value.trim();
  document.getElementById("root").style.display=tf?"none":"";
  const d=await api("/api/queue?table="+encodeURIComponent(table())+
    "&root="+encodeURIComponent(tf?"":rt)+
    "&source="+encodeURIComponent(tf?"":document.getElementById("src").value)+
    "&extraction="+encodeURIComponent(tf?"":ex));
  if(d.error){
   document.getElementById("main").innerHTML=
     '<div class="done"><b>'+esc(d.error)+'</b>The queue is unchanged.</div>';
   busy=false;return;}
  q=d.entries;i=0;busy=false;draw();
}
function draw(){
  const m=document.getElementById("main");
  document.getElementById("pi").style.width=(tot?100*done/tot:0)+"%";
  document.getElementById("ct").textContent=done+" / "+tot+" decided";
  if(i>=q.length){
    // The server pages the queue. Saying "empty" here without asking would
    // tell the reviewer they were finished with thousands still pending.
    m.innerHTML='<div class="done"><b>'+
      (q.length?"Fetching the next batch&hellip;":"Nothing left in this filter.")+
      '</b>Everything you did not approve stays unserved.</div>';
    document.getElementById("hint").textContent="";
    if(q.length&&!busy)load();
    return;}
  const e=q[i];
  const tf=table()==="tafsir";
  const inferred=!tf&&e.extraction!=="direct";
  m.innerHTML='<div class="card"><div class="meta">'+
    '<span class="head ar">'+esc(e.headword)+'</span>'+
    (tf?'':'<span class="arrow">&rarr;</span>'+
      '<span class="root ar">'+esc(e.root)+'</span>')+
    '<span class="badge '+esc(e.extraction)+'">'+esc(e.extraction)+'</span>'+
    '<span class="cite">'+esc(e.source)+' &middot; vol '+esc(e.vol)+
      ' p. '+esc(e.page)+
      (tf?'':' &middot; root occurs '+esc(e.freq)+'&times;')+'</span></div>'+
    (tf?'<div class="warn">The question here is the ANCHOR: is this passage '+
      'really this book on '+esc(e.headword)+'? The evidence is below; the '+
      'text quotes the ayat it comments on.</div>':'')+
    (inferred?'<div class="warn'+(e.extraction==="unmatched"?" hot":"")+'">'+
      'The root was INFERRED ('+esc(e.extraction)+'), not read from the heading.'+
      (e.extraction==="unmatched"?" This root does not occur in the Qur'an.":"")+
      '</div>':'')+
    (e.scan_only?'<div class="warn hot">This source keyed in no text; the page '+
      'image is the citation.</div>':'')+
    (e.flags&&e.flags.length?'<div class="warn hot">'+
      e.flags.map(f=>esc(f)).join(" &middot; ")+
      (tf?'':' &mdash; check the heading against the printed page.')+
      '</div>':'')+
    '<div class="txt ar">'+e.lines.map(l=>"<p>"+esc(l)+"</p>").join("")+
    '</div></div>';
  document.getElementById("hint").textContent=
    (q.length-i)+" in this batch \u00b7 "+pending+" pending";
}
async function decide(d){
  if(i>=q.length||busy)return;const e=q[i];busy=true;
  try{
    await api("/api/decide",{method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({id:e.id,decision:d,table:table()})});
    last=e;done++;pending--;i++;
  }finally{busy=false;}
  draw();
}
function skip(){
  // Undo must never reach past the entry the reviewer can actually see.
  if(i<q.length){last=null;i++;draw();}
}
async function undo(){
  if(!last||busy)return;busy=true;
  const target=last;
  try{
    await api("/api/decide",{method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({id:target.id,decision:"unset",table:table()})});
    done--;pending++;last=null;
    const at=q.findIndex(x=>x.id===target.id);
    i=at>=0?at:Math.max(0,i-1);
  }finally{busy=false;}
  draw();
}
addEventListener("keydown",ev=>{
  if(ev.target.tagName==="SELECT")return;
  const k=ev.key.toLowerCase();
  if(k==="a"){ev.preventDefault();decide("approve");}
  else if(k==="s"||k===" "){ev.preventDefault();skip();}
  else if(k==="r"){ev.preventDefault();decide("reject");}
  else if(k==="u"){ev.preventDefault();undo();}
});
document.getElementById("filt").addEventListener("change",load);
document.getElementById("tbl").addEventListener("change",load);
document.getElementById("root").addEventListener("change",load);
document.getElementById("src").addEventListener("change",load);
// the counter is the WHOLE queue; when a root is filtering it, the batch
// count below is the honest number for what is on screen
document.getElementById("root").addEventListener("keydown",ev=>{
  ev.stopPropagation();
  if(ev.key==="Enter")load();});
load();
</script></body></html>
"""

REVIEW_HOST = "127.0.0.1"
REVIEW_PORT = 8765


# The two review queues.  A table name cannot be a bound parameter, so it is
# whitelisted here and nowhere else: every function below that interpolates a
# table looks it up in this tuple first, and refuses anything else.
REVIEWABLE = ("entries", "tafsir")


def _table(name):
    if name not in REVIEWABLE:
        raise ValueError("not a reviewable table: %r" % (name,))
    return name


def _tafsir_queue_rows(conn, limit=60):
    """The tafsir queue.  A pericope's identity is its ANCHOR, so the anchor
    and the evidence for it are what the reviewer is shown first: the decision
    being asked for is 'is this really al-Baghawi on 2:35?'."""
    sql = ("SELECT t.id, t.sura, t.aya, t.aya_to, t.vol, t.page, t.page_to, "
           "t.text_raw, t.scan_uri, t.flags, t.anchor_method, "
           "t.anchor_evidence, s.title, s.author, s.edition "
           "FROM tafsir t LEFT JOIN sources s ON s.id = t.source_id "
           "WHERE t.verified = 0 AND t.rejected = 0 "
           "ORDER BY t.sura, t.aya, t.id LIMIT ?")
    with unguarded(conn):
        rows = list(conn.execute(sql, (int(limit),)))
    out = []
    for r in rows:
        span = ("%d:%d" % (r["sura"], r["aya"]) if not r["aya_to"]
                or r["aya_to"] == r["aya"] else
                "%d:%d-%d" % (r["sura"], r["aya"], r["aya_to"]))
        out.append({
            "id": r["id"], "headword": span, "root": "",
            "extraction": r["anchor_method"] or "",
            "vol": r["vol"],
            "page": (r["page"] if not r["page_to"]
                     else "%s-%s" % (r["page"], r["page_to"])),
            "freq": 0,
            "source": r["title"] or "(source row missing)",
            "author": r["author"] or "", "edition": r["edition"] or "",
            "lines": (render_entry(r["text_raw"])
                      if r["text_raw"] is not None
                      else ["[scan only -- no text keyed in]",
                            r["scan_uri"] or "(no scan_uri either)"]),
            "scan_only": r["text_raw"] is None,
            "flags": [f for f in (r["flags"] or "").split(",") if f]
                     + ([r["anchor_evidence"]] if r["anchor_evidence"] else []),
        })
    return out


def _queue_rows(conn, extraction=None, limit=60, table="entries", root=None,
                source=None):
    if _table(table) == "tafsir":
        return _tafsir_queue_rows(conn, limit)
    # LEFT JOIN, not JOIN: an entry whose source row has gone missing would
    # otherwise vanish from the queue while still counting as pending, so the
    # reviewer can never reach the end and is never told why.
    sql = ("SELECT e.id, e.headword, e.root_ar, e.extraction, e.vol, e.page, "
           "e.text_raw, e.scan_uri, e.flags, s.title, s.author, s.edition, "
           "COALESCE((SELECT n_segments FROM roots r "
           "          WHERE r.root_ar = e.root_ar), 0) AS freq "
           "FROM entries e LEFT JOIN sources s ON s.id = e.source_id "
           "WHERE e.verified = 0 AND e.rejected = 0")
    params = []
    if extraction:
        sql += " AND e.extraction = ?"
        params.append(extraction)
    else:
        # see cmd_review: an unmatched root is unreachable from the reader,
        # so it is not the default work
        sql += " AND e.extraction IS NOT 'unmatched'"
    if source:
        sql += " AND e.source_id = (SELECT id FROM sources WHERE key = ?)"
        params.append(source)
    if root:
        # The queue is 15,768 entries in frequency order, which is the right
        # default and useless when you are looking at ONE word in the reader
        # and want its articles approved now. The root is canonicalised by
        # the same function the loader used, so a root typed the ordinary way
        # (رمى) finds what the corpus stored (رمي).
        sql += " AND e.root_ar = ?"
        params.append("".join(canonical_root(root)))
    sql += " ORDER BY freq DESC, e.id LIMIT ?"
    params.append(int(limit))
    with unguarded(conn):
        rows = list(conn.execute(sql, params))
    out = []
    for r in rows:
        out.append({
            "id": r["id"], "headword": r["headword"],
            "root": r["root_ar"] or "", "extraction": r["extraction"],
            "vol": r["vol"], "page": r["page"], "freq": int(r["freq"] or 0),
            "source": r["title"] or "(source row missing)",
            "author": r["author"] or "",
            "edition": r["edition"] or "",
            # text_raw is NULL for a scan-only source, which the schema
            # explicitly permits. The reader path handled that; the review
            # path crashed on it, and one such row killed the whole queue.
            "lines": (render_entry(r["text_raw"])
                      if r["text_raw"] is not None
                      else ["[scan only — no text keyed in]",
                            r["scan_uri"] or "(no scan_uri either)"]),
            "scan_only": r["text_raw"] is None,
            "flags": [f for f in (r["flags"] or "").split(",") if f],
        })
    return out


def _queue_stats(conn, table="entries"):
    group = "extraction" if _table(table) == "entries" else "anchor_method"
    with unguarded(conn):
        rows = list(conn.execute(
            "SELECT %s AS extraction, "
            "SUM(verified=1 AND rejected=0) approved, "
            "SUM(rejected=1) rejected, "
            "SUM(verified=0 AND rejected=0) pending "
            "FROM %s GROUP BY %s ORDER BY %s"
            % (group, _table(table), group, group)))
    return [{"extraction": r["extraction"], "approved": r["approved"],
             "rejected": r["rejected"], "pending": r["pending"]} for r in rows]


def _decide(conn, entry_id, decision, reason=None, table="entries",
            how="read"):
    if decision not in ("approve", "reject", "unset"):
        raise ValueError("decision must be approve, reject or unset")
    tbl = _table(table)
    with unguarded(conn):
        # Each branch clears the OTHER branch's audit field. Leaving them
        # behind produced rows that were verified=1 while still carrying a
        # reject_reason -- an audit trail that contradicts itself.
        if decision == "approve":
            conn.execute("UPDATE %s SET verified=1, rejected=0, "
                         "reject_reason=NULL, verified_at=datetime('now'), "
                         "verified_by=? WHERE id=?" % tbl, (how, entry_id))
        elif decision == "reject":
            conn.execute("UPDATE %s SET verified=0, rejected=1, "
                         "verified_at=NULL, reject_reason=? WHERE id=?"
                         % tbl, (reason, entry_id))
        else:
            conn.execute("UPDATE %s SET verified=0, rejected=0, "
                         "verified_at=NULL, reject_reason=NULL "
                         "WHERE id=?" % tbl, (entry_id,))
        conn.commit()
        row = conn.execute("SELECT verified, rejected FROM %s WHERE id=?" % tbl,
                           (entry_id,)).fetchone()
    return {"id": entry_id, "verified": row["verified"],
            "rejected": row["rejected"]} if row else None


DB_LOCK = threading.Lock()


def make_review_app(conn, token):
    """Return a BaseHTTPRequestHandler class bound to this connection."""
    import http.server

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "lughat-review"

        def log_message(self, fmt, *a):        # quiet; this is a local tool
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            blob = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(blob)))
            self.send_header("X-Content-Type-Options", "nosniff")
            # this page must never be embedded, and must never talk out
            # connect-src 'self' is load-bearing: without it default-src
            # 'none' blocks the page's own fetch() and the queue never loads.
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; style-src 'unsafe-inline'; "
                             "script-src 'unsafe-inline'; connect-src 'self'; "
                             "frame-ancestors 'none'; base-uri 'none'; "
                             "form-action 'none'")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(blob)

        def _authed(self, qs):
            got = qs.get("t", [""])[0]
            try:
                # constant-time, so the token cannot be guessed byte by byte
                return secrets.compare_digest(got, token)
            except TypeError:
                # compare_digest raises on a non-ASCII str. A token that
                # cannot be compared is not a valid token; it must not be an
                # unhandled exception on an UNAUTHENTICATED route.
                return False

        def do_GET(self):
            import urllib.parse as up
            u = up.urlparse(self.path)
            qs = up.parse_qs(u.query)
            if u.path == "/":
                if not self._authed(qs):
                    return self._send(403, "missing or bad token\n",
                                      "text/plain; charset=utf-8")
                return self._send(200, REVIEW_HTML.replace("__TOKEN__", token),
                                  "text/html; charset=utf-8")
            if not self._authed(qs):
                return self._send(403, json.dumps({"error": "bad token"}))
            if u.path == "/api/queue":
                ex = qs.get("extraction", [None])[0] or None
                try:
                    tbl = _table(qs.get("table", ["entries"])[0])
                except ValueError as e:
                    return self._send(400, json.dumps({"error": str(e)}))
                root = (qs.get("root", [""])[0] or "").strip()
                srck = (qs.get("source", [""])[0] or "").strip() or None
                try:
                    with DB_LOCK:
                        rows = _queue_rows(conn, ex, table=tbl, root=root,
                                           source=srck)
                except ValueError as e:
                    # a root that is not a root is the reviewer's typo, not a
                    # server error: say so and leave the queue as it was
                    return self._send(400, json.dumps(
                        {"error": str(e)}, ensure_ascii=False))
                return self._send(200, json.dumps(
                    {"entries": rows, "table": tbl}, ensure_ascii=False))
            if u.path == "/api/stats":
                try:
                    tbl = _table(qs.get("table", ["entries"])[0])
                except ValueError as e:
                    return self._send(400, json.dumps({"error": str(e)}))
                with DB_LOCK:
                    st = _queue_stats(conn, table=tbl)
                return self._send(200, json.dumps(
                    {"stats": st, "table": tbl}, ensure_ascii=False))
            return self._send(404, json.dumps({"error": "no such route"}))

        def handle_one_request(self):
            # Any unexpected error must become a 500, not a dropped connection
            # with no HTTP response at all -- the reviewer would just see the
            # queue stop, with nothing to explain it.
            try:
                return http.server.BaseHTTPRequestHandler.handle_one_request(
                    self)
            except Exception:                                   # noqa: BLE001
                sys.stderr.write(traceback.format_exc())
                try:
                    self._send(500, json.dumps({"error": "server error"}))
                except Exception:                               # noqa: BLE001
                    pass

        def do_POST(self):
            import urllib.parse as up
            u = up.urlparse(self.path)
            qs = up.parse_qs(u.query)
            if not self._authed(qs):
                return self._send(403, json.dumps({"error": "bad token"}))
            if u.path != "/api/decide":
                return self._send(404, json.dumps({"error": "no such route"}))
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._send(400, json.dumps({"error": "bad length"}))
            if n < 0:
                # rfile.read(-1) blocks until the peer closes: a handful of
                # these would exhaust the thread pool.
                return self._send(400, json.dumps({"error": "bad length"}))
            if n > 64 * 1024:
                return self._send(413, json.dumps({"error": "too large"}))
            try:
                payload = json.loads(self.rfile.read(n).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("body must be an object")
                if not isinstance(payload.get("id"), int) or \
                        isinstance(payload.get("id"), bool):
                    # int() would silently accept 1.9 and "1" and decide a
                    # different entry than the caller named.
                    raise ValueError("id must be an integer")
                with DB_LOCK:
                    res = _decide(conn, int(payload["id"]),
                                  payload["decision"], payload.get("reason"),
                                  table=_table(payload.get("table",
                                                           "entries")))
            except (ValueError, KeyError, TypeError) as e:
                return self._send(400, json.dumps({"error": str(e)}))
            except Exception:                                   # noqa: BLE001
                sys.stderr.write(traceback.format_exc())
                return self._send(500, json.dumps({"error": "server error"}))
            return self._send(200, json.dumps({"ok": True, "row": res}))

    return Handler


def cmd_serve(conn, args):
    import http.server
    port = REVIEW_PORT
    for a in args:
        if a.startswith("--port="):
            port = int(a.split("=", 1)[1])
    token = secrets.token_urlsafe(18)
    handler = make_review_app(conn, token)
    httpd = http.server.ThreadingHTTPServer((REVIEW_HOST, port), handler)
    url = "http://%s:%d/?t=%s" % (REVIEW_HOST, port, token)
    _w(BAR)
    _w("REVIEW SERVER -- the build path, not the reading surface.")
    _w(BAR)
    _w("This page shows UNVERIFIED text. That is its job. Nothing you see")
    _w("here is served to a query until you approve it.")
    _w("")
    _w("  %s" % url)
    _w("")
    _w("Bound to %s only. The token is new every run." % REVIEW_HOST)
    _w("Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        _w("")
        _w("stopped.")
    finally:
        httpd.server_close()
    return 0


# ==========================================================================
# 11c.  THE READING SURFACE  --  query path, and nothing else
# ==========================================================================
#
# Requirement 4: a word opens a stack of CARDS, one per source, each showing
# that source's exact text with its citation, and a control to choose which
# sources appear.
#
# It is a SEPARATE server from the review gate, on a separate port, with a
# GUARDED connection. The review gate exists to show unverified text; this
# exists to show only what a person has approved. Running them in one process
# would put one `unguarded` call between the reader and a fabrication.
#
# A source with nothing on this root gets an EXPLICIT EMPTY CARD. Hiding it
# would imply agreement among sources that never spoke -- the governing rule
# applied to layout rather than to text.

READ_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lughat</title>
<style>
:root{--bg:#EFF1EF;--surf:#F8F9F7;--ink:#14181A;--body:#2C3436;--mut:#5B6663;
 --faint:#7F8A86;--rule:#D6DBD7;--soft:#E3E7E3;--mad:#9C3B2E;--madbg:#F0E2DE;
 --verd:#3D6A57;--verdbg:#DEEAE3;--och:#8E6A1F;--ochbg:#F0E7D3;}
@media (prefers-color-scheme:dark){:root{--bg:#101413;--surf:#171C1A;
 --ink:#E9ECE7;--body:#C7CEC9;--mut:#94A09B;--faint:#78837E;--rule:#2A322F;
 --soft:#222A27;--mad:#D8796A;--madbg:#33211E;--verd:#7CBBA0;--verdbg:#1A2A24;
 --och:#CFA75B;--ochbg:#2A2418;}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--body);
 font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}
.ar{font-family:"SBL BibLit","Traditional Arabic","Amiri","Geeza Pro",serif;
 direction:rtl;unicode-bidi:isolate}
header{position:sticky;top:0;z-index:5;background:var(--surf);
 border-bottom:1px solid var(--rule);padding:.7rem 1.1rem}
.bar{max-width:940px;margin:0 auto;display:flex;gap:.8rem;align-items:center;
 flex-wrap:wrap}
.brand{font-weight:600;color:var(--ink);letter-spacing:-.01em;white-space:nowrap}
.brand small{display:block;font-size:.68rem;font-weight:400;color:var(--verd);
 text-transform:uppercase;letter-spacing:.05em}
input[type=search]{flex:1;min-width:170px;font:inherit;font-size:1.05rem;
 padding:.42rem .6rem;border:1px solid var(--rule);border-radius:3px;
 background:var(--bg);color:var(--ink)}
input:focus-visible{outline:2px solid var(--verd);outline-offset:1px}
main{max-width:940px;margin:0 auto;padding:1.5rem 1.1rem 5rem}
.head{display:flex;gap:1rem;align-items:baseline;flex-wrap:wrap;
 padding-bottom:.7rem;border-bottom:1px solid var(--rule);margin-bottom:1rem}
.head h1{margin:0;font-size:2rem;color:var(--ink);font-weight:600}
.cls{font-size:.84rem;color:var(--mut)}
.pill{font-size:.68rem;text-transform:uppercase;letter-spacing:.05em;
 padding:.16rem .45rem;border-radius:2px;background:var(--soft);color:var(--mut)}
.pill.ok{background:var(--verdbg);color:var(--verd)}
.pill.no{background:var(--madbg);color:var(--mad)}
.pill.warn{background:var(--ochbg);color:var(--och)}
h2{font-size:.72rem;text-transform:uppercase;letter-spacing:.11em;
 color:var(--faint);margin:1.8rem 0 .6rem;font-weight:600}
.card{background:var(--surf);border:1px solid var(--rule);border-radius:4px;
 padding:1rem 1.15rem;margin-bottom:.7rem}
.card.empty{background:transparent;border-style:dashed;color:var(--faint)}
.card.empty .how{margin-top:.5rem;font-size:.76rem;color:var(--mut)}
.card.empty .how code{display:block;margin:.3rem 0;padding:.3rem .5rem;background:var(--soft);border-radius:3px;color:var(--ink);font-size:.8rem;direction:ltr;unicode-bidi:isolate}
.card.empty.ref{color:var(--mad);border-color:var(--mad);
 font-size:.82rem;line-height:1.6}
.ct{display:flex;gap:.6rem;align-items:baseline;flex-wrap:wrap;
 margin-bottom:.55rem}
.ct b{color:var(--ink);font-size:1rem}
.refuse{border-left:3px solid var(--mad);background:var(--madbg);
 color:var(--body);padding:.55rem .75rem;border-radius:3px;
 margin:0 0 .6rem;font-size:.86rem;line-height:1.55}
.refuse b{color:var(--mad)}
.gloss{margin:-.35rem 0 1rem;padding:.55rem .75rem;border:1px dashed var(--och);
 border-radius:4px;background:var(--ochbg)}
.glosshead{font-size:.64rem;letter-spacing:.06em;text-transform:uppercase;
 color:var(--och);font-weight:600;margin-bottom:.4rem}
.gloss p.ur{font-family:"Noto Nastaliq Urdu","Jameel Noori Nastaleeq",
 "Awami Nastaliq",serif;direction:rtl;text-align:right;line-height:2.6;
 font-size:.95rem;color:var(--body);margin:0 0 .5rem}
.quoted{margin:-.35rem 0 1rem;padding:.55rem .75rem;border-left:3px solid var(--verd);background:var(--verdbg);border-radius:0 4px 4px 0}
.qhead{cursor:pointer;list-style:none;font-size:.64rem;letter-spacing:.06em;text-transform:uppercase;color:var(--verd);font-weight:600;margin-bottom:.4rem}
.quoted summary::-webkit-details-marker{display:none}
.quoted[open] .qhead{margin-bottom:.5rem}
.quoted .aya{font-size:1.05rem;line-height:1.9;margin:.2rem 0 .5rem}
.gsw{margin-left:auto;font-size:.78rem;color:var(--mut);display:flex;
 gap:.3rem;align-items:center;white-space:nowrap;padding:.45rem .2rem;
 cursor:pointer}
@media (max-width:560px){.gsw{margin-left:0}}
.ct .who{color:var(--mut);font-size:.86rem}
.cite{margin-left:auto;font-size:.78rem;color:var(--faint);
 font-variant-numeric:tabular-nums}
.txt p{margin:0 0 .55rem;font-size:1.1rem;line-height:1.95;color:var(--ink)}
.txt p:last-child{margin:0}
.attrib{margin-top:.6rem;padding-top:.5rem;border-top:1px solid var(--soft);
 font-size:.7rem;color:var(--faint)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));
 gap:.4rem}
.slot{background:var(--surf);border:1px solid var(--rule);border-radius:3px;
 padding:.5rem .65rem}
.slot .k{font-size:.68rem;text-transform:uppercase;letter-spacing:.05em;
 color:var(--faint)}
.slot .v{font-size:1.25rem;color:var(--ink)}
.slot.unv{border-color:var(--och)}
.slot.unv .v{color:var(--och)}
.slot.ref{border-color:var(--mad);border-style:dashed}
.slot .why{font-size:.74rem;color:var(--mad);margin-top:.25rem}
.slot .note{font-size:.74rem;color:var(--mut);margin-top:.25rem}
.slot .att{font-size:.68rem;color:var(--faint);margin-top:.3rem;
 padding-top:.3rem;border-top:1px solid var(--soft);line-height:1.5}
.slot .att.ok{color:var(--verd)}
.slot .att.sk{color:var(--och)}
.slot .att i{font-style:normal;opacity:.75}
.aya{font-size:1.2rem;line-height:2.1;color:var(--ink);margin:.2rem 0 .5rem;padding:.5rem .7rem;background:var(--surf);border-radius:4px;border:1px solid var(--rule)}
.tr{direction:rtl;text-align:right;font-size:1rem;line-height:2;color:var(--body);margin:0 0 .6rem;padding:.5rem .7rem;border-right:2px solid var(--verd);background:var(--surf)}
.tr.ur{font-family:"Noto Nastaliq Urdu","Jameel Noori Nastaleeq","Awami Nastaliq",serif;line-height:2.6}
.tr .by{display:block;margin-top:.35rem;font-size:.68rem;color:var(--faint);direction:ltr;text-align:left;font-family:inherit}
.ayahead{display:flex;gap:.7rem;align-items:baseline;margin:1rem 0 .4rem}
.ayahead b{color:var(--verd);font-variant-numeric:tabular-nums}
.ayahead .ar{font-size:1.15rem;color:var(--ink)}
.tocbk{margin:.7rem 0 .3rem;color:var(--mut);font-size:.8rem}
.tocbk b{color:var(--ink)}
.toclist{display:flex;flex-wrap:wrap;gap:.3rem}
.toclist a{font-size:.95rem;text-decoration:none;color:var(--ink);background:var(--surf);border:1px solid var(--rule);border-radius:3px;padding:.15rem .45rem;direction:rtl}
.toclist a small{color:var(--faint);font-size:.62rem;direction:ltr;margin-inline-start:.35rem}
.tabs{display:flex;gap:.3rem;margin:0 0 1.2rem;flex-wrap:wrap;align-items:center;border-bottom:1px solid var(--rule)}
.tabs button{font:inherit;font-size:.82rem;padding:.45rem .8rem;border:0;border-bottom:2px solid transparent;background:none;color:var(--mut);cursor:pointer}
.tabs button.on{color:var(--ink);border-bottom-color:var(--verd);font-weight:600}
.pk{max-width:940px;margin:0 auto;display:flex;gap:.4rem;align-items:center;flex-wrap:wrap;padding:.6rem 1.1rem .2rem}
.pk .lbl{font-size:.68rem;text-transform:uppercase;letter-spacing:.07em;color:var(--faint)}
.pk select{font-size:1.2rem;font-family:inherit;padding:.15rem .3rem;border:1px solid var(--rule);border-radius:3px;background:var(--bg);color:var(--ink);min-width:3.4rem;text-align:center}
.pk button{font:inherit;font-size:.8rem;padding:.25rem .6rem;border-radius:3px;border:1px solid var(--rule);background:var(--surf);color:var(--ink);cursor:pointer}
.pk button:disabled{opacity:.4;cursor:default}
.pk .pkn{font-size:.74rem;color:var(--mut);margin-inline-start:.3rem}
.pklist{max-width:940px;margin:0 auto;padding:.2rem 1.1rem .6rem;display:flex;gap:.35rem;flex-wrap:wrap}
.pklist a{font-size:1.05rem;text-decoration:none;color:var(--ink);background:var(--surf);border:1px solid var(--rule);border-radius:3px;padding:.1rem .45rem;direction:rtl}
.pklist a small{color:var(--faint);font-size:.66rem;direction:ltr;margin-inline-start:.3rem}
#pick{font:inherit;font-size:.95rem;padding:.3rem .55rem;border-radius:3px;border:1px solid var(--rule);background:var(--surf);color:var(--ink);cursor:pointer;direction:rtl}
details.fold{margin:1.6rem 0 .6rem;border-top:1px solid var(--rule);padding-top:.7rem}
details.fold>summary{cursor:pointer;font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;color:var(--faint);font-weight:600;list-style:none}
details.fold>summary::-webkit-details-marker{display:none}
details.fold>summary::before{content:'\25b8  ';color:var(--verd)}
details.fold[open]>summary::before{content:'\25be  '}
h3{font-size:.78rem;text-transform:uppercase;letter-spacing:.08em;
 color:var(--mut);margin:1.1rem 0 .45rem;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:.9rem}
.tw{overflow-x:auto;border:1px solid var(--rule);border-radius:4px}
th,td{text-align:left;padding:.4rem .7rem;border-bottom:1px solid var(--soft)}
th{font-size:.66rem;text-transform:uppercase;letter-spacing:.08em;
 color:var(--faint);background:var(--surf)}
tr:last-child td{border:none}
.srcsel{display:flex;gap:.5rem;flex-wrap:wrap;margin:.2rem 0 1rem}
.srcsel label{font-size:.8rem;color:var(--mut);display:flex;gap:.28rem;
 align-items:center;background:var(--surf);border:1px solid var(--rule);
 border-radius:3px;padding:.2rem .5rem;cursor:pointer}
.msg{padding:3rem 1rem;text-align:center;color:var(--mut)}
.msg b{display:block;font-size:1.15rem;color:var(--ink);margin-bottom:.4rem}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style></head><body>
<header><div class="bar">
 <div class="brand">Lughat<small>approved sources only</small></div>
 <input type="search" id="q" placeholder="a word or a root &mdash; سكن, مساكين, qwl"
        autocomplete="off" autofocus>
  <button id="pick" type="button" title="choose the radicals">ف ع ل</button>
</div></header>
<div id="picker" hidden><div class="pk">
  <span class="lbl">root letters</span>
  <select id="r1"></select><select id="r2"></select><select id="r3"></select>
  <select id="r4"></select>
  <span class="pkn" id="pkn"></span>
  <button id="pkgo" type="button" disabled>open</button>
  <button id="pkclr" type="button">clear</button>
</div><div class="pklist" id="pklist"></div></div>
<main id="m"><div class="msg">Type a Qur'anic word or a root.</div></main>
<script>
function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,c=>
 ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
let HIDDEN=new Set();
try{HIDDEN=new Set(JSON.parse(localStorage.getItem("lughat.hidden")||"[]"));}
catch(e){}
function saveHidden(){try{localStorage.setItem("lughat.hidden",
 JSON.stringify([...HIDDEN]));}catch(e){}}
let DATA=null;
async function go(){
 const t=document.getElementById("q").value.trim();
 const m=document.getElementById("m");
 if(!t){m.innerHTML='<div class="msg">Type a Qur\'anic word or a root.</div>';return;}
 m.innerHTML='<div class="msg">looking&hellip;</div>';
 const r=await fetch("/api/read?q="+encodeURIComponent(t)).then(x=>x.json());
 DATA=r;draw();
}
// ---- the radical picker -------------------------------------------------
// Built from the corpus's own root list, so every letter it offers leads to
// a root that exists. Offering the alphabet would let you build ط ظ ء and
// land on "this root does not occur" -- true, and useless.
let ROOTS=null;
const PK=["r1","r2","r3","r4"];
function pkSel(){return PK.map(id=>document.getElementById(id).value);}
function pkMatch(){
 const v=pkSel();
 return (ROOTS||[]).filter(x=>{
  const L=[...x.r];
  if(v[3] && L.length!==4) return false;
  for(let i=0;i<4;i++) if(v[i] && L[i]!==v[i]) return false;
  return true;});
}
function pkFill(){
 const v=pkSel();
 for(let i=0;i<4;i++){
  const sel=document.getElementById(PK[i]);
  // the options for slot i are the letters that actually occur there among
  // the roots still matching every OTHER slot
  const kept=(ROOTS||[]).filter(x=>{
   const L=[...x.r];
   if(v[3] && L.length!==4 && i!==3) return false;
   for(let j=0;j<4;j++) if(j!==i && v[j] && L[j]!==v[j]) return false;
   return true;});
  const letters=[...new Set(kept.map(x=>[...x.r][i]).filter(Boolean))].sort();
  const cur=v[i];
  sel.innerHTML='<option value="">'+(i===3?"—":"?")+'</option>'+
   letters.map(l=>'<option value="'+l+'"'+(l===cur?" selected":"")+'>'+l+
     '</option>').join("");
  if(cur&&!letters.includes(cur)) sel.value="";
 }
 const m=pkMatch(), chosen=pkSel().filter(Boolean).length;
 document.getElementById("pkn").textContent=
   chosen? m.length+(m.length===1?" root":" roots"):"1642 roots";
 document.getElementById("pkgo").disabled=!(m.length===1||chosen>=3);
 const list=document.getElementById("pklist");
 list.innerHTML=(chosen&&m.length<=60)
  ? m.map(x=>'<a href="?q='+encodeURIComponent(x.r)+'">'+esc(x.r)+
      '<small>'+x.n+'</small></a>').join("")
  : "";
}
async function pkInit(){
 if(ROOTS) return;
 ROOTS=(await fetch("/api/roots").then(x=>x.json())).roots;
 for(const id of PK)
  document.getElementById(id).addEventListener("change",pkFill);
 document.getElementById("pkgo").addEventListener("click",()=>{
  const m=pkMatch();
  if(m.length) location.search="?q="+encodeURIComponent(m[0].r);});
 document.getElementById("pkclr").addEventListener("click",()=>{
  for(const id of PK) document.getElementById(id).value="";
  pkFill();});
 pkFill();
}
document.getElementById("pick").addEventListener("click",async()=>{
 const box=document.getElementById("picker");
 box.hidden=!box.hidden;
 if(!box.hidden) await pkInit();
});

// ---- Ibn Jinni's own table of contents ---------------------------------
let TOC=null;
async function tocOpen(){
 const body=document.getElementById("tocbody");
 if(!TOC) TOC=(await fetch("/api/jinni").then(x=>x.json())).books;
 let o='<input id="tocq" type="search" placeholder="filter his chapter '+
  'titles" style="width:100%;max-width:22rem;margin:.4rem 0">';
 for(const bk of TOC){
  o+='<div class="tocbk"><b>'+esc(bk.title)+'</b> &mdash; keyed by '+
    esc(bk.keyed_by)+'</div>';
  if(!bk.chapters.length){
   o+='<div class="card empty">'+(bk.pending
     ? 'Nothing approved yet &mdash; '+bk.pending+' chapter'+
       (bk.pending==1?" is":"s are")+' ingested and awaiting review.'+
       '<div class="how">To decide them now:<code>python3 lughat.py '+
       'review --source='+esc(bk.key)+'</code></div>'
     : 'No chapter of this book is ingested.')+'</div>';
   continue;}
  o+='<div class="toclist">'+bk.chapters.map(c=>
    '<a href="#" data-id="'+c.id+'" class="ar">'+esc(c.head)+
    '<small>'+esc(c.vol)+'/'+esc(c.page)+'</small></a>').join("")+'</div>';
 }
 o+='<div id="tocone"></div>';
 body.innerHTML=o;
 const filt=document.getElementById("tocq");
 filt.addEventListener("input",()=>{
  const v=filt.value.trim();
  body.querySelectorAll(".toclist a").forEach(a=>{
   a.style.display=(!v||a.textContent.includes(v))?"":"none";});});
 body.querySelectorAll(".toclist a").forEach(a=>
  a.addEventListener("click",async ev=>{
   ev.preventDefault();
   const d=await fetch("/api/jinni?id="+encodeURIComponent(a.dataset.id))
     .then(x=>x.json());
   const c=d.chapter;
   document.getElementById("tocone").innerHTML=c
    ? '<div class="card"><div class="ct"><b>'+esc(c.title)+'</b>'+
      '<span class="who ar">'+esc(c.head)+'</span>'+
      '<span class="cite">vol '+esc(c.vol)+' p. '+esc(c.page)+'</span></div>'+
      '<div class="txt ar">'+c.lines.map(l=>"<p>"+esc(l)+"</p>").join("")+
      '</div><div class="attrib">'+esc(c.attribution)+'</div></div>'
    : '<div class="card empty">'+esc(d.error||"not available")+'</div>';}));
}

function att(f){
 // EXACT is attestation; SKELETON is a DIFFERENT WORD and is labelled so.
 let o='';
 if(f.exact&&f.exact.length){
  o+='<div class="att ok">attested: '+f.exact.map(x=>'<span class="ar">'+
   esc(x.form)+'</span> '+esc(x.ref)+' <i>'+esc(x.tag)+'</i>').join(" &middot; ")
   +'</div>';}
 else if(f.exact) o+='<div class="att">not found in the corpus</div>';
 if(f.skeleton&&f.skeleton.length)
  o+='<div class="att sk">'+
   'same skeleton, different vowels &mdash; NOT attestation: '+f.skeleton.map(x=>'<span class="ar">'+esc(x.form)+
   '</span> '+esc(x.ref)+' <i>'+esc(x.tag)+'</i>').join(" &middot; ")+'</div>';
 if(f.n_dropped) o+='<div class="att">+'+f.n_dropped+' more not shown ('+
  f.n_dropped_exact+' of them exact)</div>';
 return o;}

const VIEWS=[["dict","Dictionary"],["jinni","Ishtiqāq — Ibn Jinnī"],
              ["quran","Qur’an"],["syn","Synonyms"]];
let VIEW=(()=>{try{return localStorage.getItem("lughat.view")||"dict";}
              catch(e){return "dict";}})();
let GLOSS=(()=>{try{return localStorage.getItem("lughat.gloss")==="1";}
                catch(e){return false;}})();
// A FUNCTION, not a const. As a const this was a snapshot taken once at
// load, so every redraw re-inserted the switch in its ORIGINAL state: GLOSS
// flipped and the Urdu appeared, but the box drew itself unchecked again a
// moment later, which reads as a control that does nothing.
function tabbar(){
 return '<nav class="tabs">'+VIEWS.map(v=>
  '<button data-v="'+v[0]+'">'+v[1]+'</button>').join("")+
  '<label class="gsw" title="machine-translated Urdu beside the Arabic">'+
  '<input type="checkbox" id="gsw"'+(GLOSS?" checked":"")+'> Urdu</label>'+
  '</nav>';
}

// MACHINE URDU. Rendered OUTSIDE the card, because the card's border is this
// page's one visual promise -- verbatim, cited -- and no machine's output may
// borrow it. Off unless switched on, and labelled every time it appears: a
// label shown once at the top of a long page is a label the reader scrolls
// past and then forgets while reading the thing it qualifies.
function quotedBlock(e){
 if(!GLOSS) return "";
 const Q=e.quoted||{}; const ks=Object.keys(Q);
 if(!ks.length) return "";
 let h="";
 for(const k of ks) for(const q of Q[k]){
  // the ayah is OUR mushaf text and the Urdu is a NAMED translator's, so
  // this block carries an attribution and the machine block cannot
  // FOLDED. An ayah is long -- 2:102 alone outruns the article quoting it --
  // and 41 of them opened at once on ع ل م buried the scholar's own words,
  // which is the same mistake the sarf grid made before it was folded. The
  // summary still names the ayah, so nothing is hidden, only closed.
  h+='<details class="quoted"><summary class="qhead">Qur\u2019\u0101n '+
   esc(q.ref)+' &mdash; quoted here'+
   ((q.translations||[]).length?', with '+esc(q.translations[0].author):'')+
   '</summary>'+
   '<div class="aya ar">'+esc(q.ayah)+'</div>';
  for(const t of (q.translations||[])){
   if(HIDDEN.has(t.key)) continue;
   h+='<div class="tr ur">'+esc(t.text)+'<span class="by">'+esc(t.title)+
    ' &middot; '+esc(t.author)+'</span></div>';}
  h+='</details>';
 }
 return h;
}

function glossBlock(e){
 if(!GLOSS) return "";
 const g=e.gloss||{}, ks=Object.keys(g);
 if(!ks.length) return "";
 const eng=g[ks[0]];
 let h='<div class="gloss"><div class="glosshead">MACHINE TRANSLATION'+
  ' &mdash; not a source, not checked by anyone &middot; '+
  esc(eng.engine)+' '+esc(eng.model)+'</div>';
 // paragraph indices line up with e.lines, so the two can be read against
 // each other; a paragraph with no gloss is left out rather than blanked
 for(let i=0;i<e.lines.length;i++)
  if(g[i]) h+='<p class="ur">'+esc(g[i].text)+'</p>';
 return h+'</div>';
}

function showView(v){
 VIEW=v;
 try{localStorage.setItem("lughat.view",v);}catch(e){}
 document.querySelectorAll("[data-view]").forEach(
   s=>{s.hidden=s.dataset.view!==v;});
 document.querySelectorAll(".tabs button").forEach(
   b=>b.classList.toggle("on",b.dataset.v===v));
}

function draw(){
 const r=DATA,m=document.getElementById("m");
 if(!r) return;
 if(r.error){m.innerHTML='<div class="msg"><b>'+esc(r.error)+'</b></div>';return;}
 if(r.absent){m.innerHTML='<div class="msg"><b class="ar">'+esc(r.query)+
  '</b>This root does not occur in the Quranic Arabic Corpus. That is a fact '+
  'about the corpus, not about Arabic, and this tool will not supply the '+
  'difference.</div>';return;}
 let h='<div class="head"><h1 class="ar">'+esc(r.letters.join(" "))+'</h1>'+
  '<span class="cls">'+esc(r.classification)+' &middot; '+r.n_segments+
  ' segments &middot; '+r.n_lemmas+' lemmas</span>';
 h+= r.bab ? '<span class="pill ok">bab '+r.bab+' &middot; sourced</span>'
           : '<span class="pill no">bab unsourced</span>';
 h+='</div>';
 if(r.bab_evidence) h+='<div class="cls" style="margin:-.5rem 0 1rem">'+
   'bab evidence: <span class="ar">'+esc(r.bab_evidence)+'</span></div>';

 // ---- three views, because the three questions are different and the
 // books answering them are keyed differently: a dictionary by ROOT, Ibn
 // Jinni by LETTER and by TOPIC, the mushaf by AYAH.
 h+='<section data-view="dict">';
 h+='<h2>Dictionaries</h2><div class="srcsel">';
 for(const c of r.cards.concat(r.tafsir_sources||[]))
  h+='<label><input type="checkbox" data-k="'+esc(c.key)+
  '"'+(HIDDEN.has(c.key)?"":" checked")+'> '+esc(c.title)+'</label>';
 h+='</div>';
 for(const c of r.cards){
  if(HIDDEN.has(c.key)) continue;
  if(!c.entries.length){
   h+='<div class="card empty"><div class="ct"><b>'+esc(c.title)+'</b>'+
    '<span class="who">'+esc(c.author)+'</span></div>'+
    (c.pending? 'Nothing approved yet &mdash; '+c.pending+
       ' entr'+(c.pending==1?"y":"ies")+' for this root '+
       (c.pending==1?"is":"are")+' ingested and awaiting review, so '+
       (c.pending==1?"it is":"they are")+' not shown.'+
       '<div class="how">To decide them now:<code>python3 lughat.py '+
       'review --root='+esc(r.root)+'</code>or open the review page and '+
       'type the root into its filter box.</div>'
     : 'This source has no entry for this root.')+'</div>';
   continue;}
  for(const e of c.entries){
   h+='<div class="card"><div class="ct"><b>'+esc(c.title)+'</b>'+
    '<span class="who">'+esc(c.author)+'</span>'+
    (e.extraction&&e.extraction!=="direct"
      ? '<span class="pill no">root inferred: '+esc(e.extraction)+'</span>':'')+
    (e.bulk? '<span class="pill warn" title="approved as part of a class, '+
      'not read one at a time">bulk-approved</span>':'')+
    '<span class="cite">vol '+esc(e.vol)+' p. '+esc(e.page)+'</span></div>'+
    '<div class="txt ar">'+e.lines.map(l=>"<p>"+esc(l)+"</p>").join("")+'</div>'+
    '<div class="attrib">'+esc(c.attribution)+'</div></div>'+glossBlock(e)+quotedBlock(e);}
 }

 h+='<h2>Synonyms and opposites</h2>';
 h+='<h3>What separates two near-synonyms &mdash; al-‘Askarī</h3>';
 if(!r.furuq.hits.length){
  h+='<div class="card empty">'+(r.furuq.pending
    ? 'Nothing approved yet &mdash; '+r.furuq.pending+' of al-‘Askarī’s '+
      'chapters are ingested and awaiting review, so they were not '+
      'searched.<div class="how">To decide them now:<code>python3 '+
      'lughat.py review</code></div>'
    : 'No chapter of al-‘Askarī names a word of this root.')+'</div>';}
 else{
  h+='<div class="cls" style="margin:0 0 .6rem">'+esc(r.furuq.rule)+'</div>';
  for(const x of r.furuq.hits)
   h+='<div class="card"><div class="ct"><b>'+esc(x.title)+'</b>'+
    '<span class="who">'+esc(x.author)+'</span>'+
    '<span class="cite">vol '+esc(x.vol)+' p. '+esc(x.page)+'</span></div>'+
    '<div class="ar" style="font-size:1.1rem;margin-bottom:.4rem">'+
    esc(x.heading)+'</div>'+
    '<div class="txt ar">'+x.lines.map(l=>"<p>"+esc(l)+"</p>").join("")+
    '</div><div class="attrib">'+esc(x.attribution)+'</div></div>';
  if(r.furuq.more) h+='<div class="cls">'+r.furuq.more+' further chapter'+
   (r.furuq.more==1?"":"s")+' matched and were not shown.</div>';
 }

 h+='<h3>Where a lexicographer states an opposition</h3>';
 h+='<div class="card empty ref">'+esc(r.opposites.refusal)+'</div>';
 if(!r.opposites.hits.length)
  h+='<div class="card empty">No approved article on this root contains '+
   esc(r.opposites.words.join(", "))+'.</div>';
 for(const x of r.opposites.hits)
  h+='<div class="card"><div class="ct"><b>'+esc(x.title)+'</b>'+
   '<span class="who">'+esc(x.author)+'</span>'+
   '<span class="pill ok">'+esc(x.word)+'</span>'+
   '<span class="cite">vol '+esc(x.vol)+' p. '+esc(x.page)+'</span></div>'+
   '<div class="txt ar"><p>'+esc(x.text)+'</p></div>'+
   '<div class="attrib">'+esc(x.attribution)+'</div></div>';
 if(r.opposites.more) h+='<div class="cls">'+r.opposites.more+
  ' further sentence'+(r.opposites.more==1?"":"s")+' matched.</div>';

// Ibn Jinni: the letters of the root, then its permutations,
 // then the books that only mention it.
 h+='</section><section data-view="jinni">';
 h+='<h2>Ishtiqāq &mdash; Ibn Jinnī</h2>';
 // His books are not keyed by root, so they are also enterable the way he
 // wrote them: Sirr by LETTER, al-Khasa'is by TOPIC.
 h+='<details class="fold" id="toc"><summary>Browse his chapters &mdash; '+
  'by letter (Sirr) and by topic (al-Khaṣāʾiṣ)</summary>'+
  '<div id="tocbody" class="cls">loading&hellip;</div></details>';
 h+='<h3>The letters of the root</h3>';
 for(const L of r.letter_cards){
  if(!L.entries.length){
   h+='<div class="card empty"><div class="ct"><b class="ar">'+esc(L.letter)+
    '</b><span class="who">'+esc(L.name)+'</span></div>'+
    'Not approved, or absent from this witness.</div>';continue;}
  for(const e of L.entries)
   h+='<div class="card"><div class="ct"><b class="ar">'+esc(L.letter)+'</b>'+
    '<span class="who">'+esc(e.title)+'</span>'+
    '<span class="cite">vol '+esc(e.vol)+' p. '+esc(e.page)+'</span></div>'+
    '<div class="txt ar">'+e.lines.map(l=>"<p>"+esc(l)+"</p>").join("")+'</div>'+
    '<div class="attrib">'+esc(e.attribution)+'</div></div>'+glossBlock(e)+quotedBlock(e);
 }

 if(r.tafsir&&r.tafsir.length){
  if(r.akbar&&r.akbar.length){
  h+='<h3>Ishtiqāq akbar &mdash; the six permutations</h3><div class="grid">';
  for(const p of r.akbar)
   h+='<div class="slot"><div class="k">'+(p.self?"this root":"permutation")+
    '</div><div class="v ar">'+esc(p.root)+'</div><div class="note">'+
    (p.n? p.n+(p.n==1?" segment":" segments")+" in the Qur’an"
      :"does not occur")+'</div></div>';
  h+='</div><div class="card empty ref">'+esc(r.akbar_refusal)+'</div>';}

 for(const b of r.passages||[]){
  h+='<h3>'+esc(b.title)+' &mdash; search, not an article</h3>';
  h+='<div class="card empty ref">'+esc(b.refusal)+'</div>';
  h+='<div class="cls" style="margin:.5rem 0 .7rem">'+esc(b.rule)+'</div>';
  if(!b.hits.length){
   h+='<div class="card empty">'+(b.pending
     ? 'Nothing approved yet &mdash; '+b.pending+' chapter'+
       (b.pending==1?" of this book is":"s of this book are")+
       ' ingested and awaiting review, so '+
       (b.pending==1?"it was":"they were")+' not searched.'+
       '<div class="how">To decide them now:<code>python3 lughat.py '+
       'review</code>and use the review page\'s filter.</div>'
     : 'No passage in the approved text matches this root.')+'</div>';
   continue;}
  for(const x of b.hits)
   h+='<div class="card"><div class="ct"><b>'+esc(b.title)+'</b>'+
    '<span class="who ar">'+esc(x.chapter)+'</span>'+
    '<span class="cite">vol '+esc(x.vol)+' p. '+esc(x.page)+'</span></div>'+
    '<div class="txt ar"><p>'+esc(x.text)+'</p></div>'+
    '<div class="attrib">'+esc(b.attribution)+'</div></div>';
  if(b.more) h+='<div class="cls">'+b.more+' further passage'+
   (b.more==1?"":"s")+' matched and were not shown.</div>';
 }

 h+='<details class="fold"><summary>Ishtiqāq ṣaghīr &mdash; the derived forms, with their refusals</summary>';
 for(const sec of r.sarf){
  h+='<h3>'+esc(sec.title)+(sec.hypothetical
    ? ' <span class="pill no">hypothetical &mdash; the bab is not sourced</span>'
    : '')+'</h3>';
  if(sec.condition) h+='<div class="cls">'+esc(sec.condition)+'</div>';
  h+='<div class="grid">';
  for(const f of sec.forms){
   if(f.refused){h+='<div class="slot ref"><div class="k">'+esc(f.slot)+
    '</div><div class="why">'+esc(f.refused)+'</div></div>';continue;}
   h+='<div class="slot'+(f.verified?"":" unv")+'"><div class="k">'+esc(f.slot)+
    (f.verified?"":" &mdash; unverified")+'</div><div class="v ar">'+
    esc(f.text)+'</div>'+
    (f.caveats||[]).map(c=>'<div class="why">! '+esc(c)+'</div>').join("")+
    (f.notes||[]).map(c=>'<div class="note">? '+esc(c)+'</div>').join("")+
    att(f)+'</div>';}
  h+='</div>';
 }

 h+='</details>';
 h+='</section><section data-view="quran">';
 if((r.translations||[]).length){
  h+='<div class="srcsel">';
  for(const c of r.translations)
   h+='<label><input type="checkbox" data-k="'+esc(c.key)+
   '"'+(HIDDEN.has(c.key)?"":" checked")+'> '+esc(c.title)+'</label>';
  h+='</div>';
 }
 h+='<h2>Tafsir</h2><div class="cls" style="margin:-.3rem 0 .6rem">'+
  'on the āyāt where this root occurs</div>';
  for(const a of r.tafsir){
   h+='<div class="ayahead"><b>'+esc(a.ref)+'</b><span class="ar">'+
    esc(a.word)+'</span></div>';
   if(a.aya_text) h+='<div class="aya ar">'+esc(a.aya_text)+'</div>';
   for(const t of (a.translations||[])){
    if(HIDDEN.has(t.key)) continue;
    h+='<div class="tr'+(t.key.startsWith("ur")?" ur":"")+'">'+esc(t.text)+
     '<span class="by">'+esc(t.title)+' &middot; '+esc(t.author)+'</span>'+
     '</div>';}
   const shown=a.passages.filter(x=>!HIDDEN.has(x.key));
   if(!shown.length){
    h+='<div class="card empty">'+(a.pending
      ? 'Nothing approved yet &mdash; '+a.pending+' passage'+
        (a.pending==1?" covering this āyah is":"s covering this āyah are")+
        ' ingested and awaiting review, so '+
        (a.pending==1?"it is":"they are")+' not shown.'+
        '<div class="how">To decide them now:<code>python3 lughat.py '+
        'review --tafsir</code></div>'
      : (a.passages.length? 'Every source covering this āyah is switched off.'
         : 'No ingested commentary covers this āyah.'))+'</div>';
    continue;}
   for(const x of shown)
    h+='<div class="card"><div class="ct"><b>'+esc(x.title)+'</b>'+
     '<span class="who">'+esc(x.author)+'</span>'+
     '<span class="pill ok">on '+esc(x.span)+'</span>'+
     '<span class="cite">vol '+esc(x.vol)+' pp. '+esc(x.page)+'</span></div>'+
     '<div class="cls" style="font-size:.72rem;margin:-.3rem 0 .5rem">'+
     'anchor: '+esc(x.anchor)+'</div>'+
     '<div class="txt ar">'+x.lines.map(l=>"<p>"+esc(l)+"</p>").join("")+
     '</div><div class="attrib">'+esc(x.attribution)+'</div></div>';
  }
  if(r.tafsir_more) h+='<div class="cls">'+r.tafsir_more+
   ' further āyah'+(r.tafsir_more==1?"":"s")+' contain this root and were '+
   'not listed here; the table below has them all.</div>';
 }

 h+='<h2>In the Qur’an</h2><div class="tw"><table><thead><tr>'+
  '<th>lemma</th><th>pos</th><th>count</th><th>first</th></tr></thead><tbody>';
 for(const l of r.lemmas)
  h+='<tr><td class="ar">'+esc(l.lemma)+'</td><td>'+esc(l.pos)+'</td><td>'+
   l.n+'</td><td class="ar">'+esc(l.form)+'</td></tr>';
 h+='</tbody></table></div></section>';

 // ---- Synonyms: Kilani, whose words are never shown ------------------
 h+='<section data-view="syn">';
 const S=r.synonyms||{};
 h+='<h2>Synonyms &mdash; Kīlānī</h2>';
 if(!S.present){
  h+='<div class="msg">This source is not loaded. <code>lughat.py ingest '+
   'mutaradifaat --from data/mutaradifaat/ocr/pages.json</code></div>';
 }else{
  h+='<div class="cls" style="margin:-.3rem 0 .6rem">'+esc(S.title)+
   ' &middot; '+esc(S.author)+'</div>';
  // Two refusals, both stated before any result -- the reader must know what
  // this card is NOT before reading what it is.
  h+='<div class="refuse"><b>Not his words.</b> '+esc(S.not_quoted)+'</div>';
  h+='<div class="refuse"><b>Keyed by '+esc(S.keyed_by)+'.</b> '+
   esc(S.no_urdu)+'</div>';
  if(S.covers && S.covers.n){
   h+='<div class="cls">Approved coverage: printed pp. '+S.covers.lo+'&ndash;'+
    S.covers.hi+' ('+S.covers.n+' entries) of a 1,026-page book.</div>';
  }
  if(!S.entries.length){
   h+='<div class="msg">No entry of Kīlānī is filed under <b class="ar">'+
    esc(r.root)+'</b>. That means this root was not confirmed on any '+
    'OCR&rsquo;d page &mdash; not that the book is silent on it: '+
    (S.covers && S.covers.n ? 'only pp. '+S.covers.lo+'&ndash;'+S.covers.hi+
     ' have been OCR&rsquo;d and approved.' : 'nothing has been approved yet.')+
    (S.pending ? ' '+S.pending+' entries are waiting on review: <code>'+
     'lughat.py review --source=mutaradifaat</code>' : '')+'</div>';
  }
  for(const e of S.entries){
   h+='<div class="card"><div class="ct"><b>Entry on <span class="ar">'+
    esc(r.root)+'</span></b><span class="cite">printed p. '+esc(e.page)+
    ' &middot; '+esc(e.scan)+'</span></div>';
   h+='<div class="cls" style="font-size:.72rem;margin:-.2rem 0 .5rem">'+
    (e.page_read
      ? 'page number read off the page&rsquo;s own header'
      : 'page number DERIVED, not read &mdash; '+esc(e.page_method))+
    '</div>';
   h+='<div class="cls">Filed here because two facts agree: the entry&rsquo;s '+
    'headword carries these radicals, and the āyāt this page quotes contain '+
    'this root. The āyāt below are <b>this program&rsquo;s</b> muṣḥaf text, '+
    'not the scan&rsquo;s.</div>';
   for(const a of (e.ayat||[]))
    h+='<div class="ayahead"><b>'+esc(a.ref)+'</b></div>'+
     '<div class="aya ar">'+esc(a.text)+'</div>';
   h+='</div>';
  }
 }
 h+='</section>';
 m.innerHTML=tabbar()+h;
 showView(VIEW);
 const toc=document.getElementById("toc");
 if(toc) toc.addEventListener("toggle",()=>{if(toc.open)tocOpen();});
 m.querySelectorAll(".tabs button").forEach(b=>
  b.addEventListener("click",()=>showView(b.dataset.v)));
 const gs=document.getElementById("gsw");
 if(gs) gs.addEventListener("change",()=>{
  GLOSS=gs.checked;
  try{localStorage.setItem("lughat.gloss",GLOSS?"1":"0");}catch(e){}
  draw();showView(VIEW);});
 m.querySelectorAll(".srcsel input[type=checkbox]").forEach(cb=>{
  cb.addEventListener("change",()=>{
   const k=cb.dataset.k;
   if(cb.checked)HIDDEN.delete(k);else HIDDEN.add(k);
   saveHidden();draw();});});
}
let t=null;
const box=document.getElementById("q");
box.addEventListener("input",()=>{clearTimeout(t);t=setTimeout(()=>{
 const v=box.value.trim();
 // keep the URL in step so a lookup can be bookmarked or linked
 try{history.replaceState(null,"",v?"?q="+encodeURIComponent(v):"/");}catch(e){}
 go();},220);});
const q0=new URLSearchParams(location.search).get("q");
if(q0){box.value=q0;go();}
</script></body></html>
"""

READ_PORT = 8766


GLOSS_IS_A_MACHINE = (
    "MACHINE TRANSLATION. No translator wrote this and nobody has checked "
    "it. It was produced by a neural model run over the Arabic beside it, "
    "offline, in the build path -- this program does not translate anything "
    "while you read. It is a reading aid and it is NOT evidence: where it "
    "disagrees with the Arabic, the Arabic is what the scholar wrote. These "
    "texts are 10th-century technical prose, which is the register machine "
    "translation is worst at, so expect it to be fluent and wrong rather "
    "than obviously broken.")


def entry_glosses(conn, entry_id, lang="ur"):
    """Machine Urdu for one entry, as {paragraph index: {...}}.

    Read through `q` like everything else on the query path. These rows are
    NOT gated by verified: the gate means "a person vouched for this source",
    and nobody vouches for a machine's output -- so instead of a review stamp
    they carry the engine and model that produced them, and the page states
    what they are. A row here is never rendered as, beside, or inside a
    sourced string without that statement; see the honesty tests."""
    out = {}
    for g in q(conn, "SELECT para, text, engine, model FROM glosses "
                     "WHERE entry_id=? AND lang=? ORDER BY para",
               (entry_id, lang)):
        out[g["para"]] = {"text": g["text"], "engine": g["engine"],
                          "model": g["model"]}
    return out


def jinni_chapters(conn):
    """Ibn Jinni's own table of contents, for the chapters a person has
    approved.  He is not keyed by root, so this is how his books are
    actually entered: by LETTER in Sirr, by TOPIC in al-Khasa'is."""
    out = []
    for key in ("sirr", "khasais"):
        src = q(conn, "SELECT id, title FROM sources WHERE key=?",
                (key,)).fetchone()
        if src is None:
            continue
        rows = [{"id": e["id"], "head": chapter_label(e["headword"] or ""),
                 "vol": e["vol"], "page": e["page"]}
                for e in q(conn, "SELECT id, headword, vol, page FROM "
                                 "v_entries WHERE source_id=? ORDER BY id",
                           (src["id"],))]
        with unguarded(conn):
            pending = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE source_id=? AND "
                "verified=0 AND rejected=0", (src["id"],)).fetchone()[0]
        out.append({"key": key, "title": src["title"],
                    "keyed_by": KEYED_BY_WORD[LEXICONS[key]["keyed_by"]],
                    "chapters": rows, "pending": pending})
    return out


def jinni_chapter(conn, entry_id):
    """One approved chapter of his, whole."""
    e = q(conn, "SELECT e.*, s.title, s.author, s.attribution FROM v_entries e "
                "JOIN sources s ON s.id = e.source_id WHERE e.id=?",
          (int(entry_id),)).fetchone()
    if e is None:
        return None
    return {"head": chapter_label(e["headword"] or ""), "vol": e["vol"],
            "page": e["page"], "title": e["title"], "author": e["author"],
            "attribution": e["attribution"],
            "lines": render_entry(e["text_raw"] or "")}


def root_inventory(conn):
    """Every root the corpus has, with how often it occurs.

    The picker is built from THIS, not from the alphabet: offering ط ظ ء as a
    third radical when no such root exists would send the reader to a page
    that says the root does not occur -- true, and useless. What the muṣḥaf
    contains is a fact; what it could contain is not this tool's business."""
    return [{"r": r["root_ar"], "n": r["n_segments"]}
            for r in q(conn, "SELECT root_ar, n_segments FROM roots "
                             "ORDER BY root_ar")]


def read_root(conn, query):
    """Everything the reader gets for one word or root. Pure retrieval."""
    letters = canonical_root(query)
    root = "".join(letters)
    rc = RootClass(letters)
    out = {"root": root, "letters": letters, "classification": rc.label(),
           "reasons": rc.reasons, "query": query}

    row = q(conn, "SELECT n_segments, n_lemmas, bab, bab_verified, "
                  "bab_method, bab_evidence FROM roots WHERE root_ar=?",
            (root,)).fetchone()
    if row is None:
        # the word may not be a root -- try it as a word first
        keys = query_keys(query)
        hit = q(conn, "SELECT root_ar FROM segments WHERE (norm_alif IN (%s) "
                      "OR norm_drop IN (%s)) AND root_ar IS NOT NULL LIMIT 1"
                % (",".join("?" * len(keys)), ",".join("?" * len(keys))),
                keys + keys).fetchone()
        if hit:
            return read_root(conn, hit["root_ar"])
        out["absent"] = True
        return out
    out["n_segments"] = row["n_segments"]
    out["n_lemmas"] = row["n_lemmas"]
    out["bab"] = row["bab"] if row["bab_verified"] else None
    out["bab_method"] = row["bab_method"]
    out["bab_evidence"] = row["bab_evidence"]

    # the corpus's own occurrences
    out["lemmas"] = [
        {"lemma": r["lemma_ar"] or "-", "pos": r["pos"] or "-",
         "n": r["n"], "form": r["form_ar"],
         "ref": "%d:%d:%d:%d" % (r["sura"], r["aya"], r["word"], r["seg"])}
        for r in q(conn,
                   "SELECT lemma_ar, pos, COUNT(*) n, "
                   "  MIN(sura) sura, MIN(aya) aya, MIN(word) word, "
                   "  MIN(seg) seg, MIN(form_ar) form_ar "
                   "FROM segments WHERE root_ar=? AND is_stem=1 "
                   "GROUP BY lemma_bw, pos ORDER BY n DESC LIMIT 14", (root,))]

    # the sarf table, with whatever refusals apply
    res = generate(root, bab=out["bab"],
                   bab_source=("mushaf" if out["bab"] else None))
    def _form(f):
        if f.is_refusal:
            return {"slot": f.slot, "refused": f.reason}
        d = {"slot": f.slot, "text": f.text, "verified": f.verified,
             "caveats": list(f.caveats), "notes": list(f.notes)}
        # attestation, ranked before it is capped, and what was capped said
        a = attest(conn, f.text, root)
        d["exact"] = [{"ref": x.ref, "form": x.form_ar, "tag": x.grammar()}
                      for x in a if x.is_attestation][:3]
        d["skeleton"] = [{"ref": x.ref, "form": x.form_ar, "tag": x.grammar()}
                         for x in a if not x.is_attestation][:2]
        d["n_dropped"] = a.n_dropped
        d["n_dropped_exact"] = a.n_dropped_exact
        return d

    out["sarf"] = []
    for sec in res["mujarrad"]:
        out["sarf"].append({
            "title": "bab %d \u2014 %s" % (sec["bab"], sec["name"]),
            "hypothetical": sec["hypothetical"], "condition": sec["condition"],
            "forms": [_form(f) for f in sec["forms"]]})
    if res["mujarrad_derived"]:
        out["sarf"].append({
            "title": "derived from the mujarrad", "hypothetical": False,
            "condition": None,
            "forms": [_form(f) for f in res["mujarrad_derived"]]})
    for sec in res["mazid"]:
        out["sarf"].append({
            "title": "form %s \u2014 %s" % (sec["roman"], sec["name"]),
            "hypothetical": False, "condition": None,
            "forms": [_form(f) for f in sec["forms"]]})

    # ishtiqaq akbar
    out["akbar"] = []
    if len(letters) == 3:
        for perm in ishtiqaq_akbar(conn, root):
            out["akbar"].append({"root": perm.root, "n": perm.n_segments,
                                 "self": perm.is_original})

    # ---- one card per source, EMPTY ONES INCLUDED ----------------------
    out["cards"] = []
    # kind='lexicon' only. A tafsir is keyed by AYAH: it has no article on a
    # root, so an empty card reading "no entry for this root" would be a
    # statement about its contents when the truth is about its organisation
    # -- the same mistake as al-Khasa'is, and it also listed al-Baghawi twice
    # in the source selector, once as a card and once as a tafsir.
    for src in q(conn, "SELECT id, key, title, author, edition, attribution "
                       "FROM sources WHERE kind = 'lexicon' ORDER BY key"):
        # A book not keyed by root gets a SEARCH below, not a card here.  An
        # empty card would say "no entry for this root", which reads as a
        # statement about the book's contents when it is a statement about
        # the book's organisation.
        if not root_keyed(src["key"]):
            continue
        ents = list(q(conn,
                      "SELECT id, text_raw, scan_uri, vol, page, extraction, "
                      "headword, verified_by FROM v_entries WHERE "
                      "source_id=? AND root_ar=? ORDER BY id",
                      (src["id"], root)))
        with unguarded(conn):
            pending = conn.execute(
                "SELECT COUNT(*) n FROM entries WHERE source_id=? AND "
                "root_ar=? AND verified=0 AND rejected=0",
                (src["id"], root)).fetchone()["n"]
        card = {"key": src["key"], "title": src["title"],
                "author": src["author"] or "", "edition": src["edition"] or "",
                "attribution": src["attribution"], "pending": pending,
                "entries": []}
        for e in ents:
            card["entries"].append({
                "headword": e["headword"], "vol": e["vol"], "page": e["page"],
                "extraction": e["extraction"],
                # "a person read this" and "a person accepted the class it
                # belongs to" are different claims, and the reader is told
                # which one they are looking at
                "bulk": e["verified_by"] == "bulk",
                "lines": (render_entry(e["text_raw"])
                          if e["text_raw"] is not None
                          else ["[scan only]", e["scan_uri"] or ""]),
                # kept in its OWN key, never merged into `lines`: a reader
                # and a later maintainer must both be able to see at a glance
                # which strings are the scholar's and which are a machine's.
                "gloss": entry_glosses(conn, e["id"]),
                # where a paragraph QUOTES the Qur'an, this program already
                # holds the ayah and a named translator's Urdu for it. Those
                # beat a machine's rendering of the same words outright, and
                # they carry an attribution, so they are kept apart from the
                # gloss as well as from the scholar's own lines.
                "quoted": (quoted_by_para(conn, e["text_raw"])
                           if e["text_raw"] is not None else {}),
            })
        out["cards"].append(card)

    # Ibn Jinni on each letter is a card too, keyed by letter not root
    letter_cards = []
    for ch in letters:
        ents = letter_entries(conn, ch)
        letter_cards.append({
            "letter": ch, "name": letter_name(ch),
            "entries": [{"lines": render_entry(e["text_raw"])[:3],
                         "vol": e["vol"], "page": e["page"],
                         "title": e["title"], "attribution": e["attribution"],
                         "gloss": entry_glosses(conn, e["id"]),
                         "quoted": quoted_by_para(conn, e["text_raw"])}
                        for e in ents]})
    out["letter_cards"] = letter_cards

    # books organised by topic or by letter: retrieval by string, labelled
    # al-'Askari is not root-keyed either, but he is not searched like the
    # others: his headings name the pair outright, so he gets his own section.
    out["passages"] = []
    for key in sorted(k for k in LEXICONS
                      if not root_keyed(k) and k != "furuq"):
        src = q(conn, "SELECT title, author, attribution FROM sources "
                      "WHERE key=?", (key,)).fetchone()
        if src is None:
            continue
        hits, more, pending = passage_search(conn, key, root)
        out["passages"].append({
            "key": key, "title": src["title"], "author": src["author"],
            "attribution": src["attribution"],
            "refusal": REFUSAL_NOT_KEYED_BY_ROOT % (
                src["title"], KEYED_BY_WORD[LEXICONS[key]["keyed_by"]], root),
            "rule": SEARCH_IS_A_STRING_SEARCH,
            "hits": hits, "more": more, "pending": pending})

    # ---- tafsir: the root's ayat, and what a mufassir says on them -----
    # Ranked by the mushaf's own order and capped, with the cap reported --
    # a silent cap reads as "that is all there is" (trap 10).
    TAF_AYAT = 6
    ayat = list(q(conn, "SELECT sura, aya, MIN(word) w, COUNT(*) n "
                        "FROM segments WHERE root_ar=? AND is_stem=1 "
                        "GROUP BY sura, aya ORDER BY sura, aya", (root,)))
    out["tafsir"] = []
    for a in ayat[:TAF_AYAT]:
        word = q(conn, "SELECT form_ar FROM words WHERE sura=? AND aya=? AND "
                       "word=?", (a["sura"], a["aya"], a["w"])).fetchone()
        rows = tafsir_for_aya(conn, a["sura"], a["aya"])
        with unguarded(conn):
            pend = conn.execute(
                "SELECT COUNT(*) FROM tafsir WHERE sura=? AND aya<=? AND "
                "COALESCE(aya_to, aya)>=? AND verified=0 AND rejected=0",
                (a["sura"], a["aya"], a["aya"])).fetchone()[0]
        out["tafsir"].append({
            "ref": "%d:%d" % (a["sura"], a["aya"]),
            "word": word["form_ar"] if word else "",
            "aya_text": aya_text(conn, a["sura"], a["aya"]),
            "translations": [
                {"key": t["key"], "title": t["title"], "author": t["author"],
                 "text": t["text"], "attribution": t["attribution"]}
                for t in translations_for_aya(conn, a["sura"], a["aya"])],
            "pending": pend,
            "passages": [{
                "key": r["key"], "title": r["title"], "author": r["author"],
                "attribution": r["attribution"],
                "span": ("%d:%d" % (r["sura"], r["aya"])
                         if not r["aya_to"] or r["aya_to"] == r["aya"]
                         else "%d:%d-%d" % (r["sura"], r["aya"], r["aya_to"])),
                "vol": r["vol"],
                "page": (r["page"] if not r["page_to"]
                         else "%s-%s" % (r["page"], r["page_to"])),
                "anchor": r["anchor_evidence"] or r["anchor_method"] or "",
                "lines": render_entry(r["text_raw"])[:6],
            } for r in rows]})
    out["tafsir_more"] = max(0, len(ayat) - TAF_AYAT)
    out["translations"] = [
        {"key": r["key"], "title": r["title"], "author": r["author"]}
        for r in installed_translations(conn)]
    out["translate_refusal"] = REFUSAL_TRANSLATE_MYSELF
    out["tafsir_sources"] = [
        {"key": r["key"], "title": r["title"]}
        for r in q(conn, "SELECT key, title FROM sources WHERE kind='tafsir' "
                         "ORDER BY key")]

    # ---- synonyms and opposites, both quoted ---------------------------
    hits, more, pending = furuq_articles(conn, root)
    out["furuq"] = {"hits": hits, "more": more, "pending": pending,
                    "rule": SEARCH_IS_A_STRING_SEARCH}
    opp, opp_more = opposition_statements(conn, root)
    out["opposites"] = {"hits": opp, "more": opp_more,
                        "refusal": REFUSAL_ANTONYM,
                        "words": list(OPPOSITION_WORDS)}

    out["akbar_refusal"] = REFUSAL_AKBAR_SENSE
    out["synonyms"] = kilani_for_root(conn, root)
    out["gloss_note"] = GLOSS_IS_A_MACHINE
    # engines present for THIS root, so the switch is offered only where it
    # would do something and the reader can see which machine wrote the Urdu
    seen = {}
    for c in out["cards"]:
        for e in c["entries"]:
            for g in e["gloss"].values():
                seen[(g["engine"], g["model"])] = True
    for c in out["letter_cards"]:
        for e in c["entries"]:
            for g in e["gloss"].values():
                seen[(g["engine"], g["model"])] = True
    out["gloss_engines"] = [{"engine": k[0], "model": k[1]} for k in seen]
    return out


REFUSAL_KILANI_NOT_QUOTED = (
    "This book's own words are NOT shown, and cannot be. The scan carries no "
    "text layer, so what exists here is OCR: mean engine confidence 0.483, "
    "and the Urdu in particular comes back wrong (پاکیزہ read as باكيزه). "
    "Even the Arabic is corrupted -- خَاوِيَةٍ read as خَاوِيَتٍ, and the "
    "headword دَابِر read as دَايِر. Rendering any of it as Kilani's prose "
    "would attribute to him words he did not write. So the OCR is kept as a "
    "SEARCH KEY only, and what you see below is this program's own mushaf "
    "text for the ayat the page quotes, plus the page to open in the scan.")

REFUSAL_KILANI_NO_URDU = (
    "Urdu search is NOT available for this book, and the reason is worth "
    "stating: it is arranged BY URDU HEADWORD, and the OCR lost exactly that "
    "key. The engine ran an ARABIC model over Nasta'liq, so only 82 of its "
    "6,585 words came back holding an Urdu-only letter. The book can "
    "therefore be reached only through the Arabic it quotes.")


def kilani_pages(conn):
    """The OCR'd range, read off the ingested rows rather than hardcoded.

    Hardcoding "pp. 378-397" would go stale the day more pages are OCR'd,
    and a stale coverage note reads as a claim about the book."""
    row = q(conn, "SELECT MIN(CAST(page AS INTEGER)) lo, "
                  "MAX(CAST(page AS INTEGER)) hi, COUNT(*) n FROM v_entries "
                  "WHERE source_id=(SELECT id FROM sources WHERE key=?)",
            ("mutaradifaat",)).fetchone()
    return (row["lo"], row["hi"], row["n"]) if row and row["n"] else (None, None, 0)


def _kilani_pending(conn):
    """How many of his entries are still undecided -- a NUMBER, never text.

    Self-contained for the same reason furuq_articles' count is: the one
    unguarded read the reading surface is allowed must sit alone, so that
    what it can reach is obvious by inspection rather than by reading on."""
    with unguarded(conn):
        return conn.execute(
            "SELECT COUNT(*) FROM entries WHERE verified=0 AND rejected=0 "
            "AND source_id=(SELECT id FROM sources WHERE key='mutaradifaat')"
        ).fetchone()[0]


def kilani_for_root(conn, root):
    """Kilani on one root: a page reference and our OWN text, never his.

    He is keyed by Urdu headword, so -- like al-Khasa'is, and for the same
    reason -- he cannot be ASKED about a root and gets no root card. What is
    reported is that a numbered entry of his sits on a page whose quoted ayat
    contain this root, which is a fact about where to look, not about what he
    says there."""
    src = q(conn, "SELECT title, author, edition FROM sources WHERE key=?",
            ("mutaradifaat",)).fetchone()
    lo, hi, n_served = kilani_pages(conn)
    out = {"present": src is not None,
           "title": src["title"] if src else None,
           "author": src["author"] if src else None,
           "edition": src["edition"] if src else None,
           "keyed_by": KEYED_BY_WORD["urdu"],
           "not_quoted": REFUSAL_KILANI_NOT_QUOTED,
           "no_urdu": REFUSAL_KILANI_NO_URDU,
           "covers": {"lo": lo, "hi": hi, "n": n_served},
           "entries": []}
    if src is None:
        return out
    out["pending"] = _kilani_pending(conn)
    for r in q(conn, "SELECT page, scan_uri, page_method, link_evidence "
                     "FROM v_entries WHERE root_ar=? AND source_id="
                     "(SELECT id FROM sources WHERE key='mutaradifaat') "
                     "ORDER BY CAST(page AS INTEGER)", (root,)):
        refs = (r["link_evidence"] or "").split()
        out["entries"].append({
            "page": r["page"],
            "scan": r["scan_uri"],
            # the warrant for the page number: read off the header, or
            # derived from the offset. Not the same claim.
            "page_read": r["page_method"] == "header",
            "page_method": r["page_method"],
            "ayat": [{"ref": ref,
                      "text": aya_text(conn, int(ref.split(":")[0]),
                                       int(ref.split(":")[1]))}
                     for ref in refs],
        })
    return out


def make_read_app(conn):
    import http.server

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "lughat-read"

        def log_message(self, fmt, *a):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            blob = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(blob)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; style-src 'unsafe-inline'; "
                             "script-src 'unsafe-inline'; connect-src 'self'; "
                             "frame-ancestors 'none'; base-uri 'none'; "
                             "form-action 'none'")
            self.end_headers()
            self.wfile.write(blob)

        def do_GET(self):
            import urllib.parse as up
            u = up.urlparse(self.path)
            if u.path == "/":
                return self._send(200, READ_HTML, "text/html; charset=utf-8")
            if u.path == "/api/roots":
                # read-only, and not sourced prose: the root list is the
                # corpus's own index, which the picker needs whole
                with DB_LOCK:
                    return self._send(200, json.dumps(
                        {"roots": root_inventory(conn)}, ensure_ascii=False))
            if u.path == "/api/jinni":
                cid = up.parse_qs(u.query).get("id", [""])[0].strip()
                with DB_LOCK:
                    if cid.isdigit():
                        got = jinni_chapter(conn, cid)
                        if got is None:
                            return self._send(404, json.dumps(
                                {"error": "not an approved chapter"}))
                        return self._send(200, json.dumps(
                            {"chapter": got}, ensure_ascii=False))
                    return self._send(200, json.dumps(
                        {"books": jinni_chapters(conn)}, ensure_ascii=False))
            if u.path == "/api/read":
                term = up.parse_qs(u.query).get("q", [""])[0].strip()
                if not term:
                    return self._send(400, json.dumps({"error": "no query"}))
                try:
                    with DB_LOCK:
                        data = read_root(conn, term)
                except (ValueError, TransliterationError) as e:
                    return self._send(200, json.dumps(
                        {"error": str(e)}, ensure_ascii=False))
                return self._send(200, json.dumps(data, ensure_ascii=False))
            return self._send(404, json.dumps({"error": "no such route"}))

        def handle_one_request(self):
            try:
                return http.server.BaseHTTPRequestHandler.handle_one_request(
                    self)
            except Exception:                                   # noqa: BLE001
                sys.stderr.write(traceback.format_exc())
                try:
                    self._send(500, json.dumps({"error": "server error"}))
                except Exception:                               # noqa: BLE001
                    pass

    return Handler


def cmd_read(conn, args):
    import http.server
    port = READ_PORT
    for a in args:
        if a.startswith("--port="):
            port = int(a.split("=", 1)[1])
    httpd = http.server.ThreadingHTTPServer(
        (REVIEW_HOST, port), make_read_app(conn))
    _w(BAR)
    _w("READING SURFACE -- approved text only.")
    _w(BAR)
    _w("Everything here has been approved by a person. A source with nothing")
    _w("to say shows an EMPTY card: the absence is information.")
    _w("")
    _w("  http://%s:%d/" % (REVIEW_HOST, port))
    _w("")
    _w("Bound to %s only. Offline; no network at query time." % REVIEW_HOST)
    _w("Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        _w("")
        _w("stopped.")
    finally:
        httpd.server_close()
    return 0


# ==========================================================================
# 12.  CLI
# ==========================================================================

USAGE = """lughat -- a local Qur'anic lexicography tool (offline, stdlib only)

  lughat.py setup [--from PATH] [--rebuild]
                                  download / load the corpus
  lughat.py test                  run the INTEGRITY and HONESTY suites
  lughat.py sarf <root> [bab]     ishtiqaq saghir, with refusals
  lughat.py root <root>           corpus occurrences of a root
  lughat.py word <word>           search the mushaf text
  lughat.py bab [<root>|--derive] the bab, read off the Qur'an's vowelling
  lughat.py ilal --check          check the i'lal rules against the Qur'an
  lughat.py akbar <root>          the six permutations, per Ibn Jinni
  lughat.py letter <root|letter>  Ibn Jinni on the root's letters
  lughat.py mentions <root>       books not keyed by root, searched
  lughat.py tafsir <sura:aya>     approved commentary on an ayah
  lughat.py translation [--add=K] a translation beside the Arabic
  lughat.py aya <sura:aya>        print an ayah, to check against a mushaf
  lughat.py ingest <lexicon> --from PATH
                                  load a lexicon, ALL at verified = 0
                                  lexicons: maqayis, mufradat, lisan
  lughat.py review [--stats]      the approval gate, in the terminal
  lughat.py review --root=<root>  decide one root's entries now
  lughat.py serve [--port=N]      the same gate as a local page (127.0.0.1)
  lughat.py read [--port=N]       the READING surface: approved sources only

Roots and words may be typed in Arabic (سكن) or Buckwalter (skn).
"""


def main(argv):
    try:
        return _main(argv)
    except (ValueError, TransliterationError) as e:
        # A malformed root or an untransliterable character is the user's
        # input being rejected, not a crash.  Say what was wrong and stop.
        sys.stderr.write("%s\n" % e)
        return 2


def _main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help", "help"):
        sys.stdout.write(USAGE)
        return 0
    cmd = argv[1]

    if cmd == "setup":
        from_path = None
        if "--from" in argv:
            from_path = argv[argv.index("--from") + 1]
        path = fetch_corpus(from_path=from_path)
        conn = connect(create=True)
        c = load(conn, path, rebuild="--rebuild" in argv)
        _w("loaded %(segments)d segments, %(words)d words, %(ayat)d ayat, "
           "%(roots)d roots" % c)
        ok = (c["segments"] == EXPECT_SEGMENTS and c["words"] == EXPECT_WORDS
              and c["ayat"] == EXPECT_AYAT and c["roots"] == EXPECT_ROOTS
              and c["suras"] == EXPECT_SURAS)
        _w("counts match the published corpus: %s" % ("yes" if ok else "NO"))
        _w("")
        _w("root classification (derived by rule from the letters):")
        tally = {}
        for (rar,) in conn.execute("SELECT root_ar FROM roots"):
            k = RootClass(root_letters(rar)).primary_kind()
            tally[k] = tally.get(k, 0) + 1
        weak = sum(1 for (rar,) in conn.execute("SELECT root_ar FROM roots")
                   if RootClass(root_letters(rar)).needs_ilal)
        for k in ("salim", "ajwaf", "naqis", "mudaaf", "mithal", "lafif",
                  "other"):
            if tally.get(k):
                _w("  %-10s %4d" % (k, tally[k]))
        _w("  %d of %d roots need i'lal, which this tool does not implement;"
           % (weak, sum(tally.values())))
        _w("  their generated forms are marked UNVERIFIED.")
        _w(QAC_ATTRIBUTION)
        _w(TANZIL_ATTRIBUTION)
        return 0 if ok else 1

    if cmd == "test":
        return run_tests(connect())

    if cmd == "sarf":
        if len(argv) < 3:
            sys.stdout.write(USAGE)
            return 2
        bab = None
        if len(argv) > 3:
            if not argv[3].isdigit() or not 1 <= int(argv[3]) <= 6:
                sys.stderr.write(
                    "bab must be 1..6 (the six abwab of the thulathi "
                    "mujarrad); got %r\n" % argv[3])
                return 2
            bab = int(argv[3])
        conn = connect() if os.path.exists(DB_PATH) else None
        cmd_sarf(conn, argv[2], bab)
        return 0

    if cmd == "root":  # noqa: E501
        if len(argv) < 3:
            sys.stdout.write(USAGE)
            return 2
        cmd_root(connect(), argv[2])
        return 0

    if cmd == "ingest":
        known = sorted(LEXICONS) + sorted(TAFASIR)
        if len(argv) < 3 or argv[2] not in known:
            sys.stderr.write("usage: lughat.py ingest <%s> --from PATH\n"
                             % "|".join(known))
            return 2
        if "--from" not in argv:
            sys.stderr.write("ingest needs --from PATH (an OpenITI text)\n")
            return 2
        if argv[2] in TAFASIR:
            key = argv[2]
            path = argv[argv.index("--from") + 1]
            conn = connect()
            n, refused, kept, recited = ingest_tafsir(conn, key, path)
            _w("%s" % TAFASIR[key]["title"])
            _w("ingested %d pericopes, ALL at verified = 0 (not served)." % n)
            _w("  anchored by quoting the mushaf, with the book's own ayah")
            _w("  number agreeing -- see tafsir.anchor_evidence.")
            if kept:
                _w("  %d passages you had already decided were left "
                   "untouched." % kept)
            if recited:
                _w("  %d of them had their citation or anchor CORRECTED."
                   % recited)
            if refused:
                for line in _wrap(REFUSAL_TAFSIR_UNANCHORED
                                  % (len(refused), n + len(refused)), 72):
                    _w("  " + line)
                why = {}
                for r in refused:
                    why[r.split(" but ")[0][:52]] = why.get(
                        r.split(" but ")[0][:52], 0) + 1
                for r, c in sorted(why.items(), key=lambda x: -x[1])[:5]:
                    _w("    %5d  %s" % (c, r))
            _w("")
            _w("Nothing above is visible to a query until it is approved:")
            _w("  python3 lughat.py review --stats")
            return 0
        if argv[2] == "mutaradifaat":
            # Not parse_lexicon's shape: OCR JSON, and it stores no text of
            # the book at all.
            path = argv[argv.index("--from") + 1]
            conn = connect()
            n, linked, kept = ingest_mutaradifaat(conn, path)
            _w("%s" % LEXICONS["mutaradifaat"]["title"])
            _w("ingested %d entries, ALL at verified = 0 (not served)." % n)
            _w("  %d carry a root, confirmed by TWO agreeing facts: the "
               "headword" % linked)
            _w("  proposes it and the ayat the page quotes contain it.")
            _w("  %d are stored unconfirmed and are keyed to nothing." % (n - linked))
            if kept:
                _w("  %d entries you had already decided were left untouched."
                   % kept)
            _w("")
            _w("NO TEXT OF THIS BOOK IS STORED. text_raw is NULL; the OCR is")
            _w("a search key in text_norm and is never displayed. The page")
            _w("image is the citation.")
            _w("")
            _w("Nothing above is visible to a query until it is approved:")
            _w("  python3 lughat.py review --source=mutaradifaat")
            return 0
        key = argv[2]
        path = argv[argv.index("--from") + 1]
        conn = connect()
        n, stats, kept, recited, unassigned = ingest_lexicon(
            conn, key, path)
        _w("%s" % LEXICONS[key]["title"])
        _w("ingested %d entries, ALL at verified = 0 (not served)." % n)
        for k in sorted(stats):
            _w("  %-11s %5d" % (k, stats[k]))
        if kept:
            _w("  %d entries you had already decided were left untouched."
               % kept)
        if recited:
            _w("  %d of them had their volume/page CORRECTED by this "
               "re-extraction." % recited)
        if unassigned:
            # A gap the reader cannot see is a gap they will mistake for
            # absence, so it is counted and printed rather than swallowed.
            _w("  %d characters of the source reached no entry (section "
               "preambles, unmarked chapters)." % unassigned)
        _w("")
        _w("Nothing above is visible to a query until it is approved:")
        _w("  python3 lughat.py review --stats")
        _w("  python3 lughat.py serve")
        _w(LEXICONS[key]["attribution"])
        return 0

    if cmd == "read":
        return cmd_read(connect(threadsafe=True), argv[2:])

    if cmd == "serve":
        return cmd_serve(connect(threadsafe=True), argv[2:])

    if cmd == "review":
        cmd_review(connect(), argv[2:])
        return 0

    if cmd == "ilal":
        conn = connect()
        res = ilal_check(conn)
        _w(BAR)
        _w("I'LAL, CHECKED AGAINST THE QUR'AN")
        _w(BAR)
        _w("Every weak root the mushaf attests, regenerated and compared")
        _w("EXACTLY. STRONG = attested in both aspects, so ONE bab must")
        _w("reproduce both. WEAK = one aspect only, so any fitting bab passes.")
        _w("")
        _w("%-7s %-8s %8s %8s %7s %6s" %
           ("TIER", "CLASS", "CORRECT", "REFUSED", "WRONG", "OF"))
        _w(RULE)
        for tier in ("strong", "weak"):
            tot = [0, 0, 0]
            for kind in sorted(res[tier]):
                m, n, fails, ref = res[tier][kind]
                wrong = n - m - ref
                tot[0] += m
                tot[1] += ref
                tot[2] += wrong
                _w("%-7s %-8s %8d %8d %7d %6d" %
                   (tier, kind, m, ref, wrong, n))
            _w("%-7s %-8s %8d %8d %7d %6d" %
               (tier, "total", tot[0], tot[1], tot[2], sum(tot)))
        _w("")
        _w("classes with no rules here: %s"
           % (", ".join("%s %d" % kv for kv in sorted(res["unhandled"].items()))
              or "none"))
        _w("")
        _w("Where a class does not reproduce the mushaf, its forms stay")
        _w("UNVERIFIED: %s" % ", ".join(
            "%s %s" % kv for kv in sorted(ILAL_NOT_VALIDATED.items())))
        for tier in ("strong", "weak"):
            for kind in sorted(res[tier]):
                for root, slot, gen, corpus in res[tier][kind][2][:3]:
                    _w("  wrong: %-6s %-5s %-7s generated %-11s mushaf %s"
                       % (kind, root, slot, gen, corpus))
        _w("")
        _w(TANZIL_ATTRIBUTION)
        return 0

    if cmd == "bab":
        conn = connect()
        if "--derive" in argv:
            n, amb = store_babs(conn)
            _w("%d roots given a bab from the Qur'an's own vowelling." % n)
            _w("%d refused: the mushaf does not settle them." % amb)
            _w(TANZIL_ATTRIBUTION)
            return 0
        if len(argv) < 3:
            with unguarded(conn):
                rows = list(conn.execute(
                    "SELECT bab, COUNT(*) n FROM roots WHERE bab IS NOT NULL "
                    "GROUP BY bab ORDER BY bab"))
                tot = conn.execute("SELECT COUNT(*) FROM roots").fetchone()[0]
                unsourced = conn.execute(
                    "SELECT COUNT(*) FROM roots WHERE bab IS NULL").fetchone()[0]
            _w(BAR)
            _w("BAB, AS THE QUR'AN VOWELS IT")
            _w(BAR)
            for r in rows:
                _w("  bab %d  %4d roots" % (r["bab"], r["n"]))
            _w("  %d of %d roots have NO sourced bab, and everything that "
               % (unsourced, tot))
            _w("  depends on it refuses for them.")
            return 0
        letters = "".join(canonical_root(argv[2]))
        r = q(conn, "SELECT * FROM roots WHERE root_ar=?",
              (letters,)).fetchone()
        if r is None:
            _w("%s does not occur in the corpus." % letters)
            return 0
        if r["bab"] and r["bab_verified"]:
            _w("%s: bab %d" % (letters, r["bab"]))
            _w("  method:   %s" % r["bab_method"])
            _w("  evidence: %s" % r["bab_evidence"])
        else:
            _w("%s: bab UNSOURCED" % letters)
            if r["bab_method"]:
                _w("  the Qur'an does not settle it: %s" % r["bab_method"])
                _w("  evidence: %s" % r["bab_evidence"])
            else:
                _w("  its form-I verb does not occur in both aspects in the")
                _w("  Qur'an, so there is no vowelled pair to read.")
        return 0

    if cmd == "letter":
        if len(argv) < 3:
            sys.stdout.write(USAGE)
            return 2
        cmd_letter(connect(), argv[2])
        return 0

    if cmd == "akbar":
        if len(argv) < 3:
            sys.stdout.write(USAGE)
            return 2
        cmd_akbar(connect(), argv[2])
        return 0

    if cmd == "translation":
        cmd_translation(connect(), argv[2:])
        return 0

    if cmd == "tafsir":
        if len(argv) < 3:
            sys.stdout.write(USAGE)
            return 2
        cmd_tafsir(connect(), argv[2])
        return 0

    if cmd == "mentions":
        if len(argv) < 3:
            sys.stdout.write(USAGE)
            return 2
        cmd_mentions(connect(), argv[2])
        return 0

    if cmd == "aya":
        if len(argv) < 3:
            sys.stdout.write(USAGE)
            return 2
        cmd_aya(connect(), argv[2])
        return 0

    if cmd == "word":
        if len(argv) < 3:
            sys.stdout.write(USAGE)
            return 2
        cmd_word(connect(), argv[2])
        return 0

    sys.stderr.write("unknown command %r\n\n" % cmd)
    sys.stdout.write(USAGE)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except BrokenPipeError:
        # `lughat.py aya 2:35 | head` closes the pipe early; that is not an
        # error.  Redirect fd 1 to devnull so the interpreter's own flush at
        # exit does not print a second traceback.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(130)

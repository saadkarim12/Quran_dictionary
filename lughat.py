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
"""

import io
import os
import re
import sqlite3
import sys
import tarfile
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


def _normalise(s, dagger):
    """dagger='alif' promotes U+0670 to a full alif; dagger='drop' deletes it."""
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


def stem_core(s):
    """The vowelled stem, for EXACT comparison.

    Keeps every internal haraka and shadda -- مَسْكَن and مِسْكَن must NOT
    compare equal.  Removes only: Uthmani annotation marks, tatweel, the
    dagger alif's *encoding* (promoted to a real alif, since it IS an alif),
    and the final iʿrab / tanwin, which is inflection rather than the stem."""
    s = "".join(ch for ch in s if ch not in _ANNOTATION)
    s = strip_wasl(s)                 # BEFORE folding: see strip_wasl
    s = s.replace(WASLA, ALIF)
    s = s.replace(DAGGER_ALIF, ALIF)  # the dagger alif IS an alif
    s = strip_tanwin_alif(s)
    while s and (s[-1] in _TANWIN or s[-1] in _SHORT):
        s = s[:-1]
    return strip_tanwin_alif(s)


def skeleton(s):
    """Consonantal skeleton used for ATTESTATION lookup.  Must agree with
    stem_core about the wasl prop, or a form whose core matches would never
    be retrieved in the first place.

    Two words with the same skeleton are NOT the same word -- see
    مَسْكَن / مِسْكَن / مُسْكَن / أَسْكَن."""
    return norm_alif(strip_tanwin_alif(strip_wasl(s)))


# ==========================================================================
# 3.  ROOT CLASSIFICATION
# ==========================================================================
#
# This IS derivable from the letters, and so is done by rule.  What is NOT
# derivable from the letters is the bab -- see section 4 and roots.bab.

WEAK_LETTERS = {"و", "ي"}
HAMZA_LETTERS = {"ء", "أ", "إ", "آ", "ؤ", "ئ"}
GUTTURALS = {"ء", "أ", "إ", "آ", "ؤ", "ئ", "ه", "ع", "ح", "غ", "خ"}

# The corpus writes a hamza radical as Buckwalter 'A' (e.g. ROOT:AHd for أحد,
# ROOT:nbA for نبأ).  An Arabic root never has a true alif as a radical.
_ROOT_BW_FIX = {"ا": "ء"}


def root_letters(root):
    """Accept Arabic (سكن) or Buckwalter (skn); return a list of Arabic
    radicals.  A bare alif in a root position is a hamza radical."""
    root = root.strip()
    if not root:
        raise ValueError("empty root")
    if not is_arabic(root):
        root = to_arabic(root)
    letters = [ch for ch in root if ch not in _MARKS and ch != DAGGER_ALIF
               and not ch.isspace()]
    return [_ROOT_BW_FIX.get(ch, ch) for ch in letters]


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
                    self.kinds.append("weak_rubaai")
                    self.reasons.append(
                        "weak radical (%s) at position %d" % (ch, i + 1))
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
                         "lafif_mafruq", "weak_rubaai") for k in self.kinds)

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
                      "it has no ism maf'ul"},
    {"roman": "X",    "name": "istaf'ala",
     "madi": "اِسْتَFْVَLَ", "mudari": "يَسْتَFْVِLُ", "amr": "اِسْتَFْVِLْ",
     "masdar": ["اِسْتِFْVَاL"], "fail": "مُسْتَFْVِL", "maful": "مُسْتَFْVَL"},
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

REFUSAL_BAB_UNKNOWN = (
    "REFUSED. This derivation depends on the bab, and the bab of a root is "
    "not derivable from its letters -- it must be read from a lexicon. "
    "roots.bab is NULL (unsourced) for this root. Pass a bab explicitly to "
    "see the template under that hypothesis, or source the bab first."
)

REFUSAL_FAIL_BAB5 = (
    "REFUSED. Bab 5 (fa'ula) does not take the fa'il pattern; it takes a "
    "sifa mushabbaha (fa'iil, fa'l, fa'al, ...), which is sama'i and not "
    "derivable. Quote it from a lexicon."
)

REFUSAL_MAFUL_BAB5 = (
    "REFUSED. Bab 5 (fa'ula) is lazim by rule; it has no ism maf'ul."
)

# Form VIII assimilates or replaces its infixed taa' after certain first
# radicals (iSTabara, izdajara, itta'akhara).  Those rules are not implemented.
FORM_VIII_TAA_IBDAL = set("صضطظدذزوي") | {"ث"}


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

    if not rc.is_thulathi:
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
        if b == 3:
            gut = [x for x in (letters[1], letters[2]) if x in GUTTURALS]
            section["condition"] = (
                "licensed: guttural %s present as R2/R3" % "/".join(gut)
                if gut else
                "NOT licensed by the letters: bab 3 requires a guttural "
                "(ء ه ع ح غ خ) as R2 or R3, and this root has none")
        for slot, key in (("madi (3MS)", "madi"),
                          ("mudari' (3MS)", "mudari"),
                          ("amr (2MS)", "amr")):
            section["forms"].append(_mk(slot, spec[key], letters, rc))

        # ---- REFUSAL 1 -------------------------------------------------
        section["forms"].append(Refusal("masdar", REFUSAL_MASDAR_MUJARRAD))

        if b == 5:
            section["forms"].append(Refusal("ism fa'il", REFUSAL_FAIL_BAB5))
            section["forms"].append(Refusal("ism maf'ul", REFUSAL_MAFUL_BAB5))
        else:
            section["forms"].append(_mk("ism fa'il", FAIL_MUJARRAD, letters, rc))
            section["forms"].append(_mk(
                "ism maf'ul", MAFUL_MUJARRAD, letters, rc,
                notes=["holds only if the verb is muta'addi; transitivity is "
                       "not derivable from the root and must be sourced"]))
        # ism makan / zaman: vowel follows the mudari', so it needs the bab
        section["forms"].append(_mk(
            "ism makan/zaman", spec["makan"], letters, rc,
            notes=[] if not hypothetical else
            ["derived under bab %d, which is a hypothesis here, not a sourced "
             "fact; a different bab gives a different vowel" % b]))
        out["mujarrad"].append(section)

    # ---- derivatives that do not depend on the bab ----------------------
    out["mujarrad_derived"].append(_mk(
        "ism tafdil", TAFDIL, letters, rc,
        notes=["holds only if the meaning admits comparison and the verb is "
               "thulathi, tamm, mutasarrif, mubna li-l-ma'lum and not a "
               "colour/defect -- conditions not derivable from the letters",
               "HOMOGRAPH: this pattern is identical to the madi of form IV; "
               "a corpus hit may be the verb, not the noun. Read the tag."]))
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
        if spec["roman"] == "VIII" and letters[0] in FORM_VIII_TAA_IBDAL:
            extra.append("form VIII requires ibdal/idgham of the infixed taa' "
                         "after R1 = %s; that rule is not implemented, so "
                         "these strings are raw templates" % letters[0])
        section = {
            "roman": spec["roman"],
            "name": spec["name"],
            "forms": [],
        }
        for slot, key in (("madi (3MS)", "madi"),
                          ("mudari' (3MS)", "mudari"),
                          ("amr (2MS)", "amr")):
            section["forms"].append(_mk(slot, spec[key], letters, rc, extra))
        # mazid masadir are QIYASI -- safe to derive.  This is the one place a
        # masdar may be generated.
        for m in spec["masdar"]:
            section["forms"].append(_mk("masdar (qiyasi)", m, letters, rc, extra))
        section["forms"].append(_mk("ism fa'il", spec["fail"], letters, rc, extra))
        if spec["maful"] is None:
            section["forms"].append(
                Refusal("ism maf'ul", "REFUSED. " + spec["maful_refusal"]))
        else:
            section["forms"].append(
                _mk("ism maf'ul", spec["maful"], letters, rc, extra))
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

SCHEMA_VERSION = 1

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
    bab_verified  INTEGER NOT NULL DEFAULT 0
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
    verified   INTEGER NOT NULL DEFAULT 0,
    CHECK (text_raw IS NOT NULL OR scan_uri IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS tafsir (
    id         INTEGER PRIMARY KEY,
    source_id  INTEGER NOT NULL REFERENCES sources(id),
    sura       INTEGER NOT NULL,
    aya        INTEGER NOT NULL,
    text_raw   TEXT,                  -- VERBATIM, or NULL for scan-only
    text_norm  TEXT,                  -- SEARCH KEY -- never displayed
    vol        TEXT,
    page       TEXT,
    scan_uri   TEXT,
    verified   INTEGER NOT NULL DEFAULT 0,
    CHECK (text_raw IS NOT NULL OR scan_uri IS NOT NULL)
);

-- The ONLY sanctioned read paths for sourced prose.  The query layer refuses
-- to run any statement that names the base tables.
CREATE VIEW IF NOT EXISTS v_entries AS
    SELECT * FROM entries WHERE verified = 1;
CREATE VIEW IF NOT EXISTS v_tafsir AS
    SELECT * FROM tafsir WHERE verified = 1;

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
    """Raised when a query would read sourced prose without the verified
    filter.  This is a bug in the caller, and it is fatal by design."""


_BASE_TABLE_RE = re.compile(
    r"\b(?:from|join|into|update)\s+[\"'`\[]?(entries|tafsir)\b", re.I)


def q(conn, sql, params=()):
    """Every read in the query path goes through here.

    Sourced prose (entries, tafsir) may only be read through v_entries /
    v_tafsir, which filter verified = 1.  Naming a base table here raises.
    Loading code uses conn.execute directly and is the only thing allowed to."""
    m = _BASE_TABLE_RE.search(sql)
    if m:
        raise UnverifiedAccess(
            "query names base table %r; unverified rows must never be served. "
            "Read through v_%s instead." % (m.group(1), m.group(1)))
    return conn.execute(sql, params)


def connect(path=DB_PATH, create=False):
    if not create and not os.path.exists(path):
        raise SystemExit(
            "no database at %s -- run:  python3 lughat.py setup" % path)
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
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


def load(conn, path=CORPUS_TXT, rebuild=False):
    with open(path, "rb") as fh:
        text = fh.read().decode("utf-8")

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
        root_ar = to_arabic(r["root_bw"]) if r["root_bw"] else None
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
    """Look a generated form up in the corpus.  Pure retrieval."""
    core = stem_core(text)
    skel = skeleton(text)
    sql = ("SELECT * FROM segments WHERE skel = ? AND is_stem = 1")
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
        if len(hits) >= limit:
            break
    hits.sort(key=lambda a: (a.kind != "EXACT", a.sura, a.aya))
    return hits


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
    for a in ats:
        mark = "EXACT   " if a.kind == "EXACT" else "SKELETON"
        _w("%s%s %-14s %-10s %s" % (indent, mark, a.form_ar, a.ref, a.grammar()))
        if a.kind == "SKELETON":
            _w(indent + "         ^ same consonants, different vowels: "
                        "this is a DIFFERENT WORD, not attestation")


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
    result = generate(root, bab=bab)
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

    if rc.needs_ilal or rc.needs_idgham or rc.needs_ibdal:
        _w("")
        _w("!" * 74)
        _w("!!  THIS ROOT IS NOT SOUND.  The i'lal / ibdal / idgham rules that")
        _w("!!  turn a template into the real word are NOT implemented here.")
        _w("!!  Naive templating on q-w-l gives the non-word qawala, not qaala.")
        _w("!!  Every form below is therefore RAW TEMPLATE OUTPUT and is marked")
        _w("!!  UNVERIFIED.  Do not read it as a claim about Arabic.")
        _w("!" * 74)

    # --- the bab is a sourced fact, and we do not have it -----------------
    _w("")
    row = None
    if conn is not None:
        row = q(conn, "SELECT bab, bab_verified, bab_page FROM roots "
                      "WHERE root_ar = ?", (result["root"],)).fetchone()
    if row is not None and row["bab"] is not None and row["bab_verified"]:
        _w("bab (sourced): %s, p. %s" % (row["bab"], row["bab_page"]))
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
    if not ents:
        _w("  %s" % NOT_FOUND_UR)
        for line in _wrap(
                "%s. No lexicon has been ingested yet, so this tool has "
                "nothing sourced to say about the MEANING of this root, and "
                "it will not invent any. The morphology above is the corpus; "
                "the meaning is a gap, and the gap is the correct output."
                % NOT_FOUND_EN, 68):
            _w("  " + line)
    for e in ents:
        _w("  %s" % (e["text_raw"] if e["text_raw"] is not None
                     else "[scan only: %s]" % e["scan_uri"]))
        _w("      -- %s vol %s p. %s" % (
            q(conn, "SELECT title FROM sources WHERE id=?",
              (e["source_id"],)).fetchone()["title"], e["vol"], e["page"]))
    _w("")
    _w(QAC_ATTRIBUTION)


def cmd_word(conn, word):
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
        # Not a false negative, and worth saying so plainly: the corpus splits
        # ٱل / ب / و / ل into their own segments, so a word the mushaf writes
        # with a prefix has no whole-word row under its bare spelling.
        _w("  (0 whole words but %d stems: the corpus segments prefixes "
           "(ٱل، ب، و، ل)" % len(srows))
        _w("   separately, so the mushaf's spelling of this word carries one.)")
    byroot = {}
    for s in srows:
        byroot.setdefault(s["root_ar"], []).append(s)
    for rt, ss in sorted(byroot.items(), key=lambda kv: -len(kv[1])):
        _w("  root %-8s %4d  e.g. %s at %d:%d:%d:%d  [%s]"
           % (rt or "-", len(ss), ss[0]["form_ar"], ss[0]["sura"],
              ss[0]["aya"], ss[0]["word"], ss[0]["seg"], ss[0]["features"]))
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
    for r in q(conn, "SELECT DISTINCT root_bw, root_ar FROM segments "
                     "WHERE root_ar IS NOT NULL"):
        ck(to_buckwalter(r["root_ar"]) == r["root_bw"], "root %r" % r["root_bw"])
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
        bad = [f for f in forms if f.verified]
        ck(not bad, "%s emitted %d forms as VERIFIED, e.g. %r"
           % (root, len(bad), bad[:1]))
        ck(all(f.caveats for f in forms),
           "%s: a form carried no reliability caveat" % root)
    # the specific non-word must be present but marked, not hidden and not sold
    res = generate("قول", bab=1)
    madi = res["mujarrad"][0]["forms"][0]
    ck(madi.text == "قَوَلَ", "expected the raw template قَوَلَ, got %r" % madi.text)
    ck(not madi.verified, "قَوَلَ was emitted as a VERIFIED form")
    return "قول/وعد/رمي/قوي: 0 verified forms; قَوَلَ present but UNVERIFIED"


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
    weak = [f for f in generate("قول", bab=1)["mujarrad"][0]["forms"]
            if not f.is_refusal]
    ck(all(f.caveats and not f.verified for f in weak),
       "a weak root produced a form with no reliability caveat")
    return "salim: notes without caveats; ajwaf: caveats on every form"


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
    conn.execute("INSERT INTO sources (key,title,kind,attribution) "
                 "VALUES ('_t','TEST','lexicon','TEST')")
    sid = conn.execute("SELECT id FROM sources WHERE key='_t'").fetchone()[0]
    try:
        conn.execute("INSERT INTO entries (source_id,root_ar,text_raw,"
                     "text_norm,vol,page,verified) VALUES (?,?,?,?,?,?,0)",
                     (sid, "سكن", "UNVERIFIED PROSE", "x", "1", "1"))
        conn.execute("INSERT INTO entries (source_id,root_ar,text_raw,"
                     "text_norm,vol,page,verified) VALUES (?,?,?,?,?,?,1)",
                     (sid, "سكن", "VERIFIED PROSE", "x", "1", "2"))
        rows = list(q(conn, "SELECT text_raw FROM v_entries WHERE root_ar=?",
                      ("سكن",)))
        texts = [r["text_raw"] for r in rows]
        ck("UNVERIFIED PROSE" not in texts, "an unverified row was served!")
        ck("VERIFIED PROSE" in texts, "the verified row was lost")
        # and the guard must refuse a query that goes round the view
        for sql in ("SELECT * FROM entries",
                    "select text_raw from  entries where 1",
                    "SELECT * FROM v_entries JOIN tafsir ON 1"):
            try:
                q(conn, sql)
            except UnverifiedAccess:
                pass
            else:
                raise Fail("the guard let through: %s" % sql)
    finally:
        conn.execute("DELETE FROM entries WHERE source_id=?", (sid,))
        conn.execute("DELETE FROM sources WHERE id=?", (sid,))
        conn.commit()
    return "view filters; q() guard rejects 3/3 base-table queries"


@test("HONESTY", "roots.bab is unsourced, and bab-dependent output refuses")
def _t(conn):
    n = q(conn, "SELECT COUNT(*) n FROM roots WHERE bab IS NOT NULL"
          ).fetchone()["n"]
    ck(n == 0, "%d roots have a bab with no lexicon loaded" % n)
    res = generate("سكن")            # no bab given
    refs = [r for r in res["mujarrad_derived"] if r.is_refusal]
    ck(any("bab" in r.reason.lower() for r in refs),
       "no refusal for the bab-dependent ism makan")
    # every bab section must be marked hypothetical when unsourced
    ck(all(s["hypothetical"] for s in res["mujarrad"]),
       "a bab section was presented as sourced")
    res2 = generate("سكن", bab=1)    # user hypothesis, still not sourced
    ck(res2["mujarrad"][0]["hypothetical"],
       "a CLI-supplied bab was presented as a sourced fact")
    return "0/1642 roots have a sourced bab; ism makan refuses without one"


@test("HONESTY", "no generative or network dependency in the query path")
def _t(conn):
    src = open(os.path.abspath(__file__), "rb").read().decode("utf-8")
    # The needles are assembled at run time; spelling them out as literals
    # would plant them in the very file this test greps.
    for verb, obj in (("import", "openai"), ("import", "anthropic"),
                      ("from", "openai"), ("from", "anthropic"),
                      ("requests", "post"), ("chat", "completions")):
        needle = verb + (" " if verb in ("import", "from") else ".") + obj
        ck(needle not in src, "found %r in the source" % needle)
    # urllib may be imported, but only inside the setup path
    net = "import" + " urllib"          # assembled, for the same reason
    ck(src.count(net) == 1, "urllib imported %d times" % src.count(net))
    ck("def fetch_corpus" in src.split(net)[0][-2000:],
       "the urllib import escaped fetch_corpus")
    ck(net not in src.split("def attest(")[1],
       "a network import appears after the query layer begins")
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
            conn.execute("BEGIN")
            conn.execute("UPDATE segments SET %s = ?, core = ?" % poisoned,
                         (SENT, SENT))
            conn.execute("UPDATE words SET %s = ?" % poisoned, (SENT,))
            conn.execute("INSERT INTO sources (key,title,kind,attribution) "
                         "VALUES ('_s','TEST LEXICON','lexicon','TEST')")
            sid = conn.execute(
                "SELECT id FROM sources WHERE key='_s'").fetchone()[0]
            conn.execute("INSERT INTO entries (source_id,root_ar,text_raw,"
                         "text_norm,vol,page,verified) VALUES (?,?,?,?,?,?,1)",
                         (sid, "سكن", "VERBATIM ENTRY TEXT", SENT, "1", "9"))
            cmd_word(conn, query)
            cmd_root(conn, "سكن")
            cmd_sarf(conn, "سكن", 1)
        finally:
            sys.stdout = real
            conn.execute("ROLLBACK")
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
    total = failed = 0
    for section in ("INTEGRITY", "HONESTY"):
        _w("")
        _w(BAR)
        _w(section)
        _w(BAR)
        for name, fn in _TESTS[section]:
            total += 1
            try:
                detail = fn(conn)
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
    _w("%d passed, %d failed, %d total" % (total - failed, failed, total))
    if failed:
        _w("")
        _w("A HONESTY failure means the governing rule has been broken.")
        _w("The change that caused it is wrong; the test is not.")
    _w(BAR)
    return 1 if failed else 0


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

Roots and words may be typed in Arabic (سكن) or Buckwalter (skn).
"""


def main(argv):
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
        bab = int(argv[3]) if len(argv) > 3 else None
        conn = connect() if os.path.exists(DB_PATH) else None
        cmd_sarf(conn, argv[2], bab)
        return 0

    if cmd == "root":
        if len(argv) < 3:
            sys.stdout.write(USAGE)
            return 2
        cmd_root(connect(), argv[2])
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
    sys.exit(main(sys.argv))

#!/bin/sh
# Rebuild the database from the sources it was built from.
#
# The database is NOT in git: it is derived, it is 133 MB, and it holds text
# under CC BY-NC-SA that this repository does not redistribute.  So it is
# rebuilt, not cloned -- and this script names the exact witness of each book
# that the counts in CLAUDE.md were measured on.  A different witness of the
# same book is a different text with different page numbers.
#
#   usage:  sh rebuild.sh /path/to/openiti
#
# where /path/to/openiti is a directory holding three OpenITI release buckets,
# cloned shallow (about 1.3 GB in total):
#
#   mkdir -p ~/openiti && cd ~/openiti
#   for b in 0400ah 0525ah 0725ah; do
#     git clone --depth 1 https://github.com/OpenITI/$b
#   done
#
# What this does NOT do is approve anything.  Every row lands verified = 0,
# and only `lughat.py review` (or the `serve` page) can change that.  If you
# have already approved rows in an existing database, re-running this keeps
# them: ingestion deletes only undecided rows.
set -e
O="$1"
if [ -z "$O" ] || [ ! -d "$O" ]; then
  echo "usage: sh rebuild.sh /path/to/openiti" >&2
  exit 2
fi
PY="${PYTHON:-python3}"

"$PY" lughat.py setup

"$PY" lughat.py ingest maqayis  --from "$O/0400ah/data/0395IbnFarisQazwini/0395IbnFarisQazwini.MucjamMaqayis/0395IbnFarisQazwini.MucjamMaqayis.Shamela0021710-ara1"
"$PY" lughat.py ingest mufradat --from "$O/0525ah/data/0502RaghibIsbahani/0502RaghibIsbahani.Mufradat/0502RaghibIsbahani.Mufradat.Shamela0023636-ara1"
"$PY" lughat.py ingest lisan    --from "$O/0725ah/data/0711IbnManzurIfriqi/0711IbnManzurIfriqi.LisanCarab/0711IbnManzurIfriqi.LisanCarab.JK000880-ara1"
"$PY" lughat.py ingest sirr     --from "$O/0400ah/data/0392IbnJinniMawsili/0392IbnJinniMawsili.SirrSinacatIcrab/0392IbnJinniMawsili.SirrSinacatIcrab.ShamAY0034702-ara1"
"$PY" lughat.py ingest khasais  --from "$O/0400ah/data/0392IbnJinniMawsili/0392IbnJinniMawsili.Khasais/0392IbnJinniMawsili.Khasais.Shamela0009986-ara1"
"$PY" lughat.py ingest baghawi  --from "$O/0525ah/data/0510IbnMascudBaghawi/0510IbnMascudBaghawi.Tafsir/0510IbnMascudBaghawi.Tafsir.Shamela0000041-ara1.completed"

"$PY" lughat.py bab --derive
"$PY" lughat.py test

echo
echo "Now:  python3 lughat.py review --stats     what is waiting"
echo "      python3 lughat.py serve              approve it (127.0.0.1:8765)"
echo "      python3 lughat.py read               read what you approved (127.0.0.1:8766)"

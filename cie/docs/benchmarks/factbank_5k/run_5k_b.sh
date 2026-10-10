# Part B of the 5,000-document test (docs/FACTBANK_5K_B_PREREGISTRATION.md): the first fact-bank test, the fact bank against
# the memory bank on finding the answer in evidence, on the 5,089-document haystack. Run after part A, on an idle machine.
set -e
export PYTHONHASHSEED=0
cd /home/user/integratedai/cie
export PYTHONPATH=src CIE_EMBEDDING_PROVIDER=fastembed CIE_LLM_PROVIDER=none
S=/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad
PY=.venv/bin/python
DB=postgresql+psycopg://cie:cie@localhost:5432
ROOT=$S/EnterpriseRAG-Bench
IDX=$S/mt5k/index.json
W5K=$S/b5k; WSM=$S/b5ksmall; WFB=$S/b5kfb; WFB50=$S/b5kfb50
L=$S/fb50/lessons.json
twice() {  # memory_test's evidence twice: the first pass warms the caches, the second is the one scored; both are kept
  CIE_DATABASE_URL=$DB/$2 CIE_LEXICAL_INDEX_DIR=$3 $PY -m cie.eval.factbank_5k_b collect --work $1
  mv $1/evidence.jsonl $1/evidence_pass1.jsonl; cp $1/giveups.json $1/giveups_pass1.json
  CIE_DATABASE_URL=$DB/$2 CIE_LEXICAL_INDEX_DIR=$3 $PY -m cie.eval.factbank_5k_b collect --work $1
}
facts() {  # the fact bank, untrained (v1) and trained (v2), built and asked
  $PY -m cie.eval.factbank_test build --work $1 --name factbank > /dev/null
  $PY -m cie.eval.factbank_test build --work $1 --name factbank_v2 --text-facts > /dev/null
  $PY -m cie.eval.factbank_test ask --work $1 --name factbank > /dev/null
  $PY -m cie.eval.factbank_test ask --work $1 --name factbank_v2 --lessons $L > /dev/null
}
checkpoints() {  # recycle Postgres's write-ahead log while a load runs (the disk is small)
  while kill -0 $1 2>/dev/null; do su postgres -c "psql -qc CHECKPOINT" > /dev/null 2>&1 || true; sleep 60; done
}
# 0. the control first: the first test's 50-document run, re-collected with today's code in its own database, as before
mkdir -p $WFB50
cp $S/fb50/haystack.json $S/fb50/questions.jsonl $S/fb50/load.json $S/fb50/plain_meta.json $WFB50/
cp $S/fb50/evidence.jsonl $WFB50/evidence_original.jsonl
ln -sfn $S/fb50/plain $WFB50/plain; ln -sf $IDX $WFB50/index.json
twice $WFB50 cie_pb $S/fb_lexical
facts $WFB50
echo "control done $(date +%T)"
# 1. the questions (seed 61: 26 owners, 10 Linear due dates, 8 action items, 6 lists, none used before, none flawed)
$PY -m cie.eval.factbank_5k_b questions --src $S/mt5k --used $S/fb50 $S/fbtest $S/mt50 --out $S/b5k_questions.jsonl --seed 61
$PY -m cie.eval.factbank_5k_b assemble --work $W5K --haystack $S/mt5k --questions $S/b5k_questions.jsonl --index $IDX --root $ROOT
$PY -m cie.eval.factbank_5k_b assemble --work $WSM --gold $S/b5k_questions.jsonl --questions $S/b5k_questions.jsonl --index $IDX --root $ROOT
$PY -m cie.eval.factbank_5k_b assemble --work $WFB --haystack $S/mt5k --questions $S/fb50/questions.jsonl --index $IDX --root $ROOT
sha256sum $S/b5k_questions.jsonl $W5K/haystack.json $WSM/haystack.json | cut -c1-16
# 2. a new database at the current schema for each size, so that each size's memory bank is alone in its indexes
for D in cie_b5k cie_b5ks; do
  su postgres -c "createdb -O cie $D"
  CIE_DATABASE_URL=$DB/$D $PY -m cie.cli migrate > /dev/null
done
# 3. the memory banks; the 5,089 reuse the embedding cache of the earlier 5,000-document runs (same model, same texts)
ln -sf $PWD/eval_out/enterprise_full/emb_cache.sqlite $W5K/emb_cache.sqlite
CIE_DATABASE_URL=$DB/cie_b5k CIE_LEXICAL_INDEX_DIR=$S/b5k_lexical $PY -m cie.eval.memory_test load --work $W5K --workers 3 &
checkpoints $!; wait $! 2>/dev/null || true
test -s $W5K/load.json
CIE_DATABASE_URL=$DB/cie_b5ks CIE_LEXICAL_INDEX_DIR=$S/b5ks_lexical $PY -m cie.eval.memory_test load --work $WSM --workers 3
echo "banks loaded $(date +%T)"
# 4. plain search: passages, BM25 and vectors (the 'plain' arm needs the vectors before any evidence is collected)
$PY -m cie.eval.memory_test plain --work $W5K
$PY -m cie.eval.memory_test plain --work $WSM
for f in load.json plain_meta.json; do cp $W5K/$f $WFB/$f; done
ln -sfn $W5K/plain $WFB/plain
echo "plain done $(date +%T)"
# 5. the evidence, twice each
twice $W5K cie_b5k $S/b5k_lexical
twice $WFB cie_b5k $S/b5k_lexical
twice $WSM cie_b5ks $S/b5ks_lexical
# 6. the fact banks (the first test's questions on the 5,089 share the primary folder's banks)
facts $W5K
for f in factbank.sqlite factbank_v2.sqlite factbank_build.json factbank_v2_build.json; do ln -sf $W5K/$f $WFB/$f; done
$PY -m cie.eval.factbank_test ask --work $WFB --name factbank > /dev/null
$PY -m cie.eval.factbank_test ask --work $WFB --name factbank_v2 --lessons $L > /dev/null
facts $WSM
# 7. how many other documents carry each answer; then the rules
$PY -m cie.eval.factbank_5k_b chance --work $W5K
$PY -m cie.eval.factbank_5k_b chance --work $WFB
$PY -m cie.eval.factbank_5k_b score --big $W5K --small $WSM --fb $WFB --fb50 $WFB50

# The company-brain round-3 test (docs/FACTBANK_BRAIN3_PREREGISTRATION.md), step 5 of 5, run once per set: SET=messy (the
# decided set: the generated questions in the rewriters' wordings, and the writers' questions) and then SET=tidy (the same
# questions in the generators' own wordings). The first run checks the rewrites and writes the messy folders, which share the
# tidy folders' banks. Every arm answers on the small set and then on the 5,000 documents, three at a time (quotes, v1 and v2 in
# one line, v16 and v17 in two others); on the messy set v17 answers again under hash seed 1; then the set is scored
# (brain3_test), with the pre-registered rules on the messy set. It prints counts and scores only.
set -e
export PYTHONHASHSEED=0
cd /home/user/integratedai/cie
export PYTHONPATH=src
S=/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad
PY=.venv/bin/python
T=${T:-$S/brain3/test5k}; TS=${TS:-${T}small}; N=$(basename $T); R=${R:-$S/brain3/rewrite/$N}
L2=docs/benchmarks/brain2/lessons
FB=$S/fb50/lessons.json
# errors go to a file, never here: a traceback could hold the test's text
ERR=${T}.step5.err; exec 2>>$ERR; trap 'echo "step 5 failed: the error is in $ERR"' ERR
SET=${SET:?SET=messy or SET=tidy}
if [ ! -e ${T}_messy ]; then
  $PY -m cie.eval.brain_writers status --batches $R/batches --outputs $R/out --prefix ${N}_messy > $R.status.json
  $PY -m cie.eval.brain2_messy collect --work $T --batches $R/batches --outputs $R/out --out ${T}_messy --small $TS \
    --small-out ${TS}_messy > $R.collect.json
  $PY -c "import json,sys; r=json.load(open(sys.argv[1])); print('rewrites kept', r['kept'], 'of', r['generated'], r['rejected'])" $R.collect.json
  # a batch with no rewrite kept was answered in the wrong form: it is written again (sealed) and this step rerun on a fresh folder
  $PY -c "import json,sys; z=[b for b,k in json.load(open(sys.argv[1]))['kept_by_batch'].items() if k == 0]; sys.exit('no rewrite kept in ' + ' '.join(z) if z else 0)" $R.collect.json
fi
if [ "$SET" = messy ]; then W=${T}_messy; WS=${TS}_messy; else W=$T; WS=$TS; fi
for X in $WS $W; do
  ( set -e
    $PY -m cie.eval.brain2_test ask --work $X --arm quotes > /dev/null
    $PY -m cie.eval.brain2_test ask --work $X --arm v1 > /dev/null
    $PY -m cie.eval.brain2_test ask --work $X --arm v2 --single $FB > /dev/null ) & A=$!
  ( $PY -m cie.eval.brain2_test ask --work $X --arm v16 --single $L2/single_lessons.json --plans $L2/plan_lessons.json --router $L2/router.json > /dev/null ) & B=$!
  ( $PY -m cie.eval.brain2_test ask --work $X --arm v17 --single $L2/single_lessons.json --plans $L2/plan_lessons.json --router $L2/router.json > /dev/null ) & C=$!
  wait $A; wait $B; wait $C  # set -e: a failed arm stops the step
  echo "asked $X $(date +%T)"
done
# every arm's record is in each folder's arms.json before scoring
WANT="quotes v1 v2 v16 v17"
for X in $WS $W; do
  $PY -c "import json,sys; have={r['label'] for r in json.load(open(sys.argv[1])).values()}; miss=sorted(set(sys.argv[2].split()) - have); sys.exit('missing arms in ' + sys.argv[1] + ': ' + ' '.join(miss) if miss else 0)" \
    $X/arms.json "$WANT"
done
if [ "$SET" = messy ]; then
  PYTHONHASHSEED=1 $PY -m cie.eval.brain2_test ask --work $W --arm v17 --single $L2/single_lessons.json --plans $L2/plan_lessons.json \
    --router $L2/router.json --name v17_seed1 > /dev/null
  $PY -m cie.eval.brain3_test score --work $W --small $WS --preregistered
else
  $PY -m cie.eval.brain3_test score --work $W --small $WS
fi
echo "scored $SET $(date +%T)"

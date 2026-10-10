# Part A of the 5,000-document test (docs/FACTBANK_5K_PREREGISTRATION.md). PYTHONHASHSEED is fixed: when names collide, which
# entity the bank resolves to can depend on Python's string hashing.
# A dry run on a seen haystack: PREFIX=dry5k HAYSTACK=<folder> bash run_5k.sh (it draws nothing).
set -e
export PYTHONHASHSEED=0
cd /home/user/integratedai/cie
export PYTHONPATH=src
S=/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad
B=docs/benchmarks/factbank_5k
PX=${PREFIX:-md5k}
BIG=$S/$PX; SMALL=$S/${PX}small; X=$S/${PX}x
A="--single $S/fb50/lessons.json"
P=$S/mdtrain
EXCL="$S/mt5k $S/mt50 $S/fb50 $S/fbtest $S/mdtrain $S/mdtest $S/mdfresh $S/mdwords $S/mdblind $S/mdllm $S/mdplan $S/mdrep $S/mdtick $S/mdord $S/lexsample"
H=${HAYSTACK:+--haystack $HAYSTACK}
# the set, its questions, the small set and the set-aside questions (drawn only after the pre-registration is committed)
.venv/bin/python -m cie.eval.factbank_5k draw --index $S/mt5k/index.json --root $S/EnterpriseRAG-Bench --exclude $EXCL $H \
  --big $BIG --small $SMALL --unclear $X --wordings docs/benchmarks/factbank_order/wordings.json --seed 53 --qseed 54
sha256sum $BIG/haystack.json $BIG/questions.jsonl $SMALL/haystack.json $X/questions.jsonl | cut -c1-16
# the banks
for W in $BIG $SMALL; do
  .venv/bin/python $B/peak.py $W/peak.jsonl -- .venv/bin/python -m cie.eval.factbank_test build --work $W --name factbank > /dev/null
  .venv/bin/python $B/peak.py $W/peak.jsonl -- .venv/bin/python -m cie.eval.factbank_test build --work $W --name factbank_v2 --text-facts > /dev/null
done
for f in factbank.sqlite factbank_v2.sqlite factbank_build.json factbank_v2_build.json; do ln -sf $BIG/$f $X/$f; done
echo "banks built $(date +%T)"
# every arm on each folder; asking never writes to a bank, so the arms run side by side. v12 then v14 share one form cache
# per question set (the small set asks the same questions as the 5,000).
for W in $BIG $SMALL $X; do
  FORM=$S/plan9/forms/form_$( [ $W = $X ] && echo ${PX}x || echo $PX ).jsonl
  .venv/bin/python $B/peak.py $W/peak.jsonl -- .venv/bin/python -m cie.eval.factbank_test ask --work $W --name factbank > /dev/null &
  for V in 4 8 9 11 13; do
    .venv/bin/python $B/peak.py $W/peak.jsonl -- .venv/bin/python -m cie.eval.factbank_multi ask --work $W $A --plans $P/plan_lessons_v$V.json --name factbank_v$V > /dev/null &
  done
  ( .venv/bin/python -m cie.eval.factbank_multi ask --work $W $A --plans $P/plan_lessons_v11.json --name factbank_v12 --form $FORM > /dev/null
    .venv/bin/python -m cie.eval.factbank_multi ask --work $W $A --plans $P/plan_lessons_v13.json --name factbank_v14 --form $FORM > /dev/null ) &
  wait
  for f in factbank factbank_v4 factbank_v8 factbank_v9 factbank_v11 factbank_v12 factbank_v13 factbank_v14; do
    test -s $W/$f.jsonl || { echo "missing $f in $W"; exit 1; }
  done
  echo "done $W $(date +%T)"
done
# the same arm under another hash seed: answers should not change
PYTHONHASHSEED=1 .venv/bin/python -m cie.eval.factbank_multi ask --work $BIG $A --plans $P/plan_lessons_v13.json --name factbank_v13_seed1 > /dev/null
.venv/bin/python -m cie.eval.factbank_5k score --big $BIG --small $SMALL --unclear $X

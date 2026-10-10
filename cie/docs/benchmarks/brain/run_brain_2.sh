# The company-brain test (docs/FACTBANK_BRAIN_PREREGISTRATION.md), step 3 of 3: after the writers' sessions (step 2), check
# and convert their questions, draw the test questions, build the banks, ask every arm and score with the pre-registered rules.
# It prints counts and scores only; the questions are read by code alone until the scores are written.
set -e
export PYTHONHASHSEED=0
cd /home/user/integratedai/cie
export PYTHONPATH=src
S=/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad
PY=.venv/bin/python
T=$S/brain/test5k; TS=$S/brain/test5ksmall
P=$S/brain/packets; O=$S/brain/writers/test_out
L=docs/benchmarks/brain/lessons
FB=$S/fb50/lessons.json; V13=$S/mdtrain/plan_lessons_v13.json
idle() {  # wait (at most 20 minutes) until nothing else is using the CPUs
  for i in $(seq 40); do [ "$(cut -d. -f1 /proc/loadavg)" -lt 2 ] && return 0; sleep 30; done
}
test ! -e $T/questions.jsonl || { echo "$T already has questions: start from a fresh folder"; exit 1; }
# the writers' questions: each writer wrote one JSONL file per batch; the checks keep or reject each question
for K in descriptive_811 prose_812; do
  cat $O/test5k_${K}_b*.jsonl > $O/test5k_${K}.outputs.jsonl
  $PY -m cie.eval.brain_writers collect --kind ${K%_*} --packets $P/test5k_$K.packets.jsonl --keys $P/test5k_$K.keys.jsonl \
    --outputs $O/test5k_$K.outputs.jsonl --out $O/test5k_$K.questions.jsonl > /dev/null
  echo "$K kept $(grep -c . $O/test5k_$K.questions.jsonl) rejected $(grep -c . $O/test5k_$K.questions.rejected.jsonl || true)"
done
# the questions (seed 810), in the development set's mix, and the small control set holding only their gold documents
$PY -m cie.eval.brain_test questions --work $T --seed 810 \
  --mix '{"deadlines": 15, "lists": 15, "fields": 30, "names": 10, "link": 15, "combine": 15, "compare": 6, "not_found": 20, "prose": 50}' \
  --prose $O/test5k_prose_812.questions.jsonl --descriptive $O/test5k_descriptive_811.questions.jsonl --small $TS > /dev/null
$PY -c "import json,collections,sys; qs=[json.loads(l) for l in open(sys.argv[1])]; print(len(qs), dict(collections.Counter(q['family'] for q in qs)))" \
  $T/questions.jsonl
sha256sum $T/questions.jsonl $TS/haystack.json | cut -c1-16
# the banks
$PY -m cie.eval.brain_test build --work $T --v1 > /dev/null
$PY -m cie.eval.brain_test build --work $TS --v1 > /dev/null
echo "banks built $(date +%T)"
idle
# every arm, one at a time, on the small set and then on the 5,000 documents
for W in $TS $T; do
  $PY -m cie.eval.brain_test ask --work $W --arm quotes > /dev/null
  $PY -m cie.eval.brain_test ask --work $W --arm v1 > /dev/null
  $PY -m cie.eval.brain_test ask --work $W --arm v2 --single $FB > /dev/null
  $PY -m cie.eval.brain_test ask --work $W --arm v13 --single $FB --plans $V13 > /dev/null
  $PY -m cie.eval.brain_test ask --work $W --arm v15 --single $L/single_lessons.json --plans $L/plan_lessons.json --router $L/router.json > /dev/null
  echo "asked $W $(date +%T)"
done
# the same brain under another hash seed: no answer should change
PYTHONHASHSEED=1 $PY -m cie.eval.brain_test ask --work $T --arm v15 --single $L/single_lessons.json --plans $L/plan_lessons.json \
  --router $L/router.json --name v15_seed1 > /dev/null
$PY -m cie.eval.brain_test score --work $T --small $TS --preregistered
echo "scored $(date +%T)"

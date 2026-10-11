# The company-brain round-2 test (docs/FACTBANK_BRAIN2_PREREGISTRATION.md), step 3 of 3: after the writers' sessions (step 2),
# check and convert their questions, draw the test questions, build the banks, ask every arm and score with the pre-registered
# rules. It prints counts and scores only; the questions are read by code alone until the scores are written.
set -e
export PYTHONHASHSEED=0
cd /home/user/integratedai/cie
export PYTHONPATH=src
S=/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad
PY=.venv/bin/python
T=$S/brain2/test5k; TS=$S/brain2/test5ksmall
P=$S/brain2/packets; O=$S/brain2/writers/test_out; H=$S/brain2/heldout/test5k
L=docs/benchmarks/brain/lessons; L2=docs/benchmarks/brain2/lessons
FB=$S/fb50/lessons.json; V13=$S/mdtrain/plan_lessons_v13.json
idle() {  # wait (at most 20 minutes) until nothing else is using the CPUs
  for i in $(seq 40); do [ "$(cut -d. -f1 /proc/loadavg)" -lt 2 ] && return 0; sleep 30; done
}
test ! -e $T/questions.jsonl || { echo "$T already has questions: start from a fresh folder"; exit 1; }
# the writers' questions: each writer wrote one file per batch. First every batch must be there and answer each of its packets
# (counts only; a batch that is not is written again by a new writer, still sealed, and this step rerun); then each file is
# read on its own and the checks keep or reject each question
for K in descriptive_911 prose_912; do
  $PY -m cie.eval.brain_writers status --batches $S/brain2/writers/test_batches --outputs $O --prefix test5k_$K > $O/test5k_$K.status.json
  $PY -m cie.eval.brain_writers collect --kind ${K%_*} --packets $P/test5k_$K.packets.jsonl --keys $P/test5k_$K.keys.jsonl \
    --outputs $O/test5k_${K}_b*.jsonl --out $O/test5k_$K.questions.jsonl > $O/test5k_$K.collect.json
  echo "$K kept $(grep -c . $O/test5k_$K.questions.jsonl) rejected $(grep -c . $O/test5k_$K.questions.rejected.jsonl || true)"
done
$PY -m cie.eval.brain_writers status --batches $H/batches --outputs $H/out --prefix test5k_heldout_913 > $H/test5k_heldout_913.status.json
$PY -m cie.eval.brain2_draw collect --work $T --packets $H/test5k_heldout_913.packets.jsonl --keys $H/test5k_heldout_913.keys.jsonl \
  --outputs $H/out/*.jsonl --out $H/test5k_heldout_questions.jsonl --i-have-preregistered > $H/test5k_heldout_913.collect.json
echo "heldout kept $(grep -c . $H/test5k_heldout_questions.jsonl) rejected $(grep -c . $H/test5k_heldout_questions.rejected.jsonl || true)"
# the questions (seed 910): v15's mix with 150 free-text questions, the new kinds' mix (brain2_test.MIX16), every held-out
# question that passes the checks, and the small control set holding only the gold documents
$PY -m cie.eval.brain2_test questions --work $T --seed 910 \
  --mix15 '{"deadlines": 15, "lists": 15, "fields": 30, "names": 10, "descriptive": 40, "link": 15, "combine": 15, "compare": 6, "not_found": 20, "prose": 150}' \
  --prose $O/test5k_prose_912.questions.jsonl --descriptive $O/test5k_descriptive_911.questions.jsonl \
  --heldout $H/test5k_heldout_questions.jsonl --small $TS > /dev/null
$PY -c "import json,collections,sys; qs=[json.loads(l) for l in open(sys.argv[1])]; print(len(qs), dict(collections.Counter(q['family'] for q in qs)))" \
  $T/questions.jsonl
sha256sum $T/questions.jsonl $TS/haystack.json | cut -c1-16
# the banks
$PY -m cie.eval.brain_test build --work $T --v1 > /dev/null
$PY -m cie.eval.brain_test build --work $TS --v1 > /dev/null
echo "banks built $(date +%T)"
idle
# every arm, one at a time, on the small set and then on the 5,000 documents; the machine is checked for idleness before each
# of the slow arms, so that the times per question are the arm's own. If a step fails, the steps after the questions step can
# be rerun one by one (the questions are not drawn again).
for W in $TS $T; do
  $PY -m cie.eval.brain2_test ask --work $W --arm quotes > /dev/null
  $PY -m cie.eval.brain2_test ask --work $W --arm v1 > /dev/null
  $PY -m cie.eval.brain2_test ask --work $W --arm v2 --single $FB > /dev/null
  idle
  $PY -m cie.eval.brain2_test ask --work $W --arm v13 --single $FB --plans $V13 > /dev/null
  idle
  $PY -m cie.eval.brain2_test ask --work $W --arm v15 --single $L/single_lessons.json --plans $L/plan_lessons.json --router $L/router.json > /dev/null
  idle
  $PY -m cie.eval.brain2_test ask --work $W --arm v16 --single $L2/single_lessons.json --plans $L2/plan_lessons.json --router $L2/router.json > /dev/null
  echo "asked $W $(date +%T)"
done
# the same brain under another hash seed: no answer should change
idle
PYTHONHASHSEED=1 $PY -m cie.eval.brain2_test ask --work $T --arm v16 --single $L2/single_lessons.json --plans $L2/plan_lessons.json \
  --router $L2/router.json --name v16_seed1 > /dev/null
$PY -m cie.eval.brain2_test score --work $T --small $TS --preregistered
echo "scored $(date +%T)"

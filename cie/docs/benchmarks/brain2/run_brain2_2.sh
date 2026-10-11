# The company-brain round-2 test (docs/FACTBANK_BRAIN2_PREREGISTRATION.md), step 3 of 5: after the writers' sessions (step 2),
# check and convert their questions, draw the test questions with the small control set, build the banks, and write the
# rewriters' batches of the generated questions. It prints counts only; the questions are read by code alone until the scores
# are written. Step 4 is the rewriters (rewriters_test2.js, with the JSON this step prints last); step 5 is run_brain2_3.sh.
set -e
export PYTHONHASHSEED=0
cd /home/user/integratedai/cie
export PYTHONPATH=src
S=/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad
PY=.venv/bin/python
# the test by default; the pre-freeze dry run sets T, P, H, B, OW and R as step 1 did
T=${T:-$S/brain2/test5k}; TS=${TS:-${T}small}; N=$(basename $T)
P=${P:-$S/brain2/packets}; O=${OW:-$S/brain2/writers/test_out}; H=${H:-$S/brain2/heldout/$N}; B=${B:-$S/brain2/writers/test_batches}
R=${R:-$S/brain2/rewrite/$N}
test ! -e $T/questions.jsonl || { echo "$T already has questions: start from a fresh folder"; exit 1; }
# the writers' questions: each writer wrote one file per batch. First every batch must be there and answer each of its packets
# (counts only; a batch that is not is written again by a new writer, still sealed, and this step rerun); then each file is
# read on its own and the checks keep or reject each question
for K in descriptive_911 prose_912; do
  $PY -m cie.eval.brain_writers status --batches $B --outputs $O --prefix ${N}_$K > $O/${N}_$K.status.json
  $PY -m cie.eval.brain_writers collect --kind ${K%_*} --packets $P/${N}_$K.packets.jsonl --keys $P/${N}_$K.keys.jsonl \
    --outputs $O/${N}_${K}_b*.jsonl --out $O/${N}_$K.questions.jsonl > $O/${N}_$K.collect.json
  echo "$K kept $(grep -c . $O/${N}_$K.questions.jsonl) rejected $(grep -c . $O/${N}_$K.questions.rejected.jsonl || true)"
done
$PY -m cie.eval.brain_writers status --batches $H/batches20 --outputs $H/out --prefix ${N}_heldout_913 > $H/${N}_heldout_913.status.json
$PY -m cie.eval.brain2_draw collect --work $T --packets $H/${N}_heldout_913.packets.jsonl --keys $H/${N}_heldout_913.keys.jsonl \
  --outputs $H/out/*.jsonl --out $H/${N}_heldout_questions.jsonl --i-have-preregistered > $H/${N}_heldout_913.collect.json
echo "heldout kept $(grep -c . $H/${N}_heldout_questions.jsonl) rejected $(grep -c . $H/${N}_heldout_questions.rejected.jsonl || true)"
# the questions (seed 910): v15's mix with 150 free-text questions, the new kinds' mix (brain2_test.MIX16), every held-out
# question that passes the checks, and the small control set holding only the gold documents
$PY -m cie.eval.brain2_test questions --work $T --seed 910 \
  --mix15 '{"deadlines": 15, "lists": 15, "fields": 30, "names": 10, "descriptive": 40, "link": 15, "combine": 15, "compare": 6, "not_found": 20, "prose": 150}' \
  --prose $O/${N}_prose_912.questions.jsonl --descriptive $O/${N}_descriptive_911.questions.jsonl \
  --heldout $H/${N}_heldout_questions.jsonl --small $TS > /dev/null
$PY -c "import json,collections,sys; qs=[json.loads(l) for l in open(sys.argv[1])]; print(len(qs), dict(collections.Counter(q['family'] for q in qs)))" \
  $T/questions.jsonl
sha256sum $T/questions.jsonl $TS/haystack.json | cut -c1-16
# the banks
$PY -m cie.eval.brain_test build --work $T --v1 > /dev/null
$PY -m cie.eval.brain_test build --work $TS --v1 > /dev/null
echo "banks built $(date +%T)"
# the rewriters' batches: the generated questions' text alone, 40 a batch
$PY -m cie.eval.brain2_messy packets --work $T --out $R/batches --per 40 > $R.packets.json
mkdir -p $R/out
$PY -c "import json,sys; r=json.load(open(sys.argv[1])); print(r['questions'], 'generated questions'); print(json.dumps({'dir': sys.argv[2], 'out': sys.argv[3], 'batches': r['batches']}))" \
  $R.packets.json $R/batches $R/out
echo "step 3 done $(date +%T)"

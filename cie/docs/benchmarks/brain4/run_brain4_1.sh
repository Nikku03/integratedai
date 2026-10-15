# The company-brain round-4 test (docs/FACTBANK_BRAIN4_PREREGISTRATION.md), step 1 of 5: draw the test set and the blind
# writers' packets. Run only after the pre-registration is committed. It prints counts only: nothing about the test documents.
# Step 2 is the writers' sessions (brain2/writers_test2.js); step 3 is run_brain4_2.sh, step 4 the rewriters
# (brain2/rewriters_test2.js) and step 5 run_brain4_3.sh.
set -e
export PYTHONHASHSEED=0
cd /home/user/integratedai/cie
export PYTHONPATH=src
S=/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad
PY=.venv/bin/python
BENCH=$S/EnterpriseRAG-Bench
# the test by default; a dry run sets ZONE=dev, T to a fresh folder, EXCL to the development sets, and P, H, B, OW
ZONE=${ZONE:-test}; T=${T:-$S/brain4/test5k}; X2=$S/brain3/r2heldout; X3=$S/brain4/r3heldout
EXCL=${EXCL:-"$S/brain/test5k $S/brain2/test5k $S/brain3/test5k $X2 $X3"}; N=$(basename $T)
P=${P:-$S/brain4/packets}; H=${H:-$S/brain4/heldout/$N}; B=${B:-$S/brain4/writers/test_batches}; OW=${OW:-$S/brain4/writers/test_out}
mkdir -p "$(dirname "$T")"
# errors go to a file, never here: a traceback could hold the test's text
ERR=${T}.step1.err; exec 2>>$ERR; trap 'echo "step 1 failed: the error is in $ERR"' ERR
test ! -e $T || { echo "$T exists: start from a fresh folder"; exit 1; }
# the held-out documents of rounds 2 and 3 guided v17's and v18's design (their held-out questions are development data): they
# are left out of this draw and of the held-out pool, each as a haystack folder of their ids
mkdir -p $X2 $X3
$PY -c "import json,sys; ids=sorted({json.loads(l)['dsid'] for l in open(sys.argv[1]) if l.strip()}); json.dump({'dsids': ids}, open(sys.argv[2], 'w')); print(len(ids), 'round-2 held-out documents left out')" \
  $S/brain2/heldout/test5k/test5k_heldout_913.keys.jsonl $X2/haystack.json
$PY -c "import json,sys; ids=sorted({json.loads(l)['dsid'] for l in open(sys.argv[1]) if l.strip()}); json.dump({'dsids': ids}, open(sys.argv[2], 'w')); print(len(ids), 'round-3 held-out documents left out')" \
  $S/brain3/heldout/test5k/test5k_heldout_1013.keys.jsonl $X3/haystack.json
mkdir -p $P $B $OW
# the test set: 5,000 documents of the test zone (seed 1019) that none of the test sets of rounds 1, 2 and 3 used (brain/test5k,
# brain2/test5k, brain3/test5k), with pull request -> Linear issue pairs planted from the zone's remaining documents
$PY -m cie.eval.brain2_draw draw --zone $ZONE --seed 1019 --zones $S/brain/zones.json.gz --index $S/mt5k/index.json --root $BENCH \
  --exclude $EXCL --out $T --i-have-preregistered > /dev/null
sha256sum $T/haystack.json | cut -c1-16
# the writers' packets: 60 descriptive (seed 1021) and 100 free-text (seed 1022), never two on one document; their reports hold
# counts only
$PY -m cie.eval.brain_writers packets --work $T --kind descriptive --n 60 --seed 1021 --out $P/${N}_descriptive_1021.packets.jsonl \
  --keys $P/${N}_descriptive_1021.keys.jsonl --i-have-preregistered > $P/${N}_descriptive_1021.report.json
$PY -m cie.eval.brain_writers packets --work $T --kind prose --n 100 --seed 1022 --out $P/${N}_prose_1022.packets.jsonl \
  --keys $P/${N}_prose_1022.keys.jsonl --avoid $P/${N}_descriptive_1021.keys.jsonl --i-have-preregistered > $P/${N}_prose_1022.report.json
# held-out documents (seed 1023): test-zone documents in none of the four test sets, that pass the checks against this
# haystack; the writers ask about them, and the right answer is "not found"
$PY -m cie.eval.brain2_draw heldout --work $T --zones $S/brain/zones.json.gz --n 100 --seed 1023 --out $H --exclude $EXCL \
  --i-have-preregistered > /dev/null
# batches of 20 packets for the writers; the answers (key files) stay out of them
$PY - <<PYEOF
import json
for name in ("${N}_descriptive_1021", "${N}_prose_1022"):
    ps = [json.loads(line) for line in open("$P/" + name + ".packets.jsonl")]
    for i in range(0, len(ps), 20):
        json.dump({"batch": f"{name}_b{i // 20:02d}", "kind": ps[0]["kind"], "packets": ps[i:i + 20]},
                  open(f"$B/{name}_b{i // 20:02d}.json", "w"), indent=1)
    print(name, len(ps), "packets")
import os
os.makedirs("$H/batches20", exist_ok=True)
hp = [json.loads(line) for line in open("$H/${N}_heldout_1023.packets.jsonl")]
for i in range(0, len(hp), 20):
    json.dump({"batch": f"${N}_heldout_1023_b{i // 20:02d}", "kind": hp[0]["kind"], "packets": hp[i:i + 20]},
              open(f"$H/batches20/${N}_heldout_1023_b{i // 20:02d}.json", "w"), indent=1)
print("heldout", len(hp), "packets")
PYEOF
# the batch lists, as writers_test2.js takes them
$PY - <<PYEOF
import json, os
sets = [{"dir": "$B", "out": "$OW", "batches": sorted(f[:-5] for f in os.listdir("$B") if f.endswith(".json"))},
        {"dir": "$H/batches20", "out": "$H/out", "batches": sorted(f[:-5] for f in os.listdir("$H/batches20") if f.endswith(".json"))}]
print(json.dumps({"sets": sets}))
PYEOF
echo "step 1 done $(date +%T)"

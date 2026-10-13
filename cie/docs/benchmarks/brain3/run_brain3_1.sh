# The company-brain round-3 test (docs/FACTBANK_BRAIN3_PREREGISTRATION.md), step 1 of 5: draw the test set and the blind
# writers' packets. Run only after the pre-registration is committed. It prints counts only: nothing about the test documents.
# Step 2 is the writers' sessions (brain2/writers_test2.js); step 3 is run_brain3_2.sh, step 4 the rewriters
# (brain2/rewriters_test2.js) and step 5 run_brain3_3.sh.
set -e
export PYTHONHASHSEED=0
cd /home/user/integratedai/cie
export PYTHONPATH=src
S=/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad
PY=.venv/bin/python
BENCH=$S/EnterpriseRAG-Bench
# the test by default; a dry run sets ZONE=dev, T to a fresh folder, EXCL to the development sets, and P, H, B, OW
ZONE=${ZONE:-test}; T=${T:-$S/brain3/test5k}; EXCL=${EXCL:-"$S/brain/test5k $S/brain2/test5k"}; N=$(basename $T)
P=${P:-$S/brain3/packets}; H=${H:-$S/brain3/heldout/$N}; B=${B:-$S/brain3/writers/test_batches}; OW=${OW:-$S/brain3/writers/test_out}
# errors go to a file, never here: a traceback could hold the test's text
ERR=${T}.step1.err; exec 2>>$ERR; trap 'echo "step 1 failed: the error is in $ERR"' ERR
test ! -e $T || { echo "$T exists: start from a fresh folder"; exit 1; }
mkdir -p $P $B $OW
# the test set: 5,000 documents of the test zone (seed 1009) that neither round 1's test set (brain/test5k) nor round 2's
# (brain2/test5k) used, with pull request -> Linear issue pairs planted from the zone's remaining documents
$PY -m cie.eval.brain2_draw draw --zone $ZONE --seed 1009 --zones $S/brain/zones.json.gz --index $S/mt5k/index.json --root $BENCH \
  --exclude $EXCL --out $T --i-have-preregistered > /dev/null
sha256sum $T/haystack.json | cut -c1-16
# the writers' packets: 100 descriptive (seed 1011) and 60 free-text (seed 1012), never two on one document; their reports hold
# counts only
$PY -m cie.eval.brain_writers packets --work $T --kind descriptive --n 100 --seed 1011 --out $P/${N}_descriptive_1011.packets.jsonl \
  --keys $P/${N}_descriptive_1011.keys.jsonl --i-have-preregistered > $P/${N}_descriptive_1011.report.json
$PY -m cie.eval.brain_writers packets --work $T --kind prose --n 60 --seed 1012 --out $P/${N}_prose_1012.packets.jsonl \
  --keys $P/${N}_prose_1012.keys.jsonl --avoid $P/${N}_descriptive_1011.keys.jsonl --i-have-preregistered > $P/${N}_prose_1012.report.json
# held-out documents (seed 1013): test-zone documents in none of the three test sets, that pass the checks against this
# haystack; the writers ask about them, and the right answer is "not found"
$PY -m cie.eval.brain2_draw heldout --work $T --zones $S/brain/zones.json.gz --n 75 --seed 1013 --out $H --exclude $EXCL \
  --i-have-preregistered > /dev/null
# batches of 20 packets for the writers; the answers (key files) stay out of them
$PY - <<PYEOF
import json
for name in ("${N}_descriptive_1011", "${N}_prose_1012"):
    ps = [json.loads(line) for line in open("$P/" + name + ".packets.jsonl")]
    for i in range(0, len(ps), 20):
        json.dump({"batch": f"{name}_b{i // 20:02d}", "kind": ps[0]["kind"], "packets": ps[i:i + 20]},
                  open(f"$B/{name}_b{i // 20:02d}.json", "w"), indent=1)
    print(name, len(ps), "packets")
import os
os.makedirs("$H/batches20", exist_ok=True)
hp = [json.loads(line) for line in open("$H/${N}_heldout_1013.packets.jsonl")]
for i in range(0, len(hp), 20):
    json.dump({"batch": f"${N}_heldout_1013_b{i // 20:02d}", "kind": hp[0]["kind"], "packets": hp[i:i + 20]},
              open(f"$H/batches20/${N}_heldout_1013_b{i // 20:02d}.json", "w"), indent=1)
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

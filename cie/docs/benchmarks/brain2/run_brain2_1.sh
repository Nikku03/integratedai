# The company-brain round-2 test (docs/FACTBANK_BRAIN2_PREREGISTRATION.md), step 1 of 3: draw the test set and the blind
# writers' packets. Run only after the pre-registration is committed. It prints counts only: nothing about the test documents.
# Step 2 is the writers' sessions (writers_test2.js); step 3 is run_brain2_2.sh.
set -e
export PYTHONHASHSEED=0
cd /home/user/integratedai/cie
export PYTHONPATH=src
S=/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad
PY=.venv/bin/python
BENCH=$S/EnterpriseRAG-Bench
T=$S/brain2/test5k
P=$S/brain2/packets
H=$S/brain2/heldout/test5k
B=$S/brain2/writers/test_batches
test ! -e $T || { echo "$T exists: start from a fresh folder"; exit 1; }
mkdir -p $P $B $S/brain2/writers/test_out
# the test set: 5,000 documents of the test zone (seed 909) that round 1's test set (brain/test5k) did not use, with pull
# request -> Linear issue pairs planted from the zone's remaining documents
$PY -m cie.eval.brain2_draw draw --zone test --seed 909 --zones $S/brain/zones.json.gz --index $S/mt5k/index.json --root $BENCH \
  --exclude $S/brain/test5k --out $T --i-have-preregistered > /dev/null
sha256sum $T/haystack.json | cut -c1-16
# the writers' packets: 45 descriptive (seed 911) and 180 free-text (seed 912), never two on one document; their reports hold
# counts only
$PY -m cie.eval.brain_writers packets --work $T --kind descriptive --n 45 --seed 911 --out $P/test5k_descriptive_911.packets.jsonl \
  --keys $P/test5k_descriptive_911.keys.jsonl --i-have-preregistered > $P/test5k_descriptive_911.report.json
$PY -m cie.eval.brain_writers packets --work $T --kind prose --n 180 --seed 912 --out $P/test5k_prose_912.packets.jsonl \
  --keys $P/test5k_prose_912.keys.jsonl --avoid $P/test5k_descriptive_911.keys.jsonl --i-have-preregistered > $P/test5k_prose_912.report.json
# held-out documents (seed 913): test-zone documents in neither test set, that pass the checks against this haystack; the
# writers ask about them, and the right answer is "not found"
$PY -m cie.eval.brain2_draw heldout --work $T --zones $S/brain/zones.json.gz --n 75 --seed 913 --out $H --i-have-preregistered > /dev/null
# batches of 10 packets for the writers; the answers (key files) stay out of them
$PY - <<PYEOF
import json
for name in ("test5k_descriptive_911", "test5k_prose_912"):
    ps = [json.loads(line) for line in open("$P/" + name + ".packets.jsonl")]
    for i in range(0, len(ps), 10):
        json.dump({"batch": f"{name}_b{i // 10:02d}", "kind": ps[0]["kind"], "packets": ps[i:i + 10]},
                  open(f"$B/{name}_b{i // 10:02d}.json", "w"), indent=1)
    print(name, len(ps), "packets")
print("heldout", sum(1 for _ in open(next(__import__("glob").iglob("$H/*.packets.jsonl")))), "packets")
PYEOF
# the batch lists, as writers_test2.js takes them
$PY - <<PYEOF
import json, os
sets = [{"dir": "$B", "out": "$S/brain2/writers/test_out", "batches": sorted(f[:-5] for f in os.listdir("$B") if f.endswith(".json"))},
        {"dir": "$H/batches", "out": "$H/out", "batches": sorted(f[:-5] for f in os.listdir("$H/batches") if f.endswith(".json"))}]
print(json.dumps({"sets": sets}))
PYEOF
echo "step 1 done $(date +%T)"

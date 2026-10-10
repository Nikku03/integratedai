# The company-brain test (docs/FACTBANK_BRAIN_PREREGISTRATION.md), step 1 of 3: draw the test set and the blind writers'
# packets. Run only after the pre-registration is committed. It prints counts only: nothing about the test documents.
# Step 2 is the writers' sessions (see the pre-registration); step 3 is run_brain_2.sh.
set -e
export PYTHONHASHSEED=0
cd /home/user/integratedai/cie
export PYTHONPATH=src
S=/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad
PY=.venv/bin/python
BENCH=$S/EnterpriseRAG-Bench
T=$S/brain/test5k
P=$S/brain/packets
test ! -e $T || { echo "$T exists: start from a fresh folder"; exit 1; }
# the test set: 5,000 documents of the test zone (seed 809), with the zone's 10 planted pull requests
$PY -m cie.eval.brain_draw draw --zone test --seed 809 --zones $S/brain/zones.json.gz --index $S/mt5k/index.json --root $BENCH \
  --out $T --i-have-preregistered > /dev/null
sha256sum $T/haystack.json | cut -c1-16
# the writers' packets: 40 descriptive (seed 811) and 60 free-text (seed 812), never two on one document
$PY -m cie.eval.brain_writers packets --work $T --kind descriptive --n 40 --seed 811 --out $P/test5k_descriptive_811.packets.jsonl \
  --keys $P/test5k_descriptive_811.keys.jsonl --i-have-preregistered > /dev/null
$PY -m cie.eval.brain_writers packets --work $T --kind prose --n 60 --seed 812 --out $P/test5k_prose_812.packets.jsonl \
  --keys $P/test5k_prose_812.keys.jsonl --avoid $P/test5k_descriptive_811.keys.jsonl --i-have-preregistered > /dev/null
# batches of 10 packets for the writers; the answers (key files) stay out of them
mkdir -p $S/brain/writers/test_batches $S/brain/writers/test_out
$PY - <<EOF
import json
for name in ("test5k_descriptive_811", "test5k_prose_812"):
    ps = [json.loads(line) for line in open("$P/" + name + ".packets.jsonl")]
    for i in range(0, len(ps), 10):
        json.dump({"batch": f"{name}_b{i // 10:02d}", "kind": ps[0]["kind"], "packets": ps[i:i + 10]},
                  open(f"$S/brain/writers/test_batches/{name}_b{i // 10:02d}.json", "w"), indent=1)
    print(name, len(ps), "packets")
EOF
ls $S/brain/writers/test_batches | wc -l
echo "step 1 done $(date +%T)"

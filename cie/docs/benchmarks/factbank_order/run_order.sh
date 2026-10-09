set -e
cd /home/user/integratedai/cie
export PYTHONPATH=src
S=/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad
A="--single $S/fb50/lessons.json"
P=$S/mdtrain
# the test set and its changed copy (built only after the pre-registration is committed)
.venv/bin/python -m cie.eval.factbank_multi fresh --index $S/mt5k/index.json --root $S/EnterpriseRAG-Bench --exclude $S/mt5k $S/fb50 $S/fbtest $S/mdtrain $S/mdtest $S/mdfresh $S/mdwords $S/mdblind $S/mdllm $S/mdplan $S/mdrep $S/mdtick $S/mt50 $S/lexsample --out $S/mdord --seed 47 --wordings $S/ord/blind5/wordings.json
.venv/bin/python -m cie.eval.factbank_split changed --work $S/mdord --out $S/mdordchanged
sha256sum $S/mdord/questions.jsonl $S/mdordchanged/questions.jsonl $S/mdord/haystack.json | cut -c1-16
for W in mdord mdordchanged; do
  .venv/bin/python -m cie.eval.factbank_test build --work $S/$W --name factbank > /dev/null
  .venv/bin/python -m cie.eval.factbank_test ask --work $S/$W --name factbank > /dev/null
  .venv/bin/python -m cie.eval.factbank_test build --work $S/$W --name factbank_v2 --text-facts > /dev/null
done
.venv/bin/python $S/ord/single_writers.py $S mdord 48
# the test set, its changed copy and each writer alone: every arm
for W in mdord mdordchanged mdord_w1 mdord_w2 mdord_w3; do
  for V in 4 8 9 11 13; do .venv/bin/python -m cie.eval.factbank_multi ask --work $S/$W $A --plans $P/plan_lessons_v$V.json --name factbank_v$V > /dev/null; done
  .venv/bin/python -m cie.eval.factbank_multi ask --work $S/$W $A --plans $P/plan_lessons_v11.json --name factbank_v12 --form $S/plan9/forms/form_$W.jsonl > /dev/null
  .venv/bin/python -m cie.eval.factbank_multi ask --work $S/$W $A --plans $P/plan_lessons_v13.json --name factbank_v14 --form $S/plan9/forms/form_$W.jsonl > /dev/null
  echo "done $W $(date +%T)"
done
# training and the earlier sets as drawn: v13 and v14 (v11 and v12 were answered before)
for W in mdtrain mdtrainv9 mdtest mdfresh mdwords mdblind mdllm mdplan mdrep mdtick; do
  .venv/bin/python -m cie.eval.factbank_multi ask --work $S/$W $A --plans $P/plan_lessons_v13.json --name factbank_v13 > /dev/null
  .venv/bin/python -m cie.eval.factbank_multi ask --work $S/$W $A --plans $P/plan_lessons_v13.json --name factbank_v14 --form $S/plan9/forms/form_$W.jsonl > /dev/null
  echo "done $W $(date +%T)"
done
.venv/bin/python -m cie.eval.factbank_multi order --work $S/mdord --changed $S/mdordchanged --train $S/mdtrain --train-all $S/mdtrainv9 --earlier $S/mdtest $S/mdfresh $S/mdwords $S/mdblind $S/mdllm $S/mdplan $S/mdrep $S/mdtick --writers $S/mdord_w1 $S/mdord_w2 $S/mdord_w3 | grep -v "^| all pieces"

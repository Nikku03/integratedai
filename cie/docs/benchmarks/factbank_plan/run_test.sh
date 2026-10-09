set -e
cd /home/user/integratedai/cie
export PYTHONPATH=src
S=/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad
A="--single $S/fb50/lessons.json"
P=$S/mdtrain
# the test set and its changed copy (built only after the pre-registration is committed)
.venv/bin/python -m cie.eval.factbank_multi fresh --index $S/mt5k/index.json --root $S/EnterpriseRAG-Bench --exclude $S/mt5k $S/fb50 $S/fbtest $S/mdtrain $S/mdtest $S/mdfresh $S/mdwords $S/mdblind $S/mdllm $S/mt50 $S/lexsample --out $S/mdplan --seed 37 --wordings $S/plan9/blind3/wordings.json
.venv/bin/python -m cie.eval.factbank_split changed --work $S/mdplan --out $S/mdplanchanged
sha256sum $S/mdplan/questions.jsonl $S/mdplanchanged/questions.jsonl $S/mdplan/haystack.json | cut -c1-16
for W in mdplan mdplanchanged; do
  .venv/bin/python -m cie.eval.factbank_test build --work $S/$W --name factbank > /dev/null
  .venv/bin/python -m cie.eval.factbank_test ask --work $S/$W --name factbank > /dev/null
  .venv/bin/python -m cie.eval.factbank_test build --work $S/$W --name factbank_v2 --text-facts > /dev/null
done
for W in mdplan mdplanchanged mdtrain mdtrainv9 mdtest mdfresh mdwords mdblind mdllm; do
  for V in 4 8 9 9n; do .venv/bin/python -m cie.eval.factbank_multi ask --work $S/$W $A --plans $P/plan_lessons_v$V.json --name factbank_v$V > /dev/null; done
  .venv/bin/python -m cie.eval.factbank_multi ask --work $S/$W $A --plans $P/plan_lessons_v9.json --name factbank_v10 --form $S/plan9/forms/form_$W.jsonl > /dev/null
  echo "done $W $(date +%T)"
done
.venv/bin/python -m cie.eval.factbank_multi plan --work $S/mdplan --changed $S/mdplanchanged --train $S/mdtrain --train-all $S/mdtrainv9 | grep -v "^| all pieces"

"""Every earlier wording of an action item and of a question that asks for an order: does v13's check act on it?
(The check should act on the action items, which ask for several things, and never on the questions that ask for an order.)
Run from cie/: PYTHONPATH=src .venv/bin/python docs/benchmarks/factbank_order/earlier_wordings.py"""
import json
from pathlib import Path

from cie.eval import factbank_multi as fm
from cie.factbank.plans import Planner

src = [("first test", kind, w) for (kind, _f), (tr, ho) in fm.T.items() for w in tr + ho]
src += [(name, kind, w) for name, W in fm.WORDINGS.items() for (kind, _f), ws in W.items() for w in ws]
B = Path(__file__).resolve().parents[1]
for t in ("general", "llm", "plan", "ticket"):
    for wr in json.loads((B / f"factbank_{t}/writers.json").read_text())["writers"]:
        src += [(f"{t} writer {wr['writer']}", x["key"].split("/")[0], x["wording"]) for x in wr["wordings"]]
acts = Planner.wants_several
action = [(s, w) for s, k, w in src if k == "action_owner_issues"]
ordering = [(s, w) for s, k, w in src if k in ("person_first", "compare_two")]
print(f"action items: the check acts on {sum(acts(w) for _, w in action)} of {len(action)}")
for s, w in action:
    if not acts(w):
        print("  not acted on:", s, "|", w)
print(f"questions asking for an order: the check acts on {sum(acts(w) for _, w in ordering)} of {len(ordering)}")
for s, w in ordering:
    if acts(w):
        print("  acted on:", s, "|", w)

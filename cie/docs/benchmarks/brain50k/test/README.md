# Raw results of the 50,000-document test

The answers and records behind `docs/FACTBANK_50K_RESULTS.md`, from the Colab run of 2026-10-21 (plan:
`docs/FACTBANK_50K_PLAN.md`). `w50k_messy/` is the messy set (the casual wordings, which decide); `w50k/` is the tidy set
(the generators' wordings, reported only).

## Files

| file | in | what it is | made where |
|---|---|---|---|
| `arms50k.json` | both | each arm's run record: model, settings, time, tokens, tool calls, the questions' sha256 | Colab |
| `rag.jsonl.gz` | both | plain search's answers, one row a question: the documents its passages came from, how many passages, tokens and the model's visible reply | Colab |
| `reasoner.jsonl.gz` | both | the reasoner's answers: each tool call (its arguments, error and result length, not the result), the model's last visible reply, tokens and the settings it was made with | Colab |
| `factbank_v18.jsonl.gz` | `w50k_messy/` (the tidy folder's follows) | v18's answers, with its route, reason and evidence | made again here (below) |
| `report50k.json.gz`, `report50k.md` | `w50k_messy/` | the score step's report on both folders: every rule, every table, and each question's score, "not found" flag and answer length for every arm | Colab |

The questions themselves are in `docs/benchmarks/brain50k/plan/<folder>/questions.jsonl`. Every row has the question's
`id`, so the files join on it. The run records' `questions_sha256` match the plan's.

`arms50k.json` in `w50k/` records only the last 123 plain-search answers for `rag`: that run was cut off after 512
answers and resumed, and the resumed run rewrote the record.

## Where they come from

The Colab notebook (`notebooks/company_brain_50k_colab.ipynb`) saved its results to Google Drive
(`MyDrive/cie_brain50k/<folder>/`) as each step ran. The files here were downloaded from there, and the answer files
gzipped. The Drive files' creation times (UTC, 2026-10-21) give the run's order; the rows themselves carry no times:

| time | file |
|---|---|
| 16:19 | `w50k/haystack.json` (the draw) |
| 16:27 | `w50k_messy/factbank_v18.jsonl` |
| 16:32 | `w50k_messy/arms50k.json` |
| 16:37 | `w50k/factbank_v18.jsonl` |
| 16:43 | `w50k/arms50k.json` |
| 17:03 | `w50k_messy/rag.jsonl` |
| 17:28 | `w50k/rag.jsonl` |
| 18:35 | `w50k_messy/reasoner.jsonl` |
| 19:00 | `w50k/reasoner.jsonl` |
| 19:24 | `w50k_messy/report50k.json`, `report50k.md` |

The last commit that changed code before the run, `61c794a`, is from 16:14 UTC. The model's thinking was not kept.

## v18's answers, made again

Colab's two v18 answer files (about 11 MB each) are larger than the Drive connector could download (10 MB). So v18 was
asked all 1,270 questions again here, with round 4's lessons and `PYTHONHASHSEED=0`. The brain's code is the one Colab
ran: `factbank/brain.py` and `factbank/engine.py` have not changed since `a215da6`, and nothing in `src/` since
`61c794a`.

```
PYTHONHASHSEED=0 PYTHONPATH=src python -m cie.eval.brain50k ask --arm v18 --work <folder> --workers 3
```

- **The same documents:** the bank was built here from a draw whose document list is the same as Colab's
  `haystack.json`, in the same order (sha256 `9a344aaa…`, the plan's). The bank holds 50,000 sources and 1,162,089 facts,
  as the plan's `banks.json` says.
- **The same answers:** every answer gives Colab's score and answer length in the report: 635 of 635 in `w50k_messy/`.
  The tidy folder's re-run is still going (540 of 635 so far, all the same); its answers will be added when it ends.

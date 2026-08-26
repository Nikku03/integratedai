# Reading the filing: the reader finds the bad news, not the good

Daily k=1 inside the catalyst gate, with one change — before the trade is taken,
the actual 8-K is read. The model proposes the top three gated names each
session; the reader opens the filings and judges each on a −2…+2 scale purely on
what the document says; three selections are then compared over the same fifteen
sessions.

## What was read

45 filings over 2026-07-21 → 2026-08-10, top three per session, ranked by a q75
quantile model trained on 158,154 gated rows before 2026-06-17. Full EDGAR
submissions were fetched, the 8-K body and its EX-99 press release split out of
the tagged-document envelope, the cover page dropped at the first numbered item,
and 3,400 characters kept — 36k tokens in total. Every one of the 45 was judged.

The first attempt at this produced unreadable bundles: `filing_corpus.clean()`
targets primary documents, so pointing it at a full submission `.txt` yielded
SEC-HEADER and XBRL namespace declarations. `submission_text()` replaces it.

## The blindness was structural, and it leaked anyway

`--build` writes the reading bundles and the outcome table to separate files;
`--score` is the first step that joins them. That held. What it could not do is
un-publish a result document: `RESULT_CATALYST_GATE.md` and
`RESULT_MOONSHOT_HUNT.md` list the gated picks with their realised moves for
seven of these fifteen sessions, and both were re-read earlier in the same
session as the judging. **21 of the 45 judgements were therefore not blind.**

So every table below is given twice: all fifteen sessions, and the eight
sessions whose outcomes had not been published. **The clean column is the
result.** Reproduce it with `--clean`.

## The reading points the right way

| | full 15 sessions | clean 8 sessions |
|---|---|---|
| rank correlation, judgement vs realised | **+0.330** (45) | **+0.355** (24) |
| judged positive | +10.00% (15) | +1.30% (6) |
| judged negative | −5.06% (14) | −8.22% (9) |
| spread | +15.06pp | +9.51pp |

Day-clustered bootstrap on negative-judged versus everything else:

| | difference | 95% CI | P(negatives not worse) |
|---|---|---|---|
| full 15 sessions | −14.51pp | [−29.66, **+0.80**] | 0.031 |
| clean 8 sessions | −12.39pp | [−26.52, **+1.68**] | 0.044 |

Both intervals clip zero at the top. This is the strongest single-direction
signal from a text feature anywhere in this repository, and it is still not
clear of zero on 8–15 days of data.

## But only in one direction

Broken out by judgement, the scale is not monotone — the whole effect lives in
the strong-negative bucket:

| judge | clean n | clean mean | clean win | full n | full mean |
|---|---|---|---|---|---|
| **−2** | 6 | **−18.09%** | **0.0%** | 10 | −8.40% |
| −1 | 3 | +11.54% | 66.7% | 4 | +3.29% |
| 0 | 9 | +6.09% | 66.7% | 16 | +8.93% |
| +1 | 1 | −8.95% | 0.0% | 8 | +12.39% |
| **+2** | 5 | **+3.35%** | 80.0% | 7 | +7.26% |

**Six strong-negative calls, six losers, mean −18%.** Reverse splits, dividend
suspensions, authorized-share increases, insider vesting acceleration, a
guidance cut, a revenue miss — the reader named them and they all fell.

**The positive calls were worth nothing.** On the clean subset judge +2 returned
+3.35%, *below* the +6.09% of filings judged to contain no information at all.
The best trade in the entire sample was **AXTI +67%** — a filing announcing the
election of one independent director, which I scored 0 because that is all it
says. Judging a filing "good news" did not find upside; judging it "no news" did
just as well.

That is `RESULT_MOONSHOT_HUNT.md` and the Item 3.02 finding in
`RESULT_CATALYST_GATE.md` arriving from a third direction. The sharpest catalyst
in the panel is dilution, at 3.53× volatility and −2.11% return; selecting for
the up-tail selects the down-tail with it; and now, given the document itself,
the reader can say which filings are bad and cannot say which are good.

## So the veto is the right architecture

Take the model's top pick unless the filing reads negative, then step down.

| arm | clean 8 | full 15 |
|---|---|---|
| model k=1 (control) | +1.90% (win 50.0%) | +1.79% (win 53.3%) |
| reader k=1 | +1.93% (win 75.0%) | +5.59% (win 80.0%) |
| **reader veto** | **+5.13%** (win 62.5%) | **+6.93%** (win 66.7%) |
| shortlist average | −0.47% | +4.93% |

Ranking *by* the judgement (reader k=1) adds nothing on the clean subset —
+1.93% against the model's +1.90% — exactly as the bucket table predicts, since
the positive end of the scale carries no information. Using the judgement only
to *reject* adds +3.2pp.

The veto fires on four of the eight clean sessions, and two of them carry it:

```
2026-07-22  MSS   -2  -46.19%  ->  KSCP  +2  -21.31%   +24.88pp
2026-08-03  EZRA  -2  -13.53%  ->  GSIT   0   +7.42%   +20.95pp
2026-08-06  ABTC  -1  +30.51%  ->  BTBT   0  +13.73%   -16.78pp
2026-08-07  VRRM  -2   -5.79%  ->  ZSQR  +1   -8.95%    -3.16pp
```

Four events is not an edge. Two of the four went the wrong way. What is worth
noting is that the two that worked were the two the reader was most confident
about — a second reverse split in three months, and a compensation committee
fully vesting the CEO's family's stock five weeks after granting it.

## The miss worth recording

**CAPR returned +70%** after an FDA advisory committee voted **9–3 against** the
effectiveness of its lead asset three weeks before the PDUFA date. I scored it
−2 and would again. The press release argues the vote addressed a narrower
indication than proposed and that the committee was "directionally supportive"
on upper-limb function; the market evidently read past the headline vote. A
document can be unambiguous and the price can still go the other way, and no
amount of careful reading fixes that.

## What this does and does not establish

Eight sessions. The veto's entire clean advantage is two trades. Nothing here
survives a power calculation, and the four previous live windows in this
repository all disagreed with their own historical figures.

What replicates against everything else measured here is the **asymmetry**, not
the profit: bad news in a filing is legible and predictive, good news in a
filing is legible and not. The next test worth running is the veto alone, over
the full historical panel rather than fifteen days — which needs the extractor
in `scripts/llm_extract.py` run at scale, not a reader working through 45
documents by hand.

## Reproducing

```
python3 scripts/llm_gate_pick.py --build --chars 3400        # writes bundles + shortlist
#   ... read bundle_*.md, write labels.json ...
python3 scripts/llm_gate_pick.py --score .../labels.json     # all 15 sessions
python3 scripts/llm_gate_pick.py --score .../labels.json --clean   # the 8 unpublished ones
```

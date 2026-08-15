# Short interest and direction

Two findings. Short interest does not predict direction, and its failure is
uninteresting. The control arm of the same test found something that partly
overturns a standing conclusion, and that is the part worth reading.

## The data

FINRA's consolidated short interest, free and unauthenticated: **3,468,663 rows,
46,348 symbols, 186 settlement dates, 2017-12-29 to 2025-12-31.** Days-to-cover
present on 83.4% of rows.

Three traps were found building it, each of which would have silently corrupted
the result:

* **The API caps a response at 5,000 rows** regardless of the `limit` asked for,
  with no error and no indication there is more. A cross-section is 12–16k
  symbols, and the rows come back ordered — so a single page would have dropped
  two thirds of the universe *and biased* what remained. Fixed by paging.
* **`daysToCoverQuantity` uses 999.99 as an infinity sentinel** for names with no
  meaningful average volume. It is the 90th percentile of the raw column. Left
  in, days-to-cover reads as enormous for exactly the illiquid microcaps this
  project trades. Now NaN.
* **A third of settlement dates fall on weekends** if you generate them as the
  15th and the last day of the month, and the API answers those with zero rows
  rather than an error. The first pass captured 133 of 193 dates and looked like
  it had succeeded. Rolling to the previous business day recovered the other 53.

Everything is joined with a backward as-of merge on an **availability** date set
ten business days after settlement — FINRA disseminates about eight business days
later, and using the settlement date itself would be look-ahead on precisely the
illiquid names where a week and a half matters.

## Short interest fails all three criteria

Criteria were fixed before running.

**1. Direction among big movers — needed AUC > 0.55.**

| arm | AUC |
|---|---|
| price only | 0.6277 |
| **+ short interest** | **0.6262** |
| short interest only | 0.5575 |

Adding it makes the classifier *marginally worse*. On its own it clears 0.55,
but it carries nothing the price features do not already have.

**2. The squeeze effect — needed +3pp, got +2.53pp, and backwards.**

Days-to-cover deciles, 394,254 covered candidates:

| decile | P(up) | mean | P(+20%) | P(−20%) |
|---|---|---|---|---|
| 0 (lowest DTC) | 46.50% | −0.52% | 5.64% | 7.31% |
| 1 | **51.90%** | +0.54% | 3.24% | 2.44% |
| 5 | 51.05% | +0.34% | 2.66% | 2.14% |
| 9 (highest DTC) | **49.03%** | +0.15% | 3.66% | 3.09% |

Top-versus-bottom is +2.53pp with a CI of [+1.82, +3.21] — statistically real,
below the threshold, and **the wrong shape for the hypothesis**. From decile 1 to
decile 9, P(up) declines monotonically. Heavily shorted names go up *less* often,
not more.

That is the opposite of the squeeze narrative and it agrees with the academic
literature: short sellers are on average informed, and high short interest
predicts weak returns. The squeeze is the memorable case, not the typical one.
Decile 0 is not a counterexample — it has the lowest P(up) *and* the highest
P(±20%), which makes it the high-volatility bucket, not the bullish one.

**3. Ranking — needed +0.25pp.**

```
price only   +1.394%      + short interest  +1.200%
delta -0.195pp   95% CI [-1.337, +0.973]   P(<=0) = 0.6230
```

Fails, and negative.

## The control arm found something

The price-only baseline in test 1 came back at **AUC 0.6277** on which way a big
mover moves. Five earlier results in this repository put direction at chance.
One of them had to be wrong, so `direction_verify.py` pulled the claim apart
along all three axes that could explain it.

| target | sample | split | AUC |
|---|---|---|---|
| sign of 10-session return | all rows | single 60/40 | 0.6550 |
| **sign of 10-session return** | **all rows** | **walk-forward** | **0.6029** |
| sign of 10-session return | FINRA-covered | single 60/40 | 0.6303 |
| **sign of 10-session return** | **FINRA-covered** | **walk-forward** | **0.5877** |
| `y_dir` (excursion) | all rows | single 60/40 | 0.5780 |
| **`y_dir` (excursion)** | **all rows** | **walk-forward** | **0.5334** |
| `y_dir` (excursion) | FINRA-covered | single 60/40 | 0.5751 |
| **`y_dir` (excursion)** | **FINRA-covered** | **walk-forward** | **0.5296** |

Two things separate cleanly.

**The single split was optimistic by about +0.05 everywhere.** That is a general
lesson and it applies to any number in this repository quoted off one split.

**The target explains the rest, and this is the real finding.** Earlier work
asked whether the *upward excursion exceeded the downward one* — `y_dir` — and
that is still at chance, **0.5296–0.5334 walk-forward**. The earlier conclusion
was correct for the question it asked.

But the sign of the **realised ten-session return** is predictable at
**0.5877–0.6029 walk-forward**, on the same rows, with the same features and the
same conditioning. Nobody had asked that question.

The distinction is not academic. `y_dir` asks which way a name *wiggled furthest*
during the window — a name can spike +30% intraday and close down 15%, and
`y_dir` calls that an up. The sign of the terminal return is what a position
actually earns. The harder-sounding question was the less useful one, and it was
the only one being asked.

### What this does and does not mean

**It does not mean direction is solved.** 0.60 is modest, and it is *conditional
on the move being large* — the mask selects `|return| ≥ 20%`, which is the
realised label. You cannot know in advance which names those are. (The earlier
`y_dir` work masked the same way, so the comparison is fair, but neither number
is directly tradeable.)

**It does suggest the pieces compose.** `RESULT_RAMANUJAN.md` found that plain
20-day volatility flags which names move ≥20% at **AUC 0.815**. If that stage
selects the candidates and this one calls the direction at 0.60, the combination
is a materially better position than "direction is at chance" implied — and it
is the first time in this project that a directional number has been meaningfully
above 0.55 out of sample across eleven blocks.

**Nothing here changes the traded book yet.** The ranking test failed, and a
conditional AUC is not a P&L. The next step is the honest one: a two-stage model —
volatility gate, then direction — run through the same walk-forward book as
everything else, with the gate applied on information available at the time.

## Reproducing

```
python3 scripts/short_fetch.py        # ~15 min, 186 settlements, resumable
python3 scripts/short_direction.py    # the three pre-registered tests
python3 scripts/direction_verify.py   # target x sample x split
```

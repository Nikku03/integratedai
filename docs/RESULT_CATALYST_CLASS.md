# Result: classifying 30 days of catalysts, then trading them

Reads every 8-K filed by a small, micro or mid cap in the last 30 days, grades
each one for trap-vs-positive and low/medium/high impact **from the filing text
only**, has a second reader try to knock down every medium and high, and then
runs the survivors through the $80 / two-slot simulator.

Nothing in the grading pass saw a price. `saw_price_outcome` is recorded per
filing and is `false` for all 83.

> **The portfolio numbers in the two sections below are superseded.** A bug
> found later — zero-volume bars triggering stops — inflated them. See the
> addendum at the end for the fix and the corrected figures. The classification
> tables are unaffected; the grid and cohort results are restated there.

## The funnel

| stage | count | share |
|---|---|---|
| 8-Ks, last 30d, small/micro/mid | 791 | 100% |
| after excluding negative item codes | 724 | 92% |
| **tradable** (print at T+1min, ≥$1, prior session ≥$250k, entry bar ≥20× order, ≤10% already moved) | **83** | **10.5%** |
| positives after grading | 26 | 3.3% |
| traps caught | 4 | 0.5% |
| medium or high after challenge | 4 | 0.5% |

The 67 excluded on item code alone were 42 dilution (Item 3.02 / 1.01
financings) and 21 delisting (Item 3.01). Those are the traps the user named,
and they are visible in the item code before anyone reads a word.

**The binding constraint is liquidity, not judgement.** Nine of ten filings die
on the tradability screen before an analyst sees them, overwhelmingly because
the filing landed outside regular hours and nothing printed a minute later.

## Grades

| verdict | impact | n |
|---|---|---|
| trap | medium | 4 |
| positive | high | 1 |
| positive | medium | 3 |
| positive | low | 22 |
| neutral | low | 53 |

Two thirds of everything that survives the liquidity screen is administrative:
shareholder-vote results, director appointments, routine dividend declarations,
earnings that landed in line. That is the honest base rate of an 8-K.

### The four traps

| ticker | band | type | what it was |
|---|---|---|---|
| AMIX | micro | dilution | Cash of $5.1m disclosed alongside a share count that "includes shares issued as part of the Company's recent warrant inducement" — the inducement is the news, buried in a cash update |
| FATN | micro | dilution | Item 7.01 CEO letter answering shareholder anger about a fresh S-3 shelf and ATM, insisting nothing has been sold *yet* |
| IPW | small | dilution | Joinder adding a guarantor to a $30m 6% OID convertible facility, bundled with the formation of an AI-hardware leasing subsidiary that has no customers, no hardware, and "preliminary, non-binding interest" |
| LASE | micro | accounting | Auditor change that discloses, in passing, that the outgoing auditor's FY2025 report carried substantial-doubt going-concern language |

Three of the four are dilution wearing something else's clothes. None of them
would be caught by an item-code filter: AMIX and FATN are Item 8.01/7.01, IPW
leads with 1.01, LASE with 4.01. They need the text read.

### The challenge pass cut 9 of 11

Every medium and high went to a second reader told to knock it down. Two
survived, two were downgraded high→medium, seven were downgraded to low.

| ticker | before | after | why it was cut |
|---|---|---|---|
| ESI | positive/high | **kept** | Acquired by Solstice, $10.00 cash + 0.500 shares ≈ $50.10, 15% premium, ~$14.5bn. Verified verbatim against EX-99.1/99.2 |
| FCFS | positive/medium | **kept** | Record Q2: revenue +29%, GAAP EPS +58%, guidance raised again, new $150m buyback |
| FATN | high → medium | cut | A $7.0m contract is real but it is a school-district order, not a transformation |
| VERA | high → medium | cut | FDA accelerated approval for TRUTAKNA is genuine, but accelerated approval in IgAN follows a crowded label path |
| BMRC | medium → low | cut | 86% of the EPS improvement was seasonal expense timing; the NIM expansion had been pre-guided in the Q1 release; the analyst had conflated special-mention loans with non-accruals |
| BPOP, ARCB, JMSB, FNWD, XRN, NKSH | medium → low | cut | In-line quarters and already-announced deals restated |

The BMRC cut is the one worth keeping. The challenger decomposed the sequential
pre-tax bridge line by line and found the "beat" was a calendar artifact. That
is the failure mode a keyword scanner cannot reach, and it was found without
looking at what the stock did.

## Trading them

$80, two slots, position size = equity/slots so it compounds, entry at the
**high** of the bar one minute after acceptance (pay the offer), 6% target, 10%
stop that fills at `min(stop, bar_low)` so gaps cost what they cost, 240 bars
maximum hold, ambiguous bars booked as stops.

### Medium and high only — 4 candidates, 4 trades

| ticker | band | impact | filed ET | entry ET | entry | exit ET | exit | why | held | ret |
|---|---|---|---|---|---|---|---|---|---|---|
| ESI | mid | high | 07-06 09:13 | 09:30 | 44.31 | 07-06 13:30 | 42.60 | time | 240m | **−3.87%** |
| VERA | small | medium | 07-07 12:45 | 12:47 | 42.47 | 07-07 17:03 | 42.32 | time | 256m | −0.35% |
| FATN | micro | medium | 07-21 10:37 | 10:46 | 4.60 | 07-22 11:32 | 4.88 | target | 1486m | **+6.00%** |
| FCFS | mid | medium | 07-23 15:26 | 15:28 | 191.94 | 07-24 09:36 | 203.46 | target | 1088m | **+6.00%** |

$80 → $83.08, **+3.85%**, mean +1.94%, t = **+0.79**. Four trades is not a
result. It is the supply.

### All positives — 26 candidates, 13 trades

| ticker | band | impact | filed ET | entry ET | lag | entry | exit ET | exit | why | ret | balance |
|---|---|---|---|---|---|---|---|---|---|---|---|
| AVNS | small | low | 07-02 10:10 | 10:12 | 1.5m | 24.92 | 07-02 14:44 | 24.92 | time | 0.00% | 80.00 |
| ESI | mid | high | 07-06 09:13 | 09:30 | 16.8m | 44.31 | 07-06 13:30 | 42.60 | time | −3.87% | 78.45 |
| XRN | mid | low | 07-02 17:26 | 07-06 09:30 | 5283m | 38.10 | 07-08 11:13 | 36.88 | time | −3.20% | 77.17 |
| TCBX | small | low | 07-13 08:05 | 09:30 | 84m | 39.98 | 07-15 16:15 | 40.55 | time | +1.43% | 77.72 |
| MAIN | mid | low | 07-16 09:15 | 09:30 | 14m | 53.68 | 07-16 13:59 | 55.35 | time | +3.10% | 78.93 |
| CCRN | small | low | 07-17 08:19 | 09:30 | 71m | 13.25 | 07-20 10:46 | 13.25 | time | 0.00% | 78.93 |
| FNWD | micro | low | 07-06 16:45 | 07-07 09:37 | 1012m | 36.99 | 07-21 16:55 | 39.21 | target | +6.00% | 81.28 |
| FATN | micro | medium | 07-21 10:37 | 10:46 | 8.4m | 4.60 | 07-22 11:32 | 4.88 | target | +6.00% | 83.65 |
| BPOP | mid | low | 07-23 08:10 | 09:30 | 79m | 175.12 | 07-23 15:01 | 172.15 | time | −1.70% | 82.94 |
| FCFS | mid | medium | 07-23 15:26 | 15:28 | 1.0m | 191.94 | 07-24 09:36 | 203.46 | target | +6.00% | 85.43 |
| PROF | micro | low | 07-24 11:58 | 12:03 | 4.4m | 7.02 | 07-27 09:40 | 7.44 | target | +6.00% | 87.99 |
| CAC | small | low | 07-28 08:05 | 09:30 | 84m | 55.87 | 07-29 14:44 | 59.22 | target | +6.00% | 90.63 |
| JMSB | micro | low | 07-22 08:40 | 09:30 | 50m | 22.89 | 07-29 14:51 | 23.61 | time | +3.17% | 91.92 |

$80 → $91.92, **+14.90%** over 30 days. Mean +2.23%, median +3.10%, win 62%,
**t = +2.16** on 13 trades. Exits: 5 targets, 8 time.

| impact | n | mean | median | win | pnl |
|---|---|---|---|---|---|
| high | 1 | −3.87% | −3.87% | 0% | −$1.55 |
| medium | 2 | +6.00% | +6.00% | 100% | +$4.86 |
| low | 10 | +2.08% | +2.26% | 60% | +$8.61 |

| band | n | mean | pnl |
|---|---|---|---|
| micro | 4 | +5.29% | +$8.57 |
| small | 4 | +1.86% | +$3.19 |
| mid | 5 | +0.07% | +$0.16 |

## Rerun at 4 slots and a shorter hold

Asked for, and it does reach 20 trades — at 4 slots and a 120-bar hold: $80 →
$85.03, **+6.29%**, mean +1.24%, win 65%, t = +2.06. Note the position size is
now $20, not $40, because four slots split the same $80.

But both knobs were turned *after* seeing a result, so the honest presentation
is the whole surface, not that cell. `--grid` sweeps it:

| hold | 2 slots | 3 slots | 4 slots |
|---|---|---|---|
| 30 bars | −0.30% (20t) | −0.18% (20t) | −0.18% (20t) |
| 60 bars | +0.28% (20t) | +0.39% (20t) | +0.32% (20t) |
| 120 bars | +0.69% (17t) | +0.61% (19t) | **+1.24% (20t)** |
| 240 bars | **+2.23% (13t)** | +1.90% (17t) | +1.50% (19t) |
| 240b, same day | −0.38% (20t) | −0.37% (20t) | −0.37% (20t) |
| 240b, ≤24h | +0.57% (20t) | +0.45% (20t) | +0.22% (20t) |

Mean return per trade, trades in brackets. Across 18 cells: mean +0.48%, range
−0.38% to +2.23%, 67% positive, t from −0.80 to +2.24, **3 of 18 cells clear
t > 2** — about what noise delivers at this many looks.

**"20 trades" and "shorter hold" are the same knob, and it is the knob that
kills the return.** The only cells that reach 20 trades are the short-hold ones,
and those cluster at zero. The +14.90% came from *not* taking 20 trades.

### Which exposes what was actually being paid for

| | same session | crossed overnight |
|---|---|---|
| 4 slots / 120 bars | −0.01% (n=10) | **+2.49%** (n=10) |
| 2 slots / 240 bars | −0.62% (n=4) | **+3.49%** (n=9) |

Every dollar came from holding overnight. The two `same day` rows in the grid
are negative at every slot count. **There is no tradable intraday reaction to
the filing** — which is the same conclusion the latency study reached, arrived
at from the other direction.

## The one result that survives: the labels separate returns

An overnight hold being where the money is invites the obvious control — is
overnight simply positive for these names? Trade all 83 filings at a fixed $40
with enough slots that nothing is refused one, so every cohort faces an
identical rule and the portfolio parameters drop out:

| cohort | n | mean | median | win |
|---|---|---|---|---|
| positive | 26 | **+0.95%** | +0.44% | 62% |
| neutral | 53 | **−0.81%** | −0.39% | 43% |
| trap | 4 | **−4.79%** | −5.37% | 50% |

Overnight is *not* generically positive: neutrals held overnight lose 1.21% and
traps lose 14.44%. Only the positives gain.

**positive − neutral = +1.76pp per trade, Welch t = +2.37, p = 0.021**,
Mann-Whitney p = 0.015.

This is a better test than any portfolio number, because both cohorts are drawn
from the same 30 days and the same cap bands — so a July that was kind to small
caps lifts both and cancels. Three confounds, all addressed:

| control | result |
|---|---|
| within micro | pos +2.16% vs neu −2.23%, spread **+4.40pp**, t = +2.80 |
| within small | +0.70% vs −0.20%, +0.90pp, t = +0.77 |
| within mid | +0.29% vs −0.51%, +0.81pp, t = +0.77 |
| band-demeaned (composition can't explain it) | +1.79pp, t = +2.38, p = 0.021 |
| one observation per ticker (14 vs 35 names) | t = **+2.93**, p = 0.006 |
| labels permuted *within calendar day*, 20k draws | **p = 0.0214**, null sd 0.70pp |

The spread is positive in all three bands, strongest where information is
scarcest, and survives collapsing 79 trades to 49 independent names.

### It is still an overnight effect, and it is monotone in hold

| hold | positive | neutral | trap | spread | Welch t | p | per-ticker t |
|---|---|---|---|---|---|---|---|
| 30 bars | −0.51% | −0.81% | −2.29% | +0.30pp | +0.54 | 0.588 | +1.90 |
| 60 bars | +0.09% | −0.91% | −2.19% | +1.00pp | +1.32 | 0.192 | +2.38 |
| 120 bars | +0.95% | −0.81% | −4.79% | +1.76pp | +2.37 | 0.021 | +2.93 |
| 240 bars | +1.45% | −0.91% | −5.94% | **+2.36pp** | +2.54 | 0.013 | +3.17 |
| 120b, same day | −0.09% | −0.48% | −1.43% | +0.39pp | +0.62 | 0.538 | +1.02 |
| 240b, same day | −0.08% | −0.49% | −1.88% | +0.42pp | +0.69 | 0.495 | +0.82 |
| 240b, ≤24h | +0.37% | −0.80% | −1.72% | +1.17pp | +1.72 | 0.091 | +1.88 |

Unlike the portfolio return, **the sign never flips** — all seven hold rules
give a positive spread and a positive per-ticker t. What changes is magnitude,
and it grows with hold length while the same-day variants collapse to nothing.

That makes this post-event *drift*, not a latency or reaction effect. The market
prices the filing's content over the following sessions, not in the next two
hours. It is the same shape as the +0.82% CAR+20 the eleven-year panel showed on
micro caps, which is mildly reassuring about both.

**The trap column is the cleanest thing here.** −2.29% → −5.94%, monotone
worsening with hold length, on filings a reader flagged from text alone with no
price visible. Dilution gets punished more the longer you hold it, which is
exactly what it should do. n = 4, so it is a direction, not a measurement.

## What to believe and what not to

**No portfolio number here is evidence.** 3 of 18 grid cells clear t > 2 and the
sign flips between neighbouring cells, which is the signature of a parameter
doing the work rather than the catalysts. The pre-registered 2015–2026 test on
the same machinery came out at −0.15% per trade. Thirty days cannot overturn
eleven years; it can only fail to.

**The cohort spread is the exception, and it needs one thing before it counts:
a second month.** p = 0.021 on 79 trades in 59 names over 30 days, with labels
produced by a specific set of readers on a specific month's filings. The test is
cheap to repeat — `--cohorts` on any other 30-day window — and until it has
been, the honest status is "one encouraging month", not a finding.

**Only the spread is measured, and the spread is not the trade.** Long positives
is +0.95% *gross of transaction cost* on names priced at $4.60. Harvesting it
long-only means paying a cost minute bars cannot see; harvesting it long/short
means shorting micro caps at $20 a side, which no retail account does. The
+1.76pp separation is real in the sense that it is not composition, day effects
or repeated names. It is not yet a strategy.

**Two trades returned exactly 0.00%** (AVNS, CCRN) because the exit bar's low
equalled the entry bar's high — nothing printed in between and the price
carried forward. That is the same staleness that dominated the latency study,
and it means "flat" here sometimes means "untradable", not "unchanged".

**The impact grade did not predict the return.** The single high-impact event
was the worst trade in the book, and the ten low-impact events carried 72% of
the profit. n = 1 in the high bucket makes this uninterpretable in either
direction, but it is the opposite of the hypothesis: reading the filing harder
did not find the money.

**The cap monotonicity survives here.** Micro +5.29%, small +1.86%, mid +0.07%
— the same ordering as the +0.82% CAR+20 on micro caps in the eleven-year
panel, and the same ordering the cost model says should be *reversed* once
spread is charged properly. Minute bars carry no quotes, so the spread on a
$4.60 micro cap is not in these numbers at all, and at $40 an order it is the
entire economics. This is the open question, not a finding.

**Survivorship is untested here.** The 30-day window is too short for a
delisting to bite, so nothing in this table is protected against it. The
eleven-year panel showed survivorship bias on micro caps to be roughly the same
magnitude as the entire measured edge.

**The one durable result is the trap screen.** 67 caught on item code, 4 more
caught only by reading, 3 of those 4 dilution disguised as something else. That
part is mechanical, verifiable, and does not depend on any return being real.

---

# Addendum: were there 10%+ moves, and why did we catch none?

## A bug found while asking, which changes numbers above

`trail 20%` on AMIX returned +2.6% on a name whose ceiling was +170% and whose
worst drawdown was −1.5%. That is arithmetically impossible, and the cause was
real: **bar 2084 reports `high=3.70, low=2.75, volume=0`** — a 35% range in a
minute during which nothing traded. The stop was triggered by a print that did
not exist.

**495,992 of 2,096,525 minute bars in the cache (23.7%) have zero volume, and
22,180 of those carry a high-low range wider than 2% of price** — stale quotes
in thin pre- and post-market sessions, ranging up to 84%. Entry already required
`volume > 0`; exits did not. The asymmetry is what makes it damaging: a phantom
*low* stops a winner out, while a phantom *high* is never honoured as a fill, so
the error only ever runs one way.

Fixed in `catalyst_sim.py`, `moonshot_scan.py` and `latency_trade.py`: a bar
with no volume cannot trigger a barrier or serve as an exit price, and a time
exit walks back to the last bar that traded.

What it changed:

| | before | after |
|---|---|---|
| grid cells clearing t > 2 | 3 of 18 | **0 of 18** |
| cohort spread | +1.76pp, p = 0.021 | **+1.93pp, p = 0.012** |
| within-day permutation | p = 0.0214 | **p = 0.0066** |
| AMIX under `trail 20%` | +2.6% | **+113.1%** |
| moonshot peaks in untradably thin minutes | 8 of 24 | **0 of 23** |

The portfolio return loses its last significance — it was partly phantom stops.
The cohort test gets stronger, because the phantom stops were adding noise to
both cohorts.

## Yes. 23 of 83 filings (28%) had a 10%+ move available

Hindsight ceiling — the highest price that actually printed after the entry bar.
Not achievable, but it bounds what any exit rule could have taken.

| | n | share with ≥10% available | median ceiling | median trough |
|---|---|---|---|---|
| trap | 4 | **75%** | **+26.7%** | −7.3% |
| positive | 26 | 31% | +3.9% | −1.8% |
| neutral | 53 | 23% | +4.2% | −6.0% |

Biggest: **AMIX +170.5%**, IPW +37.2%, KLRS +30.1%, SLNG +28.5%, FNWD +21.4%.

## We caught none of them, for two independent reasons

**One: a 6% target caps every winner at exactly 6%.** That is arithmetic about
the rule, not a fact about the market. Fifteen of the 23 moonshots were entered
and exited at +6.0% while the price kept going.

**Two: the two biggest were classified as traps and deliberately skipped.**
AMIX was the warrant-inducement disclosure. IPW was the $30m OID convertible
bundled with a customerless AI subsidiary. Both were flagged from the filing
text, both were skipped, and they ran +170% and +37%.

**The moonshots concentrate in exactly the cohort the screen exists to remove.**
Avoiding dilution and catching spikes are the same decision made in opposite
directions — the promotional microcap that dilutes is the one that squeezes.
The screen is not free, and this is its price.

AMIX was genuinely takeable: the entry minute traded $6,384 against a $40 order,
and the peak minute traded **$12,990,756**. That top was exitable. Declining it
was a real, costly, defensible choice — the trap cohort's median trough is −7.3%
and IPW drew down −46.7% before recovering.

## Dropping the profit cap helps, modestly and robustly

Per filing, no portfolio:

| rule | positive | t | neutral | spread | p | ≥10% caught |
|---|---|---|---|---|---|---|
| 6% target / 10% stop | +1.30% | +1.32 | −0.05% | +1.35pp | 0.296 | **0** |
| no target / 10% stop | **+2.84%** | +1.96 | −0.33% | +3.17pp | 0.072 | 7 |
| trail 10% | +2.01% | +1.64 | −1.71% | **+3.72pp** | **0.014** | 4 |
| trail 15% | +2.62% | +1.71 | −0.03% | +2.65pp | 0.153 | 9 |
| trail 20% | +2.59% | +1.67 | +0.45% | +2.14pp | 0.264 | 8 |
| trail 25% | +2.59% | +1.67 | +0.52% | +2.07pp | 0.275 | 8 |

**All five no-target variants beat the 6% target on the positive cohort**, which
is what makes this more than a lucky cell. Paired per filing, dropping the
target outright is **+1.54pp, t = +2.08, p = 0.048** — better on 7 of 26 filings
and worse on only 2. The asymmetry is the whole point: a target costs you
nothing on the 17 that go nowhere and everything on the few that run.

## What this does not license

**The trap cohort's trailing returns are one name.** `trail 15%` shows +35.76%
mean on traps; that is AMIX at +128.0% inside n = 4. LASE returns −11.5%. Four
observations, one of which is 85% of the mean, is an anecdote.

**None of the positive-cohort t-statistics clear 2.** +2.84% at t = +1.96 on
n = 26 in one month is a direction, not a measurement. The paired test clears
p = 0.05 only because pairing removes the between-filing variance — it says the
*rule change* is an improvement, not that the underlying return is real.

**Chasing the moonshots means inverting the trap screen**, and the eleven-year
panel plus the latency study both say that filings which have already moved are
where the losses concentrate (−2.59% to −3.30% for filings up ≥2% before entry).
One AMIX does not overturn that; it explains why the tail is worth measuring
separately rather than trading.

---

# Addendum 2: selecting for the tail, then letting winners run

Removing the profit target only pays if the filings it is applied to can
actually produce a tail. So: rank filings by ex-ante moonshot propensity, take
the top slice, exit with a trailing stop and no target.

## Features fixed before measuring, and one of them was wrong

Picking predictors after seeing which filings ran is how you fit noise on 83
observations. Four features, chosen on mechanical grounds and stated in
`moonshot_select.py` before any of this was run:

| feature | reason it should predict tail size |
|---|---|
| `pre_vol` | Realised vol of the stock's own minute returns over the prior 5 sessions. A name that moves 0.4%/day does not produce 20% because a release was good. This is the scale parameter of the whole distribution. |
| `illiq` | Prior-session dollar volume, inverted. Depth absorbs demand; thin books make tails. |
| `cheap` | Reciprocal price. A $2 stock moves in ticks that are whole percents. |
| `binary` | Step change (merger, FDA, contract, financing, going concern) vs recurring disclosure (earnings, dividends, officer changes). Assigned from item codes and filing text, never from the return. |

Equal-weight rank average, no fitted coefficients.

**`binary` — the catalyst-type feature — carries no tail information at all.**

| selector | median ceiling | ≥10% hit rate | p vs random |
|---|---|---|---|
| `pre_vol` alone | +5.95% | **65%** | **0.0001** |
| `cheapness` alone | +4.17% | 65% | **0.0000** |
| `illiquidity` alone | +3.76% | 50% | 0.0185 |
| **`binary` alone** | +0.80% | **25%** | **0.7588** |
| composite (all four) | +3.52% | 60% | 0.0008 |
| composite without `binary` | +4.17% | 60% | 0.0008 |
| *(base rate, whole pool)* | +1.50% | *29%* | — |

A binary catalyst hits ≥10% **less often than the base rate**. Splitting the
pool on it gives +4.33% median ceiling for step changes against +4.35% for
routine disclosure — no separation whatsoever. Dropping it from the score makes
the median-based test go from p = 0.079 to p = 0.033.

**The stock predicts the tail. The catalyst does not.** That is the opposite of
the hypothesis, and it is the most useful thing in this addendum: what a filing
*is about* tells you much less about how far the price can travel than how far
that particular stock normally travels.

## Cross-sectionally the selection works

Top 20 of 80 by composite score, exit `trail 20%`, no target:

| | n | mean | median | win | ≥10% ceiling | best |
|---|---|---|---|---|---|---|
| **selected** | 20 | **+11.10%** | +3.52% | 75% | **60%** | +113.1% |
| not selected | 60 | +0.02% | +0.87% | 57% | 18% | +12.5% |
| whole pool | 80 | +2.79% | +1.50% | 61% | 29% | +113.1% |

Against 20,000 random picks of 20 from the same pool: **p = 0.0006** on the
mean, **p = 0.0008** on the ≥10% hit rate.

The mean is fragile and the hit rate is not:

| variant | mean | p | ≥10% | p |
|---|---|---|---|---|
| all 80, top 20 | +11.10% | 0.0006 | 60% | 0.0008 |
| AMIX removed | +5.88% | 0.0016 | 60% | **0.0004** |
| traps excluded | +4.72% | 0.0118 | 55% | **0.0014** |

AMIX alone is +5.66pp of the +11.10%. The *return* estimate is one name; the
*hit rate* survives removing it, excluding traps, and a median-based test on the
no-`binary` score.

## But it does not survive an $80 account

Removing the target roughly doubles how long positions are held:

| exit rule | median hold | 75th pct | stops | targets | time exits |
|---|---|---|---|---|---|
| 6% target / 10% stop | 125.5h | 277.5h | 14 | 28 | 41 |
| trail 20% | **196.3h** | 360.5h | 8 | 0 | **75** |

The trailing stop almost never fires — 75 of 83 exits are the 10-session cap.
"Trail 20%" is in practice "hold ten sessions". At a 196-hour median hold you
get about **3.7 trades per slot per month**.

Running it chronologically with causal selection — each filing ranked against
only the `pre_vol` of filings already seen, never the month's distribution:

| slots | size | pctile | trades | end $ | total | mean | t | caught AMIX? |
|---|---|---|---|---|---|---|---|---|
| 3 | $26.67 | 0.70 | 6 | 84.96 | +6.19% | +3.34% | +0.53 | no |
| 6 | $13.33 | 0.70 | 9 | 83.52 | +4.41% | +3.02% | +0.67 | no |
| 8 | $10.00 | 0.70 | 12 | 83.08 | +3.86% | +2.70% | +0.71 | no |
| 12 | $6.67 | 0.00 | 17 | 83.93 | +4.91% | +3.46% | +1.50 | no |
| 16 | $5.00 | 0.70 | 21 | 82.48 | +3.10% | +2.45% | +1.03 | **no** |

**AMIX never trades in any configuration.** At 16 slots, 47 of 80 filings are
refused a slot, and the refusals include AMIX (+113%), IPW, and both FATNs. The
moonshots arrive when the book is already full.

The capacity this actually needs:

| pool | max concurrent positions | capital at $40/position | slot size on $80 |
|---|---|---|---|
| take everything | 59 | $2,360 | $1.36 |
| top 30% by `pre_vol` | **21** | **$840** | $3.81 |

**That is the finding.** The cross-sectional edge is real and the exit rule is
right, but harvesting it needs roughly $840, not $80. At $80 the choice is
between few slots that miss the moonshots and many slots holding $5 positions —
four shares of IPW at $1.05, where a one-cent spread is a full percent and any
commission is fatal.

## What this changes

**The target is not the binding constraint. Capacity is.** Removing the 6%
target was correct — it beat the target on every variant — but it converts a
throughput problem into a capital problem, and the second is harder on $80.

**Two bugs were fixed getting here**, both of which had moved numbers:
`portfolio()` joined filings on ticker alone, so a name with two filings in the
window cartesian-joined and the surviving row carried the other filing's
timestamp, silently moving the entry. And `pre_event_features` drops
zero-volume bars before estimating volatility — leaving them in understates vol
through long runs of unchanged prints and overstates depth.

**`pre_vol` alone is the honest selector**, not the four-feature composite. It
is stronger on every robust measure (65% hit rate, p = 0.0001; median +5.95%,
p = 0.0032), and it needs no judgement about what a filing means. Reported here
as the post-hoc simplification it is — it was one of four pre-specified
features, not chosen after the fact, but it *was* promoted after seeing the
comparison.

**Still one month, still 80 filings, still needs a second window.**

---

# Summary: every configuration, all post-fix

30-day window (2 July – 29 July 2026), 83 tradable 8-Ks from small/micro/mid
caps. Entry at the high of the bar one minute after EDGAR acceptance. All
figures below are after the zero-volume-bar fix and the accession-join fix.

## On the $80 account as specified

| config | trades | start | end | **ROI** | mean | median | win | best | worst | maxDD | PF | t |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **2 slots, 6% tgt, 240 bars** (original spec) | 15 | $80 | **$90.83** | **+13.54%** | +1.77% | +1.43% | 53% | +6.0% | −4.6% | −3.5% | 2.85 | +1.69 |
| 3 slots, 6% tgt, 240 bars | 19 | $80 | $88.31 | +10.39% | +1.62% | +1.43% | 58% | +6.0% | −4.6% | −2.0% | 2.83 | +1.89 |
| 4 slots, 6% tgt, 240 bars | 20 | $80 | $86.38 | +7.98% | +1.58% | +1.22% | 60% | +6.0% | −4.6% | −1.5% | 2.89 | +1.94 |
| **4 slots, 6% tgt, 120 bars** (the 20-trade ask) | 20 | $80 | **$84.83** | **+6.03%** | +1.19% | +0.44% | 65% | +6.0% | −3.9% | −1.2% | 3.56 | +1.94 |
| no target, 3 slots, trail 20%, top 30% | 6 | $80 | $84.96 | +6.19% | +3.34% | +5.82% | 67% | +22.7% | −16.6% | −7.1% | 1.63 | +0.53 |
| no target, 12 slots, trail 20%, no select | 17 | $80 | $83.93 | +4.91% | +3.46% | +3.06% | 71% | +22.7% | −16.6% | −1.4% | 2.72 | +1.50 |
| no target, 8 slots, trail 20%, top 30% | 12 | $80 | $83.08 | +3.86% | +2.70% | +5.45% | 67% | +22.7% | −16.6% | −4.4% | 1.57 | +0.71 |
| no target, 16 slots, trail 20%, top 30% | 21 | $80 | $82.48 | +3.10% | +2.45% | +4.27% | 71% | +22.7% | −16.6% | −2.7% | 1.67 | +1.03 |

**Not one configuration reaches t = 2.** The highest is +1.94. Every ROI in that
table is statistically indistinguishable from zero over 30 days.

And the ranking runs *inverse to trade count* — the fewest trades produced the
highest ROI. That is the signature of noise, not edge: fewer draws, wider spread,
and the top of the list is whichever configuration happened to catch the good
ones.

## With enough capital that slots stop binding

The no-target rule needs 21 concurrent positions to never refuse a moonshot:

| config | trades | start | end | **ROI** | mean | win | best | maxDD | PF | t |
|---|---|---|---|---|---|---|---|---|---|---|
| $840, 21 slots ($40 each), top 30% | 26 | $840 | **$900.48** | **+7.20%** | +5.95% | 69% | **+113.1%** | −2.1% | 2.78 | +1.26 |
| $840, 21 slots, no selection | 29 | $840 | $874.31 | +4.08% | +2.97% | 69% | +22.7% | −1.4% | 2.25 | +1.72 |
| $2,360, 59 slots, everything | 68 | $2,360 | $2,445.88 | +3.64% | +3.18% | 62% | +113.1% | −0.8% | 2.44 | +1.68 |

At $840 the strategy finally catches AMIX: **+113.1% on a $39.17 position =
+$44.28**. That single trade is +5.3pp of the +7.20% ROI. Strip it out and the
other 25 trades return roughly +1.9%.

So the honest reading of the best-looking number in this whole study is: one
trade, in one month, on a filing that a reader correctly flagged as a dilution
trap and that the strategy bought anyway.

## What is actually significant

None of the ROIs. Two cross-sectional results are:

| result | effect | p |
|---|---|---|
| positive-graded filings beat neutral-graded | +1.93pp per trade | **0.012** (0.0066 by within-day permutation) |
| tail selection by `pre_vol` beats random | 60–65% hit ≥10% vs 29% base | **0.0001–0.0008** |

Both are statements about *relative* cross-sections measured on 79–80 filings in
one month. Neither is a P&L, and neither has been replicated on a second window.

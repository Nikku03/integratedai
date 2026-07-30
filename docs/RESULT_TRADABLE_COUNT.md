# Result: how many trades are really available, with no peeking

The question: at each week, using only what was known then, how many names are
eligible, how many can be held on $80, and does ranking them by the model beat
drawing the same number out of the same hat?

Everything here reads the out-of-fold predictions from the pre-registered
2015–2026 run. No model is refitted, no threshold re-chosen. The OOF frame is
causal by construction — each prediction comes from a purged walk-forward fold
trained only on data before its boundary — which is what makes a
random-selection control meaningful rather than circular.

**2,535,913 candidate rows, 3,493 names, 278 weeks, 2020-08-28 to 2025-12-15
(5.3 years).** The window starts in 2020 because the splitter reserves the first
half of the sample for initial training.

## Opportunity is not the constraint. Not remotely.

| eligible names per week | |
|---|---|
| median | **9,305** |
| p10 / p90 | 7,567 / 10,479 |
| min / max | 1,733 / 11,365 |
| weeks with fewer than 5 candidates | **0 of 278** |

There is never a shortage of things to trade. Every earlier "we only got 13
trades" was a *capacity* statement, never a supply one.

## Trade count is a free parameter, and every setting is flat

| k/week | trades | /month | gross | cost | net | t naive | **t week-clustered** | win% |
|---|---|---|---|---|---|---|---|---|
| 1 | 278 | 4.4 | +0.776% | 0.678% | +0.098% | +0.24 | +0.24 | 45% |
| 2 | 556 | 8.7 | +0.593% | 0.677% | −0.084% | −0.29 | −0.26 | 44% |
| 3 | 834 | 13.1 | +0.601% | 0.677% | −0.075% | −0.32 | −0.26 | 45% |
| **5** | **1,390** | **21.8** | +0.597% | 0.678% | **−0.081%** | −0.44 | **−0.34** | 45% |
| 8 | 2,224 | 34.9 | +0.489% | 0.678% | −0.189% | −1.31 | −0.87 | 44% |
| 12 | 3,336 | 52.4 | +0.579% | 0.678% | −0.099% | −0.85 | −0.48 | 44% |
| 20 | 5,560 | 87.3 | +0.783% | 0.679% | +0.104% | +1.16 | +0.57 | 45% |
| 30 | 8,340 | 130.9 | +0.730% | 0.680% | +0.050% | +0.69 | +0.29 | 44% |
| 50 | 13,900 | 218.2 | +0.650% | 0.680% | −0.030% | −0.53 | −0.18 | 44% |

k=5 was the pre-registered setting. **k=20 shows a positive +0.104% and it is
noise** — clustered t=+0.57, and scanning nine values of k needs |t|>2.77 to
survive Bonferroni. Every k lands between t=−0.87 and +0.57. Net is
indistinguishable from zero at every trade count on offer.

## The model is a genuinely good ranker

Two separate controls, both saying the ranking is real:

**Random draws from the identical weekly pool** (2,000 draws, k=5, same calendar,
same universe, same position count — only the names inside each week differ):

| | net/trade |
|---|---|
| model top-5 by EV | **−0.081%** |
| random 5 from same pool | −0.560% |
| **advantage** | **+0.479pp** |
| null sd | 0.167pp |
| | **+2.9 null-SDs, p = 0.002** |

**Paired per-week** (model's top-5 mean minus that same week's whole-pool mean —
removes the calendar entirely): **+0.485pp, paired t = +2.35, p = 0.020**,
Wilcoxon p = 0.051. It beat its own pool in 147 of 278 weeks (53%), so the
advantage is magnitude in the good weeks, not consistency.

Precision on spikes: **25.9% against a 21.3% base rate, 1.21× lift.** Consistent
with the AUC of 0.7056 the pre-registered run measured on 2.5m rows.

## But the universe it ranks loses money

| | net/trade |
|---|---|
| hold every eligible candidate | **−0.582%** |
| model's top 5 per week | −0.081% |

**The model recovers +48bp of a −58bp hole and lands just short of zero.** That
is the whole result in one line: *a good ranker of a universe that loses money.*

And the cost is why:

| at k=5 | |
|---|---|
| gross return | **+0.597%** |
| round-trip cost | **0.678%** |
| net | −0.081% |
| | **cost is 1.1× the gross edge** |

### The cost model is not the culprit

`cost_rt` = 2 × (0.5bp commission + 30bp half-spread on news days + 45bp ×
√(order/ADV)). It ranges 0.615%–0.811% and **correlates −0.935 with log ADV**, so
it varies with liquidity as a real cost model should rather than sitting at a
constant. Selected names have median ADV $7.2m (p25 $2.35m), and the implied
order is roughly $42k.

At an $80 order the impact term vanishes entirely and the cost would be about
61bp rather than 68bp — so if anything this is **slightly conservative** for a
tiny account. Reducing cost to 61bp moves net from −0.081% to about −0.01%: still
zero. The cost model is defensible and it is not what is being hidden behind.

## What an $80 account can actually absorb

Average hold is 7.1 trading days. The k=5/week stream demands **5.9 concurrent
positions on average and 14 at peak.**

| slots | position size | capacity | share of the signal stream |
|---|---|---|---|
| 2 | $40.00 | 6.0 trades/month | **27%** |
| 3 | $26.67 | 8.9 | 41% |
| 4 | $20.00 | 11.9 | 55% |
| 8 | $10.00 | 23.8 | 100% |

To take every signal you need **14 slots — $560 at $40 a position.** On $80 that
is $5.71 per slot.

**So the direct answer: on $80 with two $40 slots you can really trade about 6 of
the 22 signals a month the model produces.** Not because the signals run out —
there are 9,305 candidates a week — but because a 7-day hold and two slots is a
throughput of six.

## The finding that undermines all of the above

**The price panel is 100% survivors.**

| | |
|---|---|
| tickers in the panel | 5,395 |
| series still running within 1 year of 2025-12-31 | **5,394 (100.0%)** |
| series ending more than 1 year early | **1** |

An unbiased 11-year US equity panel loses 4–8% of names a year to delisting,
bankruptcy and acquisition, so roughly **49–60% of names should end early.** This
one has 0.02%. Every company that died between 2015 and 2025 is absent.

The ticker list was assembled from a current snapshot, which means:

**The gross +0.597% is measured only on companies that survived, so it is
overstated and net is worse than −0.081%.** The strategy selects high-volatility,
low-priced names — exactly the delisting-prone population — so the selected set is
biased more than the universe. Order of magnitude: performance-related delistings
average roughly −30% on the delisting return, and if the selected names carry
several times the base delisting hazard over a 7-day hold, the correction is
single-digit to low-double-digit basis points per trade. Against a net of −8bp
that is not a rounding error.

**One thing survives it.** The model-versus-random comparison is a *within-pool*
comparison — both arms draw from the same survivor-only universe — so the +48bp
ranking advantage is far more robust to this bias than the absolute level. The
ranking skill is probably real. The level is optimistic and already negative.

Fixing this needs delisting-inclusive vendor data (Polygon, Norgate, CRSP). The
`CsvPrices` loader is the hook. Until then, **no absolute return number in this
repository should be believed**, including the ones in the addenda above.

## Summary

| question | answer |
|---|---|
| how many candidates per week? | 9,305 median — never the constraint |
| how many signals does the model emit? | 21.8/month at the pre-registered k=5 |
| how many can $80 with 2 slots take? | **~6/month** (27% of the stream) |
| how much capital to take all of them? | $560 (14 concurrent positions) |
| does the model pick better than random? | **Yes: +0.485pp, paired t=+2.35, p=0.020** |
| does it make money? | **No: −0.081%/trade, clustered t=−0.34** |
| is that number reliable? | **No — 100% survivor panel makes it optimistic** |

---

# The actual portfolio: start, end, and one month

$80, two $40 slots, the model's signal stream walked in date order, net of the
run's own cost model. Slot contention resolved by the calendar; same-day ties
broken on expected value, which is knowable at that moment.

The stream is the pre-registered selection: **1,386 trades, 2020-08 to 2025-12.**
Two slots absorb **420 of them (30%)**; 966 are skipped for no free slot. That is
**6.6 trades a month.**

## Full period

| | |
|---|---|
| start | **$80.00** |
| end | **$28.67** |
| total | **−64.16%** over 64 months (5.3 years) |
| CAGR | **−17.50%** |
| max drawdown | **−79.8%** |
| months up | 25 of 64 (39%) |
| monthly sd | 10.17% |
| best / worst month | +20.95% / −31.23% |
| t on mean monthly return | −0.84 → indistinguishable from zero |

## One month, which is what was asked

Bootstrapped from the same 420 trades — 7 trades, $80 start, two slots,
compounding at equity/2 — over 20,000 paths:

| percentile | end balance | return |
|---|---|---|
| p5 | $67.83 | −15.2% |
| p25 | $73.71 | −7.9% |
| **p50 (median)** | **$78.47** | **−1.9%** |
| p75 | $83.76 | +4.7% |
| p95 | $91.83 | +14.8% |
| **mean** | **$78.95** | **−1.32%** |

**42% of months end up.** A typical month on $80 takes about seven trades and
ends around **$78.50**.

## The realised path was not unlucky

Resampling the same 420 trades over 20,000 compounded paths:

| percentile | final balance |
|---|---|
| p5 | $9.52 |
| p25 | $18.69 |
| p50 | $30.32 |
| p75 | $48.96 |
| p95 | $98.64 |
| mean | $39.15 |

**The realised $28.67 sits at the 47th percentile.** It is a median outcome, not
bad luck. **91% of paths end below $80; 65% end below $40; 1% end above $160.**

## Two things worth being precise about

**Sequence, not edge, produced the −64%.** The first 18 months lost **$53.49** on
121 trades at −1.666% each, while positions were still $40. The remaining 46
months *made* **+$2.16** on 299 trades at +0.189% each — but by then positions
were $10, so recovering was arithmetically impossible. With two slots on $80 the
outcome is dominated by path, and this path front-loaded the losses.

**The per-trade figure to quote is −0.154%, not the −0.081% above.** That −0.081%
came from re-selecting k=5 on the OOF frame myself; the pre-registered run applied
further filters (`min_ev`, `max_per_day`) and its stream averages **−0.154%**,
matching the −0.15% in `RESULT_2015.md`. The pre-registered number is the one that
counts.

The 420 taken trades average −0.345%, worse than the −0.154% stream, but that gap
is **0.6 standard errors** (SE 0.339% on n=420, sd 6.95%). Slot contention is not
selecting bad trades; it is selecting an arbitrary 30% of them, and this draw came
in slightly below average.

## And it is still an optimistic bound

Every number on this page comes from a panel in which 5,394 of 5,395 tickers were
still listed at the end. Correcting for the roughly half of names that should have
delisted makes all of it worse.

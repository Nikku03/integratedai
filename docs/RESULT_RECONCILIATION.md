# Which strategy is which

Four different strategies have been tested in this repository and they are easy
to confuse, because all of them are "buy a small cap after something happens".
They differ in the trigger, the bar resolution, the holding period and the
sample — and they produce different numbers for different reasons. This page
exists because those numbers got reported next to each other without the
distinction being made.

| | trigger | bars | hold | sample | trades |
|---|---|---|---|---|---|
| **A. Latency trade** | EDGAR filing, enter T+1min | 1-minute | hours | 1,203 filings, 28 days | — |
| **B. Catalyst trade** | 8-K, classified, enter T+1min | 1-minute | 4h–10 sessions | 83 filings, July 2026 | 13–20/mo |
| **C. Next-open trade** | any 8-K, enter next session open | daily | 1–10 days | 1,861 filings, July 2026 | — |
| **D. ML moonshot model** | weekly EV rank, no catalyst | daily | 7.1 days | 1,386 trades, 5.3 years | 22/mo |

**The portfolio numbers in the preceding document — $80 → $28.67, −64% —
are strategy D.** They are not the 1-minute catalyst trade.

## A. The latency trade: died on liquidity

Enter one minute after EDGAR accepts a filing.

| | |
|---|---|
| filings fillable at T+1min | **16.2%** |
| filings arriving outside regular hours | **92%** |
| median entry lag (waiting for a market) | 29.3 min |
| return at every horizon, realistic fill | **−0.92% to −1.22%** |

**Five filings in six cannot be traded a minute later at any price** — not a wide
spread, no print at all. The mechanism fails before information is reached. Full
detail in `RESULT_LATENCY.md`.

## B. The catalyst trade: the 1-minute strategy, actually simulated

This is the one the conversation was building: 8-Ks from small/micro/mid caps,
read and graded from filing text, traps excluded, entered at the high of the bar
one minute after acceptance, on 1-minute bars.

Funnel: **791 8-Ks → 724 after item-code exclusion → 83 tradable → 26 positive.**

| config | trades | start | end | total | mean | t |
|---|---|---|---|---|---|---|
| 2 slots, 6% target, 240 bars | 15 | $80 | **$90.83** | **+13.54%** | +1.77% | +1.69 |
| 4 slots, 6% target, 120 bars | 20 | $80 | **$84.83** | **+6.03%** | +1.19% | +1.94 |

**One month. n=15–20. Neither clears t=2, and across the full 18-cell
slots × hold grid, zero cells clear t=2** (they did before the zero-volume bar
fix; three cells cleared, and all three were phantom stops).

So the honest statement for the 1-minute catalyst trade is: **$80 → $85–91 in
July 2026, on 30 days of data, not distinguishable from zero.**

### And it structurally cannot see the moonshots

The move census found **59 8-K-driven 20%+ movers** in the same window. This
pipeline classified **zero** of them:

| stage | surviving |
|---|---|
| had an 8-K within 7 days of a 20%+ move | 59 |
| survived the filing scan (covered 52% of universe) | 46 |
| survived pool construction (298 kept of 1,581 8-K filers) | 8 |
| survived the T+1min tradability screen | **0** |

**17 of the last 8 names' 18 filings arrived outside regular hours.** The
1-minute entry rule requires a market that is open when 92% of filings are not —
which is finding A arriving from the other direction.

## C. The next-open trade: the honest fix, and it fails

Drop the 1-minute requirement, enter at the next session's open. Tested on
**every** 8-K in the window with no conditioning on the outcome — 1,861 filings,
1,280 names:

| held | mean | t |
|---|---|---|
| open → close | −0.39% | −2.98 |
| +1 day | −0.84% | −4.69 |
| +5 days | −1.76% | −7.18 |
| +10 days | **−2.55%** | **−8.99** |

Significantly negative at every horizon on the largest sample in the project.
Only item 2.02 (earnings) is positive: +0.78%, t=+2.13, n=577. Item 3.02 (equity
issued) is worst at −11.61%, t=−5.70.

## D. The ML moonshot model: the −64% number

No catalyst at all. Weekly expected-value ranking on daily features, 7.1-day
holds, pre-registered over 2015–2026. **This is the strategy whose $80 → $28.67
was just reported**, and it is a different thing from the 1-minute trade.

| | |
|---|---|
| gross alpha | +0.524%/trade |
| cost | −0.678%/trade |
| net | −0.154%/trade |
| beats random selection | +0.41pp, paired t=+2.35 |
| $80, 2 slots, 64 months | **$80 → $28.67 (−64%)** |

## So what is the answer to "aren't we doing the 1-minute thing?"

**Yes, that was strategy B, and its number is $80 → $85–91 for July 2026, not
$28.67.** But three things stop that being good news:

**It is one month at n=15–20.** t=+1.69 and +1.94, and zero of eighteen
parameter cells clear t=2. There is no version of 30 days and 20 trades that
establishes an edge.

**It cannot reach the moonshots by construction.** Zero of 59 8-K-driven 20%+
movers survived its screen, because the moonshot filings land after hours where
nothing prints at T+1min. The strategy is structurally confined to the 8% of
filings that arrive during regular hours.

**The only large-sample test of the same idea is strongly negative.** Relaxing
the entry to the next open — which is what you must do to reach the other 92% —
gives −2.55% at ten days with t=−8.99 across 1,861 filings.

Strategy D's −64% is not evidence against strategy B. It is a separate,
better-powered failure of a separate idea. What they share is the reason:

| strategy | gross edge | cost | verdict |
|---|---|---|---|
| B (1-min catalyst) | unmeasured, n too small | ~60bp spread at $40 | undetermined, 1 month |
| C (next open, 1,861 filings) | **negative before costs** | — | fails on sign |
| D (ML model, 1,386 trades) | +52bp | 68bp | fails on cost |

**C and D fail for opposite reasons and B has not been measured.** The honest
position on the 1-minute catalyst trade is not that it lost money — it is that
30 days cannot tell you, and the two adjacent tests that *are* powered both come
out negative.

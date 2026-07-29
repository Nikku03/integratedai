# What moves the price, in what order, and how much is left for you

> "We are not fighting institutions' million-dollar analyst tools. We are
> fighting market and mass-trader sentiment."

That is a testable claim about **who prices what, and when**. This document is
the test, run on 106 small/mid caps over 2021–2024, 37,562 events.

The answer is: **the cascade you described is real and measurable. The
direction is not.**

---

## 1. The ordering — and the filing does come first

`cascade.lead_lag()` finds every pair of event kinds that landed on the same
name within five days and measures which arrived first.

| first | second | pairs | median gap | % second-after-first | leader |
|---|---|---|---|---|---|
| `8-K.2.02` (earnings) | volume surge | 879 | **+23.1 h** | 82% | **filing** |
| `8-K.7.01` (press release) | volume surge | 420 | **+8.6 h** | 72% | **filing** |
| `8-K.2.02` | breakout | 357 | +22.5 h | 72% | **filing** |
| `8-K.2.02` | news attention | 53 | +7.7 h | 68% | **filing** |
| `insider.buy` | volume surge | 101 | +10.0 h | 57% | **filing** |
| `form.424B5` | breakdown | 32 | +8.7 h | 56% | filing |
| `8-K.1.01` (material agreement) | volume surge | 227 | −0.8 h | 42% | **volume** |
| volume surge | news attention | 58 | −12.0 h | 12% | **news** |

**The chain, as measured:**

```
SEC filing (t=0)  →  media pickup (+8 h)  →  volume surge (+23 h)  →  breakout (+22 h)
```

That is your hypothesis, confirmed. The filing is the origin; the crowd arrives
roughly a day later.

**One exception worth its own line.** `8-K.1.01` — material definitive
agreements, i.e. deals — is the one filing where volume arrives *before* the
filing (42% after, median −0.8 h). Deals leak. The 8-K is the confirmation, not
the news, and by the time it is filed the informed money has already traded.
That is the one place in this study where you genuinely are competing with
someone who knew first, and the right response is to not play that hand.

---

## 2. The magnitude — 89% of the move is after the opening bell

For events arriving **after the close** (most 8-Ks), the next session splits
cleanly into two legs at the opening auction:

- **gap** = `open(D+1) / close(D) − 1` — set overnight by whoever reads filings.
  **You cannot trade this.** It has happened by the time the auction prints.
- **intraday + tail** = `close(D+1)/open(D+1)` plus the next five sessions —
  everything after the news is already public and already in the open price.
  **You can trade all of this**, by buying the open.

Across all 23,056 events that moved the stock more than 3%:

| leg | median absolute move |
|---|---|
| overnight gap | **0.89%** |
| intraday + next five sessions | **6.76%** |
| **gap's share of the total move** | **11%** |

**Only about a tenth of the movement happens in the leg you cannot reach.**
The machines take a small first bite; the overwhelming majority of the price
action happens afterwards, in regular sessions, among people reacting to news
that is already public.

Your intuition was right, and it is larger than you guessed — the split is
closer to 1:9 than 5:15.

---

## 3. The catch: the size is there, the direction is not

Movement is not edge. A stock that moves 7% after a filing is only useful if
you know the sign.

Median capturable return by event kind, with the sign test that matters:

| kind | n | median capturable | % positive | Wilcoxon p | survives FDR |
|---|---|---|---|---|---|
| `form.424B5` (shelf takedown) | 174 | **−2.50%** | 39.1% | 0.011 | **yes** |
| `flow.breakdown` | 1,245 | **+0.62%** | 54.1% | 0.002 | **yes** |
| `flow.accumulation` | 2,642 | **+0.43%** | 52.5% | 0.001 | **yes** |
| `insider.sell` | 5,926 | **+0.32%** | 51.6% | 0.006 | **yes** |
| `insider.buy` | 340 | +0.21% | 51.5% | 0.064 | no |
| `8-K.2.02` (earnings) | 1,628 | +0.25% | 51.2% | 0.291 | no |
| `flow.volume_surge` | 4,862 | +0.06% | 50.3% | 0.762 | no |
| `8-K.1.01` | 570 | −0.57% | 46.8% | 0.270 | no |

**4 of 25 kinds survive**, and the percentages tell the story: 51–54% positive
is a coin flip with a thumb on it. The 89% of the move that is reachable is
mostly *noise you can now participate in*, not *return you can now collect*.

The one large, robust effect is **negative**: a shelf takedown (`424B5`) is
followed by a further −2.50% median, with only 39% of cases positive. Dilution
keeps hurting. That is a short, and shorting small caps carries borrow costs
that frequently exceed the edge — see `docs/RISK.md`.

---

## 4. Why the earlier insider result shrank

The last run reported `insider.buy` at **+1.90% capturable, t = 3.15**, which
survived FDR. On closer inspection it does not survive contact with outliers:

| sample | n | mean capturable | t |
|---|---|---|---|
| all | 340 | +1.90% | 3.15 |
| drop 5 largest by \|return\| | 335 | +0.92% | 2.19 |
| drop 10 largest | 330 | +0.55% | 1.55 |
| drop 20 largest | 320 | +0.14% | 0.42 |

Median +0.21%, win rate 51.5%. **Twenty events out of 340 carry the entire
effect.** A placebo test (five replicas with the dates shuffled within each
ticker) came back at −0.20% average, so the effect is not a methodological
artifact — but it is a *lottery-ticket* payoff, not a reliable one, and it
cannot be distinguished from noise once the tail is trimmed.

That shape is not automatically bad. It is precisely the "high variability, big
reward" profile you asked for. But trading it needs enough breadth and capital
to survive long stretches where the 6% of trades that pay have not shown up —
and 340 events over four years across 64 names is roughly 85 a year, which is
not enough breadth for that.

---

## 5. What this changes about how to trade

**Stop trying to trade the filing. Trade the session after it.** The pipeline's
original convention dated an after-hours filing to the *next* session and then
measured from the session after that — discarding the entire `day1_intraday`
leg, which is the single largest capturable component. If you act on overnight
filings, the entry is the **next open**, not the one after.

**Volume is a confirmation, not a signal.** It arrives ~23 hours after the
filing that caused it, 82% of the time. By then the filing is a day old. Its
use is as a *filter* on a filing you already saw, which is exactly what the
conditional test in `docs/FINDINGS.md` measured.

**Avoid `8-K.1.01`.** It is the one kind where volume leads the filing. That is
the signature of information leaking ahead of disclosure, and it is the one
place in this data where you are demonstrably last to know.

**The honest summary:** you were right that the crowd is slower than the
machines and that most of the move belongs to the crowd. You were right that
the filing comes first. What the data does not support — yet, at this sample
size — is that knowing the filing came first tells you which way the crowd will
push.

Reproduce with `scripts/cascade_study.py` (intraday) or
`iai.cascade.daily_cascade()` (daily OHLC, full window).

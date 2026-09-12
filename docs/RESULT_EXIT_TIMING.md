# Holding the straddle instead of selling it at the open

The proposal: do not dump the position at the opening print. Ride it for a day
or two and sell when the move has played out and the trend starts to fade.

The proposal is right that the opening print is a poor exit. It is wrong that
waiting fixes anything, and the reason is that the problem was never the exit.

## The ceiling: what perfect timing would be worth

Sell at the single best minute in the window. This is not a strategy — it needs
the peak to be known before it happens — and it exists only to bound the
argument. If perfect timing still loses, no exit rule can save the trade.

| | sell at the open | **perfect timing** | when the peak actually was |
|---|---|---|---|
| IBRX | −32.4% | **−1.4%** | 08-04 10:01 |
| WULF | −16.3% | **+1.9%** | 08-07 13:25 (third session) |
| JOBY | −15.4% | **+10.3%** | 08-06 09:32 (two minutes in) |
| RGTI | −24.0% | **−3.6%** | 08-10 09:34 (third session) |
| UAMY | +55.4% | **+120.3%** | 08-12 14:35 |
| **mean** | **−6.5%** | **+25.5%** | |

So there is real room above the open — and then the ceiling collapses under
inspection:

```
perfect timing, all five      mean +25.5%   median  +1.9%
perfect timing without UAMY   mean  +1.8%   median  +0.3%
```

**Four of the five barely break even even when sold at the exact peak.** The
entire ceiling is one trade. And the peaks land at 09:32, 10:01, 13:25 on day
three, 09:34 on day three, and 14:35 — there is no hour of the day and no
number of sessions that finds them.

## Every rule you could actually follow

| exit rule | n | mean | median | win | $40 → |
|---|---|---|---|---|---|
| sell at the open *(baseline)* | 5 | −6.5% | −16.3% | 20% | $22.62 |
| **trailing stop, give back 10%** | 5 | −5.0% | −18.9% | 20% | **$26.33** |
| trailing stop, give back 20% | 5 | −9.8% | −28.5% | 20% | $16.92 |
| trailing stop, give back 30% | 5 | −16.8% | −32.4% | 20% | $11.59 |
| sell at +25% | 5 | −7.1% | −16.7% | 20% | $17.78 |
| sell at +100% | 5 | +0.2% | −16.7% | 20% | $21.69 |
| hold to the end | 5 | −12.8% | −16.7% | 20% | $14.75 |
| *perfect timing (hindsight)* | 5 | *+25.5%* | *+1.9%* | *60%* | *$94.08* |

And fixed holds, which is the "wait 24 or 48 hours" version stated literally:

| held until | n | mean | median | $40 → |
|---|---|---|---|---|
| +1 hour | 5 | +0.9% | −21.8% | **$27.95** |
| +2 hours | 5 | −2.1% | −24.9% | $23.01 |
| +4 hours | 5 | −0.8% | −26.2% | $22.13 |
| first close | 5 | +1.1% | −30.7% | $22.62 |
| **second close (~48h)** | 5 | **−10.2%** | −21.7% | **$16.41** |
| third close | 4 | −11.8% | −14.8% | $17.70 |

**Longer is worse, monotonically after the first hour.** Not one implementable
rule turns a profit, and the best of them — a tight 10% trailing stop at $26.33
— still ends below the $40 it started with.

## Why the trailing stop fails at the thing it was designed for

"Sell when the trend fades" is exactly a trailing stop, and it is the rule that
degrades fastest as you loosen it: $26.33 at 10%, $16.92 at 20%, $11.59 at 30%.
The per-name detail shows why.

| | open | trail 20% | trail 30% | ceiling |
|---|---|---|---|---|
| WULF | −16.3% | **−34.4%** | −37.2% | +1.9% |
| RGTI | −24.0% | **−28.5%** | −34.8% | −3.6% |
| JOBY | −15.4% | −30.8% | −30.8% | +10.3% |

The straddle dips first, the stop fires near that dip, and the position then
recovers without you. You bought the instrument *because* it is volatile and
then set a rule that sells on volatility. The win rate tells the same story:
**20% for every implementable rule, 60% for perfect timing.** The rules cannot
even identify which trades are the winners.

## The path explains the whole thing

| | open | +1h | +2h | +4h | first close | second close |
|---|---|---|---|---|---|---|
| IBRX | — | −12.2% | −13.5% | −16.2% | −32.4% | −39.2% |
| WULF | −13.0% | −31.2% | −32.1% | −36.3% | −30.7% | −36.7% |
| JOBY | **+6.4%** | −21.8% | −32.1% | −32.1% | −41.0% | −16.7% |
| RGTI | — | −23.5% | −24.9% | −26.2% | −4.1% | −21.7% |
| UAMY | — | **+93.2%** | +91.9% | +106.8% | +113.5% | +63.5% |

For four of the five the value falls from the opening bell onward. **The gap is
fully priced into the first print**; after that you hold a decaying asset whose
implied volatility has already collapsed, and time only takes more away. Joby is
the clearest case: +6.4% in the first minutes, −41% by the close.

UAMY is the one that behaved the way the proposal expects — it kept running for
two more sessions. One out of five.

## What this actually says

The exit was never the problem. The straddles cost **11.3%** of spot and the
events delivered **6.2%** — an edge of **−5.1pp**. That is a pricing fact
established before a single exit decision is made, and no exit rule can overcome
paying more for a move than the move is worth. Exit timing moves variance
around; it does not move a negative expectation to a positive one.

Two things follow, and they point the same way:

1. **If you are buying, sell early.** Every measurement says the first hour is
   the best available moment (+0.9%, $27.95) and that everything after it is
   worse. The instinct to let a winner run is being punished by theta and by
   implied volatility collapsing the instant the news is out.
2. **The sign of the edge is the finding.** A −5.1pp edge for the buyer is a
   +5.1pp edge for the seller, and everything above — the decay from the open,
   the monotone worsening with time, the 20% win rate — is what being on the
   wrong side of that looks like from the inside.

## Limitations

* **Five trades.** This establishes the mechanism, not the magnitude.
* **No bid-ask.** Every exit rule here transacts at printed trades with no
  spread. A trailing stop that fires often pays that spread more often, so the
  real ranking is probably *worse* for the active rules than shown.
* Minute paths are forward-filled from the last trade in each leg, so a quiet
  contract's path is a step function and a stop can fire on a stale print.
* The +1 hour result rests on one large winner, the same way the ceiling does.

## Reproducing

```
POLYGON_API_KEY=... python3 scripts/options_exit.py --only-executable
```

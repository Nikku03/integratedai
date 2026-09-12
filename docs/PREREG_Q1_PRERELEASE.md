# Pre-registration: pre-positioned weekly options on scheduled earnings, Q1-2026

Committed **before any Q1-2026 price, filing or option data was fetched**. The
rule below is mechanical, so it cannot be steered by knowledge of outcomes — but
it is registered first anyway, because the value of the test is that the rule was
fixed in advance.

## Why this window

Every window examined so far in this session is contaminated for a directional
test: I have seen gap **signs** for roughly sixteen names in the Q2-2026 season
and the full outcomes of the 2026-08-17 → 09-04 8-K test. **Q1-2026 earnings
(filings 2026-04-20 → 2026-05-15)** have not been looked at here at all.

It is also the right window for the stated purpose: the point of weekly options
is a fast verification cycle, and a forward pick that resolves in October teaches
nothing today.

## The trade

Positioned **before** the release, which is the design chosen: the filing does
not exist when the trade goes on, so direction must be forecast rather than read.

* **Buy** one weekly option at the **close of the last session before the
  release was accepted**.
* **Sell** at the **open of the first session after**, capturing the gap.
* **Weeklies only** — nearest expiry strictly after the event, within 10 days.
* Screens unchanged: market cap $300M–$20B, trailing price-to-sales ≥ 8.0x,
  at least $20M/day of stock volume, all point-in-time.

## The forecasting rule

The only pre-release signals available to this system at scale are tape signals;
there is no point-in-time analyst-consensus feed here. So direction is forecast
from the run-up into the print, measured to the last bell before acceptance:

```
runup_z = (5-session return ending at the last pre-release close)
          / (vol20 * sqrt(5/252))
```

Four arms, all declared now:

| arm | rule |
|---|---|
| **MOMENTUM** | call if `runup_z > +0.5`, put if `< −0.5`, else no trade |
| **REVERSAL** | put if `runup_z > +0.5`, call if `< −0.5`, else no trade |
| **ALWAYS PUT** | put on every screened event |
| **ALWAYS CALL** | call on every screened event |

**Momentum and reversal are mirrors.** On the names where both trade, one's
accuracy is exactly one minus the other's, so **one of them is guaranteed to look
good**. That is not evidence. Only a deviation from 50% large enough to survive a
confidence interval means anything, and with the sample this window is likely to
yield, that bar will probably not be cleared. Registering both, and saying this
now, is what stops the winner being presented as a discovery.

`ALWAYS PUT` is included because it is the one asymmetry with repeated support:
puts beat calls by 54.7pp in the blind 8-K window, and judged-negative filings
have outperformed judged-positive ones in five consecutive windows.

## Hypotheses

**H1 (primary).** Neither tape arm reaches **55.3%** direction accuracy — the
break-even measured over 30 real weekly purchases, where a correct call returned
+48.8% and a wrong one −48.9%. Registered expectation: **both land near 50% and
both lose.**

**H2.** `ALWAYS PUT` beats `ALWAYS CALL`.

**H3.** Every arm loses money even if its accuracy is near 50%, because at a
realistically marked premium the break-even accuracy is about **69%**, not 50%.
This follows from the arithmetic rather than from any forecast: an at-the-money
straddle is priced near the expected move, one leg costs about half of it, and
the market was measured charging 13.7% for a move that delivered 9.9% across
2,842 releases.

**H4.** The strategy will be capacity-limited by weekly chains, as it has been
every time: in the Q2 season only 21 of 73 screened names had a weekly contract.

## What would count as a result

Direction accuracy with a confidence interval that excludes 50%, on a sample
large enough to mean it. Anything short of that is the null being confirmed
again, which is the registered expectation.

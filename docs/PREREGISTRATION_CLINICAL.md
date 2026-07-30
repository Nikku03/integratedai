# Pre-registration: the clinical-readout rule

Committed **before** the out-of-sample result exists. The July numbers that
motivated this are stated below so the comparison is fixed in advance and cannot
be re-described afterwards.

## Why this needs pre-registering

The July result — positive clinical readouts, trailing exit, **mean +9.86% over
11 trades, bootstrap 95% CI [+1.34%, +19.07%]** — has one disqualifying weakness:
**the sentiment patterns were written after seeing which July names won.** The
vocabulary is generic clinical-trial language and the mechanism was predictable in
advance, but that is an argument, not evidence. So the rule is frozen here and
run on the twelve months before it.

## The frozen rule

**Universe.** Filers whose SEC-reported SIC is pharma/biotech/medical
(2833, 2834, 2835, 2836, 8731, 8071, 3826, 3841, 3845, 8000, 8090).

**Signal.** An 8-K whose text (primary document plus up to two EX-99 exhibits,
first 24,000 characters) matches the CLINICAL_RESULT pattern in
`catalyst_extract.py`, **and** matches no toxic-financing pattern, **and** whose
sentiment is POSITIVE — matching the "worked" vocabulary and not the "failed"
vocabulary, both frozen in `oos_clinical.py`.

**Entry.** The open of the next session after EDGAR acceptance.

**Exit.** Arm at **+8%**. Before arming, stop at **−15%**. Once armed, trail
**8%** below the running high-water mark; also exit if no new high for **8
sessions**. Hard stop after 25 sessions.

**Sizing.** $80, two slots, position = equity/slots, compounded, chronological.

Nothing above is re-fitted on the test period.

## What counts as success

The July estimate is +9.86% per trade. The relevant null is zero, not +9.86%.

| criterion | threshold |
|---|---|
| **PRIMARY** | mean return per trade > 0 with a bootstrap 95% CI excluding zero |
| supporting | median > 0 |
| supporting | positive in a majority of calendar quarters |
| supporting | POSITIVE cohort beats the SILENT/NEGATIVE cohorts |
| sanity | at least 40 trades, else the test is underpowered and reports as such |

**A mean between 0 and +9.86% still counts as a pass on the primary criterion.**
Shrinkage from an in-sample estimate is expected; sign is what is being tested.

## What would falsify it

- Mean ≤ 0, or a CI spanning zero.
- POSITIVE indistinguishable from SILENT — that would mean the sentiment filter,
  the part most at risk of having been fitted, does nothing.
- The result resting on one or two names: reported by re-running with the largest
  contributors dropped.

## Known weaknesses of the test itself

**Daily bars.** Yahoo caps 1-minute history near 30 days, so twelve months must
run daily. The trail is evaluated on daily highs and lows, which is **coarser and
slightly optimistic** — an intraday spike through the trail that recovers by the
close is invisible here and would have exited in the July minute-bar run.

**Survivorship.** The ticker list is a current snapshot. Biotechs that failed a
trial and delisted are absent, and they are precisely the left tail of this
strategy. **The out-of-sample result is therefore an upper bound**, and a pass
here is necessary rather than sufficient.

**No transaction costs are charged.** At $40 a side on names of this liquidity,
the round trip is on the order of 60–120bp and should be subtracted mentally from
any per-trade figure.

# Pre-registration: directional weekly options on 8-K events, 15 sessions

Committed **before any option price was fetched for a judged name** and before
any outcome was computed. The judgements in `data/window_w5_labels.json` were
made from filing text alone by readers explicitly forbidden from touching price,
volume or outcome data of any kind. The git timestamp is the evidence.

## Window and why it is this window

**Filings 2026-08-17 → 2026-09-04**, fifteen trading sessions, entries
2026-08-18 → 2026-09-08.

The obvious choice — the fifteen sessions ending today — is **contaminated**. In
earlier work in this session I printed per-name outcomes for early September
(the 63-name shortlist's forward moves, the ten largest movers, and six traded
names) and for the Q2 earnings sample through 2026-08-21. Re-using those dates
with fresh judgements would not be a blind test. This window is the most recent
fifteen sessions whose per-name outcomes I have not seen.

One name is excluded by hand: **IVF**, whose +132.6% gap on 2026-08-17 appeared
in a table of worst gaps earlier today. `CAPR` appears on 2026-08-24; its
2026-08-13 earnings gap was printed earlier but that is a different filing and a
different date, and it is kept with this note attached.

## What is traded

* **Long options only** — a call where the filing is judged positive, a put where
  it is judged negative. No straddles, no short premium.
* **Weeklies only** — the nearest expiration strictly after the event must be
  within 10 days. On a monthly-only name that expiry can be five weeks out,
  roughly tripling the premium for the same overnight move.
* At the money: the strike nearest the entry session's opening price.
* Judged **0** means no trade. 36 of 81 events are judged 0.

## The screens, all point-in-time

```
2,756  8-K filings over the fifteen sessions        (1,997 filers)
  794  ticker trading at least $20M/day
  746  held across a bell (an intraday filing cannot be positioned for)
  422  market cap $300M-$20B
  136  trailing price-to-sales >= 8.0x
   81  both   -> 61 names, 15 sessions
```

Share counts are those filed before the event; the price is the close of the last
session that closed before acceptance; revenue is what had been filed by then.
Fundamentals coverage is **100% of the 546 screened filers**.

## Has the market already moved on it?

Measured to the last bell before acceptance, never to the day EDGAR disseminated
the filing. `already_priced` is set when the stock moved more than one standard
deviation over five sessions, **or** more than one and a half over the single
session before, with no 8-K in the preceding fortnight to explain it.

**20 of 81 events are flagged**, the sharpest being Arcturus at **+76.2% over
five sessions (4.5 standard deviations)** with nineteen days of silence behind
it, and Twist at **+22.6% in one session (3.3 standard deviations)**.

The one-session test was added after inspecting pre-filing data alone: the
five-session window diluted Twist's move to +13.7% and 0.9 standard deviations,
below any sensible threshold. No outcome data was used in that refinement.

## What the readers found

| direction | n | | | |
|---|---|---|---|---|
| −2 | 2 | | is_news true | 45 |
| −1 | 12 | | is_news false | 36 |
| 0 | **36** | | transformative | 6 |
| +1 | 28 | | significant | 33 |
| +2 | 3 | | routine | 42 |

Most common event types: officer-change 12, governance 9, clinical-data 9,
financing 7, m&a 5, earnings 5, fda-decision 4.

That 36 of 81 filings carry no directional information, and 42 of 81 are routine,
is itself a finding about what an 8-K usually is.

## Hypotheses

**H1 (primary).** The judged direction predicts the option's return. Measured as
the mean return of the traded contract across all non-zero judgements. The four
prior windows of this work gave judge −2 a mean of −11.33% at an 18.2% win rate
on the underlying, and judge +1 −4.50% — so the registered expectation is that
**the negative calls work and the positive calls do not**.

**H2.** Events flagged `already_priced` underperform those not flagged. This is
the rule as stated: if the price moved before the disclosure with nothing to
explain it, the information is already out. Tested earlier as a hard veto on
160,920 rows it was worth −0.06pp with an interval spanning zero, so the
registered expectation is **no effect**, and the flag is measured rather than
trusted.

**H3.** `is_news = false` events — filings that merely furnish a press release
about an already-disclosed matter — produce smaller absolute moves than
`is_news = true` ones. This is the cleanest test of whether the reading layer
adds anything beyond the item code.

**H4.** The option loses even where the direction is right. Every measurement in
this work so far says an at-the-money weekly is nearly all extrinsic value and a
resolved event destroys it whichever way it resolves: one name's stock rose 24%
and its call rose 12%; another fell 7.5% and its call fell 80%.

## Exits, declared in advance

Primary: **the close of the entry session.** Reported alongside, as sensitivity
and not as the headline: the opening print, one hour in, and the following close.
The primary is named here so it cannot be chosen afterwards.

## What this cannot establish

Forty-five directional trades before the weekly-options and liquidity filters,
and far fewer after. No bid-ask is modelled — the key serves aggregates but 403s
on NBBO — so every figure is an upper bound.

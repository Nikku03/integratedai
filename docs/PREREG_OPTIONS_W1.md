# Pre-registration: options on catalyst filings, 2026-09-08 → 2026-09-10

Committed **before** any return, option price or outcome was computed. The
judgements in `data/options_w1_labels.json` were written from the filings alone;
the git timestamp on this commit is the evidence for that claim.

## The design, as specified

Take a session. Enumerate the 8-K filings that landed on it. Keep the names in
the **$300M–$20B** market-cap band, sweet spot $2B–$15B, whose **pre-filing
price-to-sales is at least 8.0x**. Rank what survives, trade the best one, and
carry the second as a diversification check. Instrument: listed options, priced
from Polygon. Window: Tuesday to Thursday of this week.

## What the screen produced

673 8-K filings over the three sessions, 621 issuers. 560 carry a ticker with a
Polygon bar. 264 land in the cap band; 127 clear 8.0x price-to-sales; **63
name-days clear both** — 29 on Tuesday, 14 on Wednesday, 20 on Thursday.

Both screens are point-in-time: the share count is the one filed *before* the
8-K existed, the price is the close of the last session *before* the filing day,
and trailing revenue is what had been filed by then.

## Hypotheses

**H1 (primary).** The name this rule ranks first outperforms the second-ranked
name over the hold. This is the claim the design actually makes and it is the
one with the least evidence behind it, because k=1 against k=2 on three
observations is noise by construction. Registered so the answer cannot be
chosen afterwards.

**H2.** The judged **−2** filings lose money on the underlying. Across four
earlier windows judge −2 returned **−11.33% at an 18.2% win rate**, the most
durable shape in this repository. Two names are judged −2 here: GOSS (a 1-for-80
reverse split) and BHVN (an FDA partial clinical hold). GOSS trades $1.2M a day
and will fail the liquidity gate, so BHVN carries this test alone.

**H3.** The judged **+2** filings do *not* reliably make money. Judge +1
returned −4.50% and judge +2 −2.28% across those same windows. Nine names here
are judged +2. If H3 holds, a book that buys calls on good news underperforms
one that buys puts on bad news, despite good news being six times more common
in this sample.

**H4 (the instrument).** A long straddle beats the directional bet. The
repository's clearest measurement is that this gate concentrates **dispersion**
and predicts **direction** poorly: realised volatility sorts |return| by 4.94x
and mean return not at all. A long straddle monetises exactly that, and the
directional bet is the arm the evidence supports least. H4 is registered as the
honest expectation even though the directional book is the requested deliverable.

## The selection rule, fixed in advance

```
score = |judge| × (1.5 if judge < 0 else 1.0)      only negative readings have held up
        × (1.0 if flat_and_quiet else 0.6)         +0.36pp, CI [+0.19,+0.53], P=0.000
        × (0.5 if already_out else 1.0)            the run-up rule, as a down-weight
        × clip(vol20 / median(vol20), 0.5, 2.0)    dispersion is the point of an option
        × (1.0 if pre_filing_dollar_volume ≥ $25M else 0.0)
```

`already_out` is the rule proposed earlier in this work — the price jumped
before the disclosure and nothing was announced, so the information is already
out. It is a **down-weight, not a veto**, because tested as a veto on 160,920
rows it was worth −0.06pp with an interval spanning zero.

`vol20` enters with a **positive** sign, reversing its role in the equity book,
where dropping the top volatility quintile was what cut the compounding drag
from −1.77% to −0.75%. A long option position wants the dispersion the equity
book had to avoid.

## What this test cannot establish

Three sessions, two names each: **six trades, and Thursday's pair can only be
held intraday** because Friday's session had not opened when this was built.
The earlier work measured the standard error of a *fifteen*-trade window mean at
4–8pp, and found that a single trade accounts for a large share of window-to-
window spread. Six trades resolve nothing. The registration exists so the result
is reported rather than selected.

## Known limitation in the data

The Polygon key available here serves option **aggregates** (open, high, low,
close, volume, VWAP per contract) but returns 403 on the **NBBO quote** feed.
Every fill in this backtest is therefore struck at a price someone actually
traded, with **no bid-ask spread modelled**. On single-name options that spread
is routinely 2–10% of premium and occasionally far more, so the reported P&L is
an upper bound on what the same decisions would have earned. This is stated
here, before the numbers, rather than as a footnote afterwards.

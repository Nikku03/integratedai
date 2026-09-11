# Options on catalyst filings, 2026-09-08 → 2026-09-10

Pre-registered in `PREREG_OPTIONS_W1.md`, committed at `90394ab` before any
outcome was computed. Judgements in `data/options_w1_labels.json`, written from
the filings alone.

**The headline is not the P&L. It is that four of the six names the screen
selected had no option market to trade.**

## The screen worked. The instrument did not exist.

| | Tue 09-08 | Wed 09-09 | Thu 09-10 |
|---|---|---|---|
| 8-K filings | 262 | 198 | 213 |
| with a ticker and a price | 214 | 167 | 179 |
| in the $300M–$20B band | | | **264 over three days** |
| at price-to-sales ≥ 8.0x | | | **127** |
| **clearing both** | **29** | **14** | **20** |

The two screens select hard for one thing: small and mid-cap issuers valued on a
story rather than on sales. Twenty of the 63 survivors are clinical-stage
pharmaceutical companies. That is exactly what was asked for, and it is also a
near-perfect description of the set of US equities whose listed options do not
trade.

| pick | rank | contracts traded in the strike, all session | tradeable? |
|---|---|---|---|
| **RGTI** | 1st, Tue | **3,784** | yes |
| **QBTS** | 2nd, Tue | **481** | yes |
| TYRA | 1st, Wed | 9 — and the only print after 09:35 was at **15:59** | no |
| HYMC | 2nd, Wed | 39 | no |
| BHVN | 1st, Thu | 20 | no |
| IRON | 2nd, Thu | **0 — the contract never traded** | no |

One contract is 100 shares. Disc Medicine traded 480,869 shares of stock on
09-10 and not one at-the-money option. Tyra's $20 call printed nine contracts
across an entire session in which the stock moved 24%.

## What the two real trades did

| | judge | side | entry | exit | option | stock |
|---|---|---|---|---|---|---|
| RGTI | +2 | call $16.5 | 1.20 | 0.24 | **−80.0%** | −7.5% |
| QBTS | +2 | call $17.5 | 1.47 | 0.41 | **−72.1%** | −5.9% |

Both were the same trade: a $100M CHIPS Act award to a quantum computing company
with almost no revenue, announced the same morning. The rule ranked on
conviction and never checked correlation, so the "diversification" pick was the
identical event in the identical sector.

## Every arm, $40 compounded trade by trade

| arm | n | mean | median | win | compounds | $40 → |
|---|---|---|---|---|---|---|
| directional, as designed | 5 | −29.5% | −13.6% | 40% | −43.5% | **$2.29** |
| best only | 3 | −20.6% | +6.2% | 67% | −38.0% | $9.52 |
| second only | 2 | −42.9% | −42.9% | 0% | −50.9% | $9.64 |
| **executable only** | **2** | **−76.1%** | −76.1% | 0% | −76.4% | **$2.23** |
| straddle | 5 | −15.8% | −13.7% | 0% | −16.2% | $16.56 |
| always the call | 5 | −38.7% | −40.0% | 20% | −49.6% | $1.29 |
| **always the put** | 5 | **+20.2%** | +6.2% | 60% | −7.3% | **$27.35** |
| *the underlying stock* | 6 | +0.4% | −3.9% | 17% | −0.1% | $39.65 |

Buying the stock and doing nothing kept $39.65 of $40. Every option arm lost,
and the arm that was actually executable lost three quarters of the stake in
two trades.

## Against the pre-registration

**H1 — nominally PASS, and worthless.** Best −20.6% against second −42.9%. That
is three observations against three. Registered so it would be reported rather
than chosen.

**H2 — the veto held for the fifth straight window.** One name was judged −2 and
liquid enough to read: Biohaven, disclosing an FDA partial clinical hold on its
lead epilepsy program. It gapped **−9.8%** and fell a further **−5.4%**, and its
put was the only directional position that made money. The prior four windows
gave judge −2 a mean of −11.33% at an 18.2% win rate; this one gave −14.7%
end to end.

**H3 — confirmed, and it is the finding with real evidence behind it.** Five
names were judged positive. Their stocks averaged **+1.5%** and their calls
averaged **−38.4%**. Reading a filing as good news and buying it has now failed
in five consecutive windows.

**H4 — PASS.** The straddle lost 15.8% against the directional book's 29.5%,
consistent with the repository's standing result that this gate concentrates
dispersion and predicts direction badly. Losing less is not the same as winning.

## Where the reaction actually happened

| | judge | prev close | entry open | the gap | the hold | both |
|---|---|---|---|---|---|---|
| RGTI | +2 | 15.20 | 16.39 | **+7.8%** | −7.5% | −0.3% |
| QBTS | +2 | 16.58 | 17.70 | **+6.8%** | −5.9% | +0.5% |
| TYRA | +2 | 26.73 | 18.94 | **−29.1%** | +24.3% | −11.9% |
| HYMC | +2 | 22.81 | 21.58 | −5.4% | −0.9% | −6.2% |
| BHVN | −2 | 15.00 | 13.53 | **−9.8%** | −5.4% | −14.7% |
| IRON | +2 | 76.51 | 75.89 | −0.8% | −2.3% | −3.1% |

**The information is entirely in the gap, and a position opened at the bell
cannot reach it.** Both CHIPS awards gapped up around 7% and then handed the
whole move back inside two sessions — so the filings were read correctly, the
reaction was correct, and the trade still lost because it started after the
reaction was over.

Tyra is the sharpest case. The filing announced positive Phase 2 proof of
concept and a selected dose; the stock opened **29% lower**. Judging a filing on
its contents says what the document contains, not what the market already
expected of it.

## Why the options lost so much more than the stocks

| | stock | right direction? | option | gap |
|---|---|---|---|---|
| RGTI | −7.5% | no | −80.0% | −72.5pp |
| QBTS | −5.9% | no | −72.1% | −66.2pp |
| TYRA | +24.3% | yes | +12.0% | −12.3pp |
| BHVN | −5.4% | yes | +6.2% | +0.8pp |

An eight-day at-the-money call on a 70%-volatility name is almost entirely
extrinsic value, and a resolved binary event destroys extrinsic value whichever
way it resolves. RGTI's stock fell 7.5% and its call fell 80%. Tyra's stock rose
24.3% and its call rose 12%. **Both directions cost money**, because implied
volatility collapses once the filing is out — which is the mechanical reason a
long-premium catalyst strategy is harder than the stock version, not easier.

## Limitations, stated plainly

* **Six trades, two of them real.** Nothing here is statistically established.
  The earlier work measured the standard error of a *fifteen*-trade window mean
  at 4–8pp.
* **No bid-ask.** The key serves option aggregates but 403s on NBBO, so every
  fill is a printed trade with **no spread modelled**. On contracts printing 9
  to 39 times a session the true spread is enormous. Every figure above is an
  upper bound, and the thin names are upper bounds on fiction.
* **Thursday's pair could only be held intraday** — Friday's session had not
  opened.
* **Tuesday's two picks were one trade.** The rule has no correlation control.

## What this says about the design

The screen did what it was asked to do. The failure is downstream of it:

1. **Add an option-liquidity gate to the selection, not to the report.** Require
   the at-the-money strike to have traded, say, 250 contracts on a recent
   session, before a name is eligible. Applied here it would have left two
   candidates in three days, which is itself the answer — this screen and listed
   options do not overlap much.
2. **The gap is the trade.** A position opened at the next bell systematically
   misses the reaction and then eats the fade. Either trade the pre-market or
   accept that the edge, if any, is in the drift and size accordingly.
3. **Long premium fights volatility crush.** The only arms that did not lose
   badly were the put book and the straddle. If the reading layer has any
   value it is the negative judgements — now 5 for 5 — and the cleanest way to
   express those is the underlying or a put, not a call on good news.

## Reproducing

```
python3 scripts/options_screen.py          # 673 filings -> 63 name-days
python3 scripts/options_features.py        # pre-filing tape context, scoring
POLYGON_API_KEY=... python3 scripts/options_backtest.py
python3 scripts/options_report.py
```

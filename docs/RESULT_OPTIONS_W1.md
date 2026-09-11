# Options on catalyst filings, 2026-09-08 → 2026-09-10

Pre-registered in `PREREG_OPTIONS_W1.md`, committed at `90394ab` before any
outcome was computed. Judgements in `data/options_w1_labels.json`, written from
the filings alone.

Run twice. The first run selected on conviction alone and discovered afterwards
that four of its six names had no tradeable option. The second adds an
**option-liquidity gate to the selection**, measured before the filing exists.
Both runs are reported, because the difference between them is the finding.

---

## 1. The screen works. The option market is the binding constraint.

| | Tue 09-08 | Wed 09-09 | Thu 09-10 |
|---|---|---|---|
| 8-K filings | 262 | 198 | 213 |
| with a ticker and a price | 214 | 167 | 179 |
| **clearing $300M–$20B and P/S ≥ 8.0x** | **29** | **14** | **20** |
| the reading gives a view on, and liquid enough in the stock | 7 | 3 | 5 |
| **and has an option market before the filing** | **4** | **1** | **2** |

The two screens select hard for small and mid-cap issuers valued on a story
rather than on sales — 20 of the 63 survivors are clinical-stage pharmaceutical
companies. That is exactly what was asked for, and it is also close to a
definition of the set of US equities whose listed options do not trade.

**Only Tuesday produced two names to choose between.** Wednesday produced one.
Thursday produced two, but the higher-ranked one filed at 16:36 — after the last
session in the window — so it could not be held at all. That is the direct
answer to "best and second best each day": on two days of three, a second
tradeable name did not exist.

### The gate, measured before the filing

Five sessions ending on the last close **before** the filing was accepted,
on the at-the-money strike, on the side the reading would trade. Using
filing-day volume instead would admit precisely the chains that only wake up
for an event.

| | | pre-filing contracts | sessions traded | |
|---|---|---|---|---|
| Tue | BMNR | 13,977 | 5/5 | eligible |
| Tue | NTLA | 1,203 | 5/5 | eligible |
| Tue | QBTS | 755 | 5/5 | eligible |
| Tue | RGTI | 716 | 5/5 | eligible |
| Tue | SYRE | 10 | 3/5 | no market |
| Tue | DFTX | 6 | 1/5 | no market |
| Tue | MIRM | 0 | 0/5 | no market |
| Wed | TYRA | 2,390 | 5/5 | eligible |
| Wed | HYMC | 151 | 5/5 | no market |
| Wed | EPRT | 3 | 1/5 | no market |
| Thu | CORZ | 5,764 | 5/5 | eligible |
| Thu | QBTS | 1,351 | 5/5 | eligible |
| Thu | BHVN | 34 | 2/5 | no market |
| Thu | WPC | 24 | 5/5 | no market |
| Thu | IRON | 0 | 0/5 | no market |

**7 of 15.** The gate costs something real: it removes Biohaven, whose FDA
partial clinical hold was the only filing in the window that the reading called
correctly *and* that made money. More on that below.

---

## 2. The gated book

| date | tkr | rank | judge | side | entry | exit | **option** | stock | contracts | in | out | usable? |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 09-08 | RGTI | 1 | +2 | call 16.5 | 1.20 | 0.24 | **−80.0%** | −7.5% | 3,784 | 09:35 | 15:54 | **yes** |
| 09-08 | QBTS | 2 | +2 | call 17.5 | 1.47 | 0.41 | **−72.1%** | −5.9% | 481 | 09:35 | 15:57 | **yes** |
| 09-09 | TYRA | 1 | +2 | call 20.0 | 2.50 | 2.80 | +12.0% | +24.3% | 9 | 15:59 | 10:20 | no |
| 09-10 | CORZ | 1 | +1 | call 17.5 | 0.66 | 0.86 | +30.3% | −1.4% | 2,643 | 09:51 | 12:45 | no |

Two of the four survive contact with the tape, and **the gate is not why**. Both
failures are new, and both are about marks rather than volume:

**Tyra passed the gate and still could not be traded.** The gate cleared it on
the $25 strike, which had printed 2,390 contracts. The stock then gapped 29%
lower, moving the money to the $20 strike — which printed **nine contracts all
session**, the only one after 09:35 being at 15:59.

| | gate strike | pre-filing vol | traded strike | entry-day vol |
|---|---|---|---|---|
| RGTI | 15 | 716 | 16.5 | 3,784 |
| QBTS | 16.5 | 755 | 17.5 | 481 |
| **TYRA** | **25** | **2,390** | **20** | **9** |
| CORZ | 18 | 5,764 | 17.5 | 2,643 |

A gap relocates at-the-money, and the liquidity does not necessarily follow it.
Gating on a pre-filing strike cannot see that coming.

**Core Scientific's exit mark was three hours stale.** Its call traded 2,643
contracts, comfortably clearing the gate — but its last print before the bell
was a single contract at **12:45**, with the stock near its session high.
Carrying that forward as a 16:00 close credited the position +30.3% on a day the
stock fell 1.4%. The exit is now taken from minute bars and its timestamp
recorded, so a stale mark is excluded rather than believed. Without that fix
this document would have reported a winning trade that did not exist.

---

## 3. Every arm, $40 compounded trade by trade

| arm | n | mean | median | win | compounds | $40 → |
|---|---|---|---|---|---|---|
| directional, as designed | 4 | −27.5% | −30.1% | 50% | −46.6% | $3.26 |
| best only | 3 | −12.6% | +12.0% | 67% | −33.7% | $11.68 |
| second only | 1 | −72.1% | — | 0% | −72.1% | $11.16 |
| **executable only** | **2** | **−76.1%** | −76.1% | 0% | −76.4% | **$2.23** |
| straddle | 4 | −12.3% | −18.7% | 25% | −13.5% | $22.35 |
| always the put | 4 | +23.4% | +39.3% | 50% | −10.7% | $25.39 |
| *the underlying stock* | 4 | **+2.4%** | −3.6% | 25% | +1.6% | **$42.70** |

Holding the four stocks turned $40 into $42.70. Every option arm lost, and the
two trades that could genuinely have been taken lost three quarters of the
stake between them.

Adding the gate moved the headline from $2.29 to $3.26 and left the executable
arm almost exactly where it was — **$2.23 before, $2.23 after**. The gate makes
the test honest; it does not make the strategy work.

---

## 4. Against the pre-registration

**H1 — nominally PASS, still worthless.** Best −12.6% against second −72.1%,
on three observations against one.

**H2 — no observations, and that is the gate's doing.** The one name judged −2
with a real filing behind it was Biohaven's FDA partial clinical hold. Ungated
it gapped **−9.8%**, fell a further **−5.4%**, and its put was the only
directional position in the whole exercise that made money. Its option printed
34 contracts over two of five pre-filing sessions, so the gate is right to
exclude it — you could not have got that trade on. **The most informative
signal in the test is the one the market gives you no way to express.**

**H3 — confirmed again.** Four names judged positive: stocks **+2.4%**, calls
**−27.5%**. Reading a filing as good news and buying it has now failed in five
consecutive windows.

**H4 — PASS.** Straddle −12.3% against the directional book's −27.5%,
consistent with the standing result that this gate concentrates dispersion and
predicts direction badly. Losing less is not winning.

---

## 5. Where the reaction actually happened

| | judge | prev close | entry open | the gap | the hold | both |
|---|---|---|---|---|---|---|
| RGTI | +2 | 15.20 | 16.39 | **+7.8%** | −7.5% | −0.3% |
| QBTS | +2 | 16.58 | 17.70 | **+6.8%** | −5.9% | +0.5% |
| TYRA | +2 | 26.73 | 18.94 | **−29.1%** | +24.3% | −11.9% |
| CORZ | +1 | 18.09 | 17.61 | −2.6% | −1.4% | −4.0% |

**The information is entirely in the gap, and a position opened at the bell
cannot reach it.** Both CHIPS awards gapped up around 7% and handed the whole
move back within two sessions: the filings were read correctly, the market
reacted correctly, and the trade still lost because it began after the reaction
was over.

Tyra is the sharpest case in the set. The filing announced positive Phase 2
proof of concept and a selected dose. The stock opened **29% lower**. Judging a
filing on its contents tells you what the document says, not what the market
already expected it to say.

## 6. Why the options lost more than the stocks

| | stock | right direction? | option |
|---|---|---|---|
| RGTI | −7.5% | no | −80.0% |
| QBTS | −5.9% | no | −72.1% |
| TYRA | +24.3% | yes | +12.0% |

An eight-day at-the-money call on a 70%-volatility name is almost all extrinsic
value, and a resolved binary destroys extrinsic value whichever way it resolves.
Rigetti's stock fell 7.5% and its call fell 80%; Tyra's stock rose 24% and its
call rose 12%. **Both directions cost money**, which is the mechanical reason a
long-premium catalyst strategy is harder than the equity version, not easier.

## 7. Limitations

* **Four trades, two of them real.** Nothing here is statistically established.
  The earlier work put the standard error of a *fifteen*-trade window mean at
  4–8pp.
* **No bid-ask.** The key serves option aggregates but returns 403 on NBBO, so
  every fill is a printed trade with **no spread modelled**. Both executable
  trades lost ~75%; a spread would make that worse, not better.
* **The gate watches one strike.** A wider probe would be better and costs more
  requests than a five-per-minute key allows.
* **Thursday's best pick was unhedgeable** — filed at 16:36, after the last
  session in the window.
* **Tuesday's two picks were one trade**: the same CHIPS Act program, the same
  sector, the same morning. The rule still has no correlation control.

## 8. What to change next

1. **Gate on the traded strike, not a pre-filing one.** The pre-filing gate is
   point-in-time and correct, and Tyra shows it is not sufficient. A workable
   version requires several strikes around the money to be active, so a gap has
   somewhere liquid to land.
2. **Require a print near both ends of the hold.** Already implemented for
   reporting; it should be a selection filter, since an un-markable exit is an
   un-closable position.
3. **The gap is the trade.** Opening at the next bell systematically misses the
   reaction and then eats the fade. Either trade pre-market or accept that the
   edge, if any, lives in the drift.
4. **Stop buying calls on good news.** Five windows, five failures. The
   repository's only durable reading signal is the negative one — and where it
   fires, listed options frequently do not exist, so the underlying is the
   instrument.

## Reproducing

```
python3 scripts/options_screen.py                          # 673 filings -> 63 name-days
python3 scripts/options_features.py --no-gate              # candidate list
POLYGON_API_KEY=... python3 scripts/options_liquidity.py   # point-in-time option volume
python3 scripts/options_features.py                        # gated selection, best + second
POLYGON_API_KEY=... python3 scripts/options_backtest.py
python3 scripts/options_report.py
```

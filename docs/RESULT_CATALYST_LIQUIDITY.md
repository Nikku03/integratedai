# At catalyst + 1 minute: liquidity and price, by catalyst type

Event-first this time. Every catalyst of every type, standing at its own timestamp
plus one minute, recording the two things that decide whether it is tradable.

**7,563 catalyst events across 1,536 names, 1–29 July 2026.** SEC forms only,
because they carry `acceptanceDateTime` to the second. FDA, ClinicalTrials.gov and
DoD publish **date only** — there is no minute to add one to, so a T+1min figure
for them would be fabricated. They are excluded here rather than faked.

## 1. Liquidity — does that minute even trade?

| catalyst type | n | **printed at +1min** | $ that minute | $ next 5 min | $ next 60 min |
|---|---|---|---|---|---|
| | | | *median, when it printed* | | |
| insider Form 4 | 3,098 | 25% | $52,664 | $290,777 | $3.82m |
| **offering / dilution** | 1,119 | **43%** | **$2,036,416** | $11.22m | $161.4m |
| **8-K earnings** | 607 | **11%** | $73,976 | $311,125 | $4.03m |
| passive 13G | 402 | 41% | $38,693 | $260,263 | $3.66m |
| 8-K officer change | 367 | 12% | $22,027 | $111,303 | $1.29m |
| 8-K material agreement | 356 | **11%** | $17,629 | $52,292 | $583,891 |
| 8-K other event | 356 | 19% | $17,754 | $98,220 | $1.12m |
| 8-K reg-FD | 301 | 18% | $22,702 | $109,540 | $1.83m |
| periodic 10-Q/K | 262 | 23% | $200,767 | $1.67m | $24.2m |
| proxy / other | 257 | 15% | $9,086 | $55,027 | $871,970 |
| merger / tender | 147 | 14% | $16,490 | $163,352 | $2.92m |
| activist 13D | 97 | 21% | $21,510 | $62,026 | $1.09m |
| 8-K vote results | 77 | 16% | $8,499 | $46,145 | $428,995 |
| 8-K delisting | 50 | 14% | $1,960 | $30,848 | $157,809 |
| 8-K dilution | 26 | 15% | $853 | $8,981 | $102,539 |
| **ALL** | **7,563** | **24%** | **$90,634** | **$534,025** | **$7.58m** |

**Three quarters of catalysts have no trade at all in the minute after they
publish.** That is the binding constraint, and it is worst exactly where the
information is richest: 8-K earnings prints only 11% of the time, material
agreements 11%, officer changes 12%.

The one type that reliably trades is **offering/dilution at 43%** — because 424B
and S-3 filings go out during market hours, when the underwriter is working.

## 2. Order size that minute supports (10% participation)

Conditional on the minute printing at all:

| catalyst type | n printed | median $/min | 10% of it | supports $80 | supports $5,000 |
|---|---|---|---|---|---|
| offering / dilution | 480 | $2,036,416 | $203,642 | **99%** | **96%** |
| periodic 10-Q/K | 59 | $200,767 | $20,077 | 95% | 71% |
| 8-K earnings | 69 | $73,976 | $7,398 | **99%** | 57% |
| insider Form 4 | 761 | $52,664 | $5,266 | 95% | 52% |
| passive 13G | 166 | $38,693 | $3,869 | 96% | 45% |
| 8-K reg-FD | 54 | $22,702 | $2,270 | 98% | 33% |
| 8-K officer change | 44 | $22,027 | $2,203 | 93% | 39% |
| activist 13D | 20 | $21,510 | $2,151 | 90% | 45% |
| 8-K other event | 68 | $17,754 | $1,775 | 79% | 29% |
| 8-K material agreement | 39 | $17,629 | $1,763 | 85% | 21% |
| merger / tender | 20 | $16,490 | $1,649 | 85% | 45% |
| **8-K delisting** | 7 | **$1,960** | $196 | **57%** | 14% |

**When it prints, $80 is not the problem.** 79–99% of printing minutes support an
$80 order at 10% participation. Even $5,000 clears more than half the time on the
liquid types. Liquidity is binary here: either nothing trades, or enough trades.

## 3. Price move already gone at +1 minute

The offer at T+1min against the last print before the catalyst:

| catalyst type | n | median | mean | p90 | ≥1% | ≥5% | median fill lag |
|---|---|---|---|---|---|---|---|
| insider Form 4 | 3,098 | +0.07% | +0.43% | 2.1% | 23% | 3% | 990 min |
| offering / dilution | 1,119 | +0.08% | +0.22% | 2.2% | 23% | 3% | 884 min |
| **8-K earnings** | 607 | **+0.43%** | +0.81% | 6.6% | **43%** | **14%** | 996 min |
| passive 13G | 402 | +0.03% | +0.12% | 1.7% | 21% | 2% | 967 min |
| 8-K officer change | 367 | +0.04% | −0.00% | 2.6% | 26% | 3% | 1,020 min |
| 8-K material agreement | 356 | +0.06% | +0.98% | 4.7% | 30% | 10% | 1,001 min |
| 8-K other event | 356 | +0.30% | +1.16% | 3.7% | 35% | 8% | 974 min |
| **8-K reg-FD** | 301 | +0.44% | +1.71% | 4.4% | 37% | 10% | **198 min** |
| periodic 10-Q/K | 262 | +0.15% | +0.90% | 5.5% | 34% | 10% | 1,000 min |
| activist 13D | 97 | +0.12% | +1.75% | 8.4% | 34% | 13% | 946 min |
| merger / tender | 147 | +0.21% | +0.20% | 3.6% | 29% | 5% | 970 min |
| **8-K delisting** | 50 | +0.07% | **−3.17%** | 4.3% | 36% | 8% | 1,045 min |
| 8-K dilution | 26 | −0.00% | −1.01% | 2.8% | 31% | 4% | 977 min |

**Conditional on actually printing in that minute, the move is essentially zero:**

| catalyst type | median move at +1min, when it printed |
|---|---|
| 8-K reg-FD | +0.19% |
| activist 13D | +0.14% |
| 8-K other event | +0.08% |
| 8-K earnings | **+0.06%** |
| 8-K officer change | +0.06% |
| offering / dilution | +0.04% |
| insider Form 4 | +0.02% |
| passive 13G | 0.00% |
| 8-K delisting | **−4.35%** |

**This is the strongest evidence yet that the window is real.** When you can
trade at T+1min you pay roughly 2–19 basis points over the pre-catalyst price.
Nothing has moved. The larger unconditional medians (+0.43% for earnings) come
entirely from the 89% of cases where you waited sixteen hours for a market and
bought after the gap.

## 4. And what you get for being early

Forward return from the T+1min offer, selling the bid:

| catalyst type | n | +15 min | +60 min | +1 day |
|---|---|---|---|---|
| **8-K earnings** | 607 | −0.48% | −0.22% | **+0.17%** |
| **8-K other event** | 356 | −1.19% | −1.60% | **+1.07%** |
| 8-K officer change | 367 | −0.78% | −1.40% | −0.16% |
| 8-K reg-FD | 301 | −0.70% | −0.41% | −0.32% |
| passive 13G | 402 | −0.49% | −0.68% | −0.56% |
| insider Form 4 | 3,098 | −0.66% | −0.95% | −1.45% |
| periodic 10-Q/K | 262 | −1.00% | −0.88% | −1.49% |
| offering / dilution | 1,119 | −0.69% | −1.01% | −2.25% |
| activist 13D | 97 | −0.84% | −1.78% | −2.86% |
| merger / tender | 147 | −0.60% | −1.23% | −3.58% |
| proxy / other | 257 | −0.99% | −1.96% | −3.73% |
| 8-K vote results | 77 | −0.19% | −1.70% | −5.16% |
| **8-K dilution** | 26 | −3.17% | −4.91% | **−7.26%** |
| **8-K delisting** | 50 | −2.78% | −3.47% | **−8.18%** |

**Thirteen of fifteen catalyst types are negative at every horizon.** Only 8-K
earnings (+0.17%) and 8-K other event (+1.07%) are positive at one day, both
small and both negative at fifteen and sixty minutes.

Delisting and dilution are the standouts in the other direction — **−8.18% and
−7.26% at one day**, and they are also the two types with the worst liquidity
($1,960 and $853 in the printing minute). The market prices those correctly and
does not let you out.

## The answer in three lines

**Liquidity:** 24% of catalysts print in the minute after publication. When they
do, the median minute trades $90,634 — enough for $80 in 79–99% of cases and for
$5,000 in a third to a half.

**Price:** conditional on being able to trade, the price has moved **2–19 basis
points**. The window the thesis predicted is real and it is nearly free.

**Payoff:** negative for thirteen of fifteen catalyst types at every horizon. The
window exists, costs almost nothing to enter, and leads somewhere you do not want
to go.

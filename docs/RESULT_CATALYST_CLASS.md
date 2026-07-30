# Result: classifying 30 days of catalysts, then trading them

Reads every 8-K filed by a small, micro or mid cap in the last 30 days, grades
each one for trap-vs-positive and low/medium/high impact **from the filing text
only**, has a second reader try to knock down every medium and high, and then
runs the survivors through the $80 / two-slot simulator.

Nothing in the grading pass saw a price. `saw_price_outcome` is recorded per
filing and is `false` for all 83.

## The funnel

| stage | count | share |
|---|---|---|
| 8-Ks, last 30d, small/micro/mid | 791 | 100% |
| after excluding negative item codes | 724 | 92% |
| **tradable** (print at T+1min, ≥$1, prior session ≥$250k, entry bar ≥20× order, ≤10% already moved) | **83** | **10.5%** |
| positives after grading | 26 | 3.3% |
| traps caught | 4 | 0.5% |
| medium or high after challenge | 4 | 0.5% |

The 67 excluded on item code alone were 42 dilution (Item 3.02 / 1.01
financings) and 21 delisting (Item 3.01). Those are the traps the user named,
and they are visible in the item code before anyone reads a word.

**The binding constraint is liquidity, not judgement.** Nine of ten filings die
on the tradability screen before an analyst sees them, overwhelmingly because
the filing landed outside regular hours and nothing printed a minute later.

## Grades

| verdict | impact | n |
|---|---|---|
| trap | medium | 4 |
| positive | high | 1 |
| positive | medium | 3 |
| positive | low | 22 |
| neutral | low | 53 |

Two thirds of everything that survives the liquidity screen is administrative:
shareholder-vote results, director appointments, routine dividend declarations,
earnings that landed in line. That is the honest base rate of an 8-K.

### The four traps

| ticker | band | type | what it was |
|---|---|---|---|
| AMIX | micro | dilution | Cash of $5.1m disclosed alongside a share count that "includes shares issued as part of the Company's recent warrant inducement" — the inducement is the news, buried in a cash update |
| FATN | micro | dilution | Item 7.01 CEO letter answering shareholder anger about a fresh S-3 shelf and ATM, insisting nothing has been sold *yet* |
| IPW | small | dilution | Joinder adding a guarantor to a $30m 6% OID convertible facility, bundled with the formation of an AI-hardware leasing subsidiary that has no customers, no hardware, and "preliminary, non-binding interest" |
| LASE | micro | accounting | Auditor change that discloses, in passing, that the outgoing auditor's FY2025 report carried substantial-doubt going-concern language |

Three of the four are dilution wearing something else's clothes. None of them
would be caught by an item-code filter: AMIX and FATN are Item 8.01/7.01, IPW
leads with 1.01, LASE with 4.01. They need the text read.

### The challenge pass cut 9 of 11

Every medium and high went to a second reader told to knock it down. Two
survived, two were downgraded high→medium, seven were downgraded to low.

| ticker | before | after | why it was cut |
|---|---|---|---|
| ESI | positive/high | **kept** | Acquired by Solstice, $10.00 cash + 0.500 shares ≈ $50.10, 15% premium, ~$14.5bn. Verified verbatim against EX-99.1/99.2 |
| FCFS | positive/medium | **kept** | Record Q2: revenue +29%, GAAP EPS +58%, guidance raised again, new $150m buyback |
| FATN | high → medium | cut | A $7.0m contract is real but it is a school-district order, not a transformation |
| VERA | high → medium | cut | FDA accelerated approval for TRUTAKNA is genuine, but accelerated approval in IgAN follows a crowded label path |
| BMRC | medium → low | cut | 86% of the EPS improvement was seasonal expense timing; the NIM expansion had been pre-guided in the Q1 release; the analyst had conflated special-mention loans with non-accruals |
| BPOP, ARCB, JMSB, FNWD, XRN, NKSH | medium → low | cut | In-line quarters and already-announced deals restated |

The BMRC cut is the one worth keeping. The challenger decomposed the sequential
pre-tax bridge line by line and found the "beat" was a calendar artifact. That
is the failure mode a keyword scanner cannot reach, and it was found without
looking at what the stock did.

## Trading them

$80, two slots, position size = equity/slots so it compounds, entry at the
**high** of the bar one minute after acceptance (pay the offer), 6% target, 10%
stop that fills at `min(stop, bar_low)` so gaps cost what they cost, 240 bars
maximum hold, ambiguous bars booked as stops.

### Medium and high only — 4 candidates, 4 trades

| ticker | band | impact | filed ET | entry ET | entry | exit ET | exit | why | held | ret |
|---|---|---|---|---|---|---|---|---|---|---|
| ESI | mid | high | 07-06 09:13 | 09:30 | 44.31 | 07-06 13:30 | 42.60 | time | 240m | **−3.87%** |
| VERA | small | medium | 07-07 12:45 | 12:47 | 42.47 | 07-07 17:03 | 42.32 | time | 256m | −0.35% |
| FATN | micro | medium | 07-21 10:37 | 10:46 | 4.60 | 07-22 11:32 | 4.88 | target | 1486m | **+6.00%** |
| FCFS | mid | medium | 07-23 15:26 | 15:28 | 191.94 | 07-24 09:36 | 203.46 | target | 1088m | **+6.00%** |

$80 → $83.08, **+3.85%**, mean +1.94%, t = **+0.79**. Four trades is not a
result. It is the supply.

### All positives — 26 candidates, 13 trades

| ticker | band | impact | filed ET | entry ET | lag | entry | exit ET | exit | why | ret | balance |
|---|---|---|---|---|---|---|---|---|---|---|---|
| AVNS | small | low | 07-02 10:10 | 10:12 | 1.5m | 24.92 | 07-02 14:44 | 24.92 | time | 0.00% | 80.00 |
| ESI | mid | high | 07-06 09:13 | 09:30 | 16.8m | 44.31 | 07-06 13:30 | 42.60 | time | −3.87% | 78.45 |
| XRN | mid | low | 07-02 17:26 | 07-06 09:30 | 5283m | 38.10 | 07-08 11:13 | 36.88 | time | −3.20% | 77.17 |
| TCBX | small | low | 07-13 08:05 | 09:30 | 84m | 39.98 | 07-15 16:15 | 40.55 | time | +1.43% | 77.72 |
| MAIN | mid | low | 07-16 09:15 | 09:30 | 14m | 53.68 | 07-16 13:59 | 55.35 | time | +3.10% | 78.93 |
| CCRN | small | low | 07-17 08:19 | 09:30 | 71m | 13.25 | 07-20 10:46 | 13.25 | time | 0.00% | 78.93 |
| FNWD | micro | low | 07-06 16:45 | 07-07 09:37 | 1012m | 36.99 | 07-21 16:55 | 39.21 | target | +6.00% | 81.28 |
| FATN | micro | medium | 07-21 10:37 | 10:46 | 8.4m | 4.60 | 07-22 11:32 | 4.88 | target | +6.00% | 83.65 |
| BPOP | mid | low | 07-23 08:10 | 09:30 | 79m | 175.12 | 07-23 15:01 | 172.15 | time | −1.70% | 82.94 |
| FCFS | mid | medium | 07-23 15:26 | 15:28 | 1.0m | 191.94 | 07-24 09:36 | 203.46 | target | +6.00% | 85.43 |
| PROF | micro | low | 07-24 11:58 | 12:03 | 4.4m | 7.02 | 07-27 09:40 | 7.44 | target | +6.00% | 87.99 |
| CAC | small | low | 07-28 08:05 | 09:30 | 84m | 55.87 | 07-29 14:44 | 59.22 | target | +6.00% | 90.63 |
| JMSB | micro | low | 07-22 08:40 | 09:30 | 50m | 22.89 | 07-29 14:51 | 23.61 | time | +3.17% | 91.92 |

$80 → $91.92, **+14.90%** over 30 days. Mean +2.23%, median +3.10%, win 62%,
**t = +2.16** on 13 trades. Exits: 5 targets, 8 time.

| impact | n | mean | median | win | pnl |
|---|---|---|---|---|---|
| high | 1 | −3.87% | −3.87% | 0% | −$1.55 |
| medium | 2 | +6.00% | +6.00% | 100% | +$4.86 |
| low | 10 | +2.08% | +2.26% | 60% | +$8.61 |

| band | n | mean | pnl |
|---|---|---|---|
| micro | 4 | +5.29% | +$8.57 |
| small | 4 | +1.86% | +$3.19 |
| mid | 5 | +0.07% | +$0.16 |

## What to believe and what not to

**13 trades, not 20.** Thirteen candidates were skipped for `no free slot`.
Candidate supply was not the constraint; hold time was. Five of the thirteen
trades ran past a full session because 240 *bars* is four trading hours, which
spans overnight and, for FNWD, fourteen calendar days. Getting to twenty trades
would take three or four slots or a shorter hold — a change that must be made
before seeing results, not after.

**t = +2.16 on n = 13 is not significant** at any bar this project has been
holding itself to. It is one month, and the pre-registered 2015–2026 test on
the same machinery came out at −0.15% per trade. Thirty days cannot overturn
eleven years; it can only fail to.

**Two trades returned exactly 0.00%** (AVNS, CCRN) because the exit bar's low
equalled the entry bar's high — nothing printed in between and the price
carried forward. That is the same staleness that dominated the latency study,
and it means "flat" here sometimes means "untradable", not "unchanged".

**The impact grade did not predict the return.** The single high-impact event
was the worst trade in the book, and the ten low-impact events carried 72% of
the profit. n = 1 in the high bucket makes this uninterpretable in either
direction, but it is the opposite of the hypothesis: reading the filing harder
did not find the money.

**The cap monotonicity survives here.** Micro +5.29%, small +1.86%, mid +0.07%
— the same ordering as the +0.82% CAR+20 on micro caps in the eleven-year
panel, and the same ordering the cost model says should be *reversed* once
spread is charged properly. Minute bars carry no quotes, so the spread on a
$4.60 micro cap is not in these numbers at all, and at $40 an order it is the
entire economics. This is the open question, not a finding.

**Survivorship is untested here.** The 30-day window is too short for a
delisting to bite, so nothing in this table is protected against it. The
eleven-year panel showed survivorship bias on micro caps to be roughly the same
magnitude as the entire measured edge.

**The one durable result is the trap screen.** 67 caught on item code, 4 more
caught only by reading, 3 of those 4 dilution disguised as something else. That
part is mechanical, verifiable, and does not depend on any return being real.

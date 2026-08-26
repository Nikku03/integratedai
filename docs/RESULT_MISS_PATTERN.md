# What we got wrong in the last fifteen days

Window C, 2026-06-05 → 06-26, the pre-registered run. 45 filings, 24 of them
judged directionally (±1 or ±2). **Ten right, eleven wrong, three flat.** A coin
flip, and the pooled three-window figure agrees.

## The eleven misses

**Called good, it fell (7)**

| | judged | return | what it was |
|---|---|---|---|
| TOON | +2 | **−35.6%** | $28.5M of litigation settlements coming *in*, 6× its cash |
| ELTX | +1 | −23.8% | complete responses in metastatic pancreatic cancer |
| BGDE | +1 | −21.5% | regained Nasdaq equity-rule compliance |
| PDSB | +1 | −11.4% | regained Nasdaq minimum-bid compliance |
| OTLK | +1 | −10.3% | FDA accepted the BLA, PDUFA six weeks out |
| ABSI | +1 | −7.2% | positive interim Phase 1, 65-day half-life |
| VNCE | +2 | −5.5% | Q1 beat, guidance raised |

**Called bad, it rose (4)**

| | judged | return | what it was |
|---|---|---|---|
| CRMT | −2 | **+80.3%** | lender forbearance on imminent covenant defaults, one week |
| RGNX | −1 | +48.2% | underwater option repricing |
| HYPD | −1 | +17.7% | both yield agreements terminated |
| TRDA | −1 | +12.5% | evergreen share formula widened |

## The story the misses tell — and why most of it is wrong

Split the judged-positive calls by what the price had already done, and the
separation looks decisive. On window C, and again on all 114:

| | median 20-day momentum | 60-day |
|---|---|---|
| judged good, **fell** | **+64%** (pooled +31%) | +161% (pooled +74%) |
| judged good, **rose** | **−2%** (pooled −12%) | −17% (pooled −37%) |

| | below 52-week high | realised vol |
|---|---|---|
| judged bad, **rose** | **−86%** | 172% |
| judged bad, **fell** | −72% | 124% |

That reads as two clean lessons: good news bought after the move fails, and
deeply distressed equity is a call option that re-rates on any news that isn't
fatal. Both are stories fitted to 114 outcomes, so both were tested on the gated
panel — **160,918 rows, fifteen walk-forward blocks**.

### What survived: the volume surge, and it is small

Forward return by prior momentum (rows) × filing-day volume against its own
20-day median (columns):

```
                 C1         C2         C3         C4         C5     spread
R1           -0.48%     +0.53%     +0.35%     +0.05%     -0.98%     -0.50pp
R2           -0.07%     +0.25%     +0.02%     +0.02%     -0.39%     -0.32pp
R3           -0.01%     +0.07%     +0.19%     -0.07%     -0.35%     -0.35pp
R4           +0.02%     +0.19%     -0.05%     -0.19%     -0.52%     -0.54pp
R5           -0.01%     +0.04%     -0.19%     -0.07%     -0.26%     -0.25pp
```

**The top volume-surge quintile is negative in all five momentum rows**, by
−0.25 to −0.54pp. A filing that visibly moved volume is a filing the market has
already read, and entering afterwards costs about half a point. That is real,
consistent, and small.

### What did not survive: momentum

Momentum contributes nothing. Extended names returned −0.08%, un-extended
−0.09%. The spread down each column is noise, and R5C5 (−0.26%) is *better*
than R1C1 (−0.48%) — the opposite of the story. The +64%-vs-−2% split in the
misses is a 12-observation artefact.

### What was refuted outright: the option story

`ctx_from_high` is negative, so its bottom quintile is the *most* crushed. Those
names are simply bad:

| subset | rows | mean | median | compounds |
|---|---|---|---|---|
| the whole gate | 160,918 | −0.08% | −0.20% | −0.92% |
| extended | 79,910 | −0.08% | −0.20% | −0.90% |
| not extended | 81,008 | −0.09% | −0.23% | −0.93% |
| extended **and** volume surged | 39,553 | −0.13% | −0.26% | −1.08% |
| **bottom quintile from high** | 33,017 | **−0.87%** | **−1.79%** | **−2.73%** |
| **that, and top vol quintile** | 17,993 | **−1.60%** | **−3.12%** | **−4.09%** |

The most-crushed, most-volatile cell — exactly where CRMT and RGNX sat — is the
**worst** part of the gate, not a coiled option. It loses 1.60% a trade with a
median of −3.12%.

**So CRMT +80% and RGNX +48% were not insight I lacked. They were draws from the
fat left-tailed distribution those names live in, and they happened to come up
right.** Building a rule around them would have bought the worst cell in the
panel.

## What we actually did wrong

1. **Nothing systematic on the bad calls.** Four "called bad, rose" out of
   twelve negative judgements is what a −4% mean with a huge variance produces.
   The names were correctly identified as distressed; distressed names sometimes
   double.
2. **One real error on the good calls: entering after the tape had read the
   filing.** TOON at 10.5× normal volume, FTHM at 27.9×, ELTX at 38.6×, HCAT at
   8.6× — those pops happened before the D+1 entry. Worth about −0.5pp, and it
   is a mechanical problem, not a judgement one.
3. **Judging "is this good news" instead of "is this better than expected".**
   OTLK's BLA acceptance and ABSI's Phase 1 were genuinely good and genuinely
   expected; I wrote "the stock is up 504% in twenty sessions" and "a raise is
   imminent" in the labels themselves and still scored them +1. The information
   was in my own notes and I did not act on it.
4. **Nothing at all on four of the seven positive misses.** PDSB, BGDE — Nasdaq
   compliance regained — are non-events. The stock rising *caused* the
   compliance; the filing reports it afterwards. Scoring them +1 was scoring an
   echo.

## What this changes

Very little, and that is the finding. The one durable lesson — skip filings the
tape has already digested — is worth half a percentage point against a gate that
loses 0.92% a trade compounded. It does not fix anything.

The larger correction is the one in `RESULT_LOSS_AUTOPSY.md`: the pool itself has
a negative growth rate, and no amount of better reading of individual filings
addresses that.

## Reproducing

```
python3 scripts/miss_pattern.py
```

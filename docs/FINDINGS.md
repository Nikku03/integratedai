# Real-data findings

The system was run against live data as part of building it. This is what came
back. It is the most decision-relevant output here, and it is not encouraging,
which is the point of having built the diagnostic first.

---

## Run 1 — 19 high-beta / retail-heavy names, 2021–2024

`PLUG MRNA RIOT MARA AMC BBBY SPCE NKLA FCEL CLOV WKHS GME SOFI LCID CHPT BLNK
OPEN AFRM UPST DKNG` · 3,218 EDGAR events · 15 kinds tested

**No event kind showed a significant tradable drift.** Every |t| < 2 before any
correction.

Directionally sensible things that were nonetheless not significant:

- `form.424B5` (shelf takedown): `day0_car` −7.6%. Dilution really does hurt on
  the day. But it is a day-0 move — gone by the next open.
- `8-K.3.02` (unregistered equity sale, usually a PIPE): `pre_car` +3.8%,
  `drift_car` −5.3%, t = −1.76. The strongest thing in the run and still short
  of significance.

## Run 2 — 46 small/mid caps across biotech, semis, materials, solar, 2019–2024

Broader and longer, chosen for sectors where catalysts plausibly matter rather
than where flow dominates. 7,794 EDGAR events · 15 kinds tested.

| kind | n | pre_car | day0_car | drift_car | t | p | survives FDR |
|---|---|---|---|---|---|---|---|
| `form.424B5` | 145 | **+8.01%** | −1.12% | −2.35% | −2.01 | 0.044 | **no** |
| `8-K.5.03` | 83 | +3.96% | +1.17% | +2.05% | 1.54 | 0.123 | no |
| `form.10-K` | 231 | +0.81% | +0.42% | −1.18% | −1.05 | 0.296 | no |
| `8-K.2.02` (earnings) | 932 | +0.15% | +0.52% | −0.94% | −2.07 | 0.039 | **no** |
| `8-K.1.01` (material agreement) | 346 | +1.94% | +0.29% | −0.54% | −0.68 | 0.497 | no |
| `8-K.9.01` | 2174 | +0.47% | +0.37% | −0.12% | −0.36 | 0.719 | no |

*(9 further kinds, all |t| < 1.2, omitted.)*

### **0 of 15 kinds survived FDR correction.**

---

## The two results worth understanding

### 1. `form.424B5` and endogeneity

`pre_car` = **+8.0%**. A shelf takedown is preceded by an 8% run-up.

That is not a data-latency bug — the EDGAR timestamp is accurate to the second.
It is **endogeneity**: companies issue equity *because* the stock ran up. The
event is caused by the prior return.

This matters because the naive read — "424B5 predicts −2.35%, short it" — is
confounded. You are not measuring the effect of the filing; you are measuring
what happens after a stock that already ran 8% does a dilutive offering. The
`CONFOUNDED` verdict exists to flag exactly this shape, and the distinction
from a late timestamp matters: a late timestamp is fixable by buying faster
data, endogeneity is not fixable at all.

### 2. `8-K.2.02` and why the correction earns its keep

Post-earnings drift of −0.94% at t = −2.07, p = 0.039. Under a naive |t| > 2
rule this is a discovery, and the first version of this tool reported it as
`tradable drift -0.94%`.

It is not a discovery. **Fifteen hypotheses were tested simultaneously.** At
p < 0.05 you expect 0.75 false positives per run from pure noise, and getting
one is the single most likely outcome. Under Benjamini-Hochberg at FDR 10% it
does not survive.

And even if it were real: −0.94% over 20 days, before costs. The cost model
charges ~9bp one-way on liquid names and considerably more on the small caps
where the effect would have to live. Half the alleged edge is gone to the
spread before impact.

This is why `event_study_summary` now reports `survives_fdr` and why the
verdict string for this case reads `NOT SIGNIFICANT after multiple-testing
correction` rather than a dollar figure.

---

## What this does and does not establish

**Does:**

- The pipeline runs end to end on real data — SEC universe resolution (10,432
  issuers), EDGAR submissions with item codes, Yahoo prices, PIT validation,
  event study.
- The naive hypothesis "8-K item type → post-event drift" does **not** survive
  on these universes over these periods. Anyone selling you that is selling
  something.
- The diagnostic layer works, and it works by saying no.

**Does not:**

- Prove no catalyst edge exists. Two universes, one data source, one
  specification. The event study is a *marginal* test — it asks whether an event
  kind moves price on average, unconditionally. Real edge in this domain is
  more plausibly conditional: an Item 1.01 in a microcap with no analyst
  coverage and an unusual pre-print volume surge is a completely different
  object from an Item 1.01 at ILMN, and the marginal test averages them
  together into nothing.
- Test the sources most likely to carry differentiated signal. Litigation,
  bills of lading and jet convergence were **not** included in these runs —
  CourtListener at the anonymous tier is too slow to sweep 46 names, and the
  manifest and ADS-B feeds need paid credentials. Those are the ones where the
  data is genuinely hard to get, which is where edge tends to live.

---

## What I would do next, in order

1. **Widen the universe before anything else.** 46 names and ~150 events per
   kind gives a standard error around 1.2% on a 20-day CAR. You cannot detect a
   1% effect with that. Take the Russell 2000, use `CsvPrices` with a
   survivorship-bias-free vendor extract, and you get 10–50× the events. Most
   of the "no detectable effect" rows above are statements about power, not
   about the world.

2. **Test conditional, not marginal, effects.** Split each kind by market cap,
   analyst coverage, pre-event volume surge, and short interest. The
   unconditional average of a heterogeneous population is the least informative
   summary of it.

3. **Add the sources that were not tested.** Get a CourtListener token, price a
   bill-of-lading feed. If a source is free and universally available, its edge
   has been arbitraged; that is roughly what these results show for EDGAR item
   codes on their own.

4. **Only then fit a model.** Nothing above justifies training one yet. The
   scaffold is ready when the event study gives you something to model.

Reproduce with `iai fetch` then `iai research`. The event study runs
automatically and prints before the model does — deliberately, so you see the
refutation before you see a Sharpe ratio.

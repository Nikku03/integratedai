# The pre-trade checklist: what survives and what does not

Eighteen candidate questions, each a binary condition computable before the
trade, scored on the model's own 1,759 picks. **Derived on 2019-2022, tested on
2023-2025.**

## As a winner-picker it fails completely

The eight-question composite scored +5.66pp (high-score minus low-score) on the
derivation years with a CI of [+1.57, +9.96] and P = 0.0031. On the test years it
scored **+1.13pp, CI [−3.58, +5.89], P = 0.3229. FAIL.**

Individually it is worse than that. Of eighteen questions, **not one** has the
same sign in both periods *and* a test interval excluding zero. Nine of eighteen
keep their sign — exactly the 50% that coin-flipping predicts.

The two strongest derivation questions inverted outright:

| question | 2019-2022 | 2023-2025 |
|---|---|---|
| A material-agreement 8-K in the last month | **+4.63pp** | **−2.39pp** |
| A material-event 8-K in the last month | **+3.40pp** | **−2.37pp** |

Those were the catalyst questions — the ones the premise rested on.

### Why it was never going to work

The reason is mechanical and I should have seen it before building this. The
gradient-boosting model already receives all 108 features and fits optimal splits
on every one of them. A hand-written rule like `cash_per_cap > 0.15` cannot add
information to a model that already has `cash_per_cap` as an input and has
already found the best threshold for it. **The checklist was asking the same data
the same question twice**, and the second answer was a cruder version of the
first.

A checklist can only add value if it carries information the model does not have.
Nothing in that list of eighteen did.

## As a disaster-veto, three questions survive

Different question, and the one this project has repeatedly found answerable:
not "which trade wins" but "which trade blows up". Disaster defined as a position
closing at −20% or worse, which happens to 17.6% of picks.

| question | derive | test | test 95% CI | disaster if YES | if NO |
|---|---|---|---|---|---|
| **No unregistered share issuance (8-K 3.02) in the quarter** | −1.97pp | **−11.82pp** | [−19.37, −4.48] | **15.1%** | **26.9%** |
| Not in a violent regime (20d daily vol under 6%) | −2.96pp | −6.25pp | [−12.22, −0.11] | 12.6% | 18.8% |
| An insider bought in the last quarter | −0.90pp | −5.83pp | [−11.51, −0.04] | 13.3% | 19.1% |

All three keep their sign across periods and exclude zero out of sample. With
eighteen questions tested, Bonferroni requires α = 0.0028: **only the first one
clears it.** The other two are suggestive and should be treated as such.

**This is the third independent time in this project that loser-avoidance has
worked where winner-picking failed** — after the burn-rank test and the
registration screen. The asymmetry is real and it is worth building around.

### The one that clears the bar, and a correction

8-K item 3.02 is an unregistered sale of equity securities — a PIPE, a
convertible, a warrant issue. A company that has just sold stock privately, often
at a discount and often on punishing terms, blows up at **26.9%** against
**15.1%** for one that has not. That nearly halves the disaster rate.

It also corrects something from earlier in this session. I built the
`dilution_armed` screen around **registration** (S-3, 424B5) and rejected REPL
largely on its shelf going effective. Tested here, "no registered stock ready to
sell" gives only −2.81pp with a CI of [−8.78, +2.96] — **not significant**. The
*actual issuance* discriminates; the *paperwork to issue* does not. That is a
meaningful refinement, and it means the REPL reasoning was directionally right
for a weaker reason than I claimed.

## The checklist worth actually using

Three questions, and they veto rather than select:

1. **Has the company issued unregistered stock in the last quarter?**
   (8-K item 3.02.) If yes — skip. Disaster rate 26.9% against 15.1%.
   *This is the only one with statistical standing after multiple-testing
   correction.*
2. **Is 20-day daily volatility above 6%?** If yes — skip, or size down.
   Suggestive, not proven.
3. **Has any insider bought in the last quarter?** If no, expect a higher
   blowup rate. Suggestive, not proven.

Nothing else on the list earned a place. In particular, do not screen on recent
catalysts, share price, market cap, cash runway, or how far the name has already
run — all were tested and all failed.

## What actually controls the risk

Not a screen. The exposure is structural: 2.27% of trades carry the entire
result, so the left tail cannot be selected away, only sized.

| configuration | final equity | max drawdown |
|---|---|---|
| 4 slots, full size | 12.84x | **−89.3%** |
| 10 slots, full size | 6.11x | −57.7% |
| 20 slots, full size | 2.84x | −34.6% |
| 10 slots at half size | 2.84x | −34.6% |
| 10 slots at quarter size | 1.75x | −19.0% |

Risk and return move together almost exactly: halving the size halves the
drawdown and roughly halves the compounding. There is no configuration that
keeps 6x and removes the 58% drawdown, and any rule that appeared to would be
overfitting.

**Concentrating into four slots to hit twenty trades a month produces an 89%
drawdown.** That is the single most important number here for a small account.

## The honest answer to "eliminate all the risks"

It cannot be done, and the attempt is where this kind of work usually goes wrong.
What can be done, and is supported out of sample:

- **Veto on 3.02 issuance.** Roughly halves the blowup rate. Real.
- **Size for the drawdown you can actually sit through**, not the return you want.
- **Do not run four slots.**

Everything else in the eighteen was noise, and the composite that looked strong
on four years of data did nothing on the next three.

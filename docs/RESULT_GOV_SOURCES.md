# Result: DoD contracts, FDA decisions and trial readouts

The move census attributed causes from SEC form types only, so anything announced
on a government site landed in the 38% "no filing" bucket — the largest single
category of 20%+ moves. These are the three sources this project kept circling.

Both directions were run. Only the second can support a conclusion.

## The design that matters: compare against the name's own baseline

Measuring "what happened after an FDA approval" against zero, or against the
market, confounds the event with the company. A biotech running trials has a
different return distribution than an industrial, and July was kind to biotech.

So every event's 10-session forward return is compared with **the same ticker's
average 10-session forward return from every other entry date in the window.** If
the event carries information, event dates beat the name's own baseline. If they
do not, the apparent edge is a name effect wearing an event's clothes.

One subtlety, and it runs in the conservative direction: for names with many
events the baseline includes the event dates themselves, biasing the measured
excess *toward zero*. The true negative excess is therefore likely larger than
what is reported below.

## Backward: government sources explain 2% of the tail

| | count |
|---|---|
| 20%+ movers in the window | 222 |
| with an FDA / trial event within 7 days | **4 (2%)** |
| of the 83 with *no SEC filing*, had a gov event | **2** |

The four: CRNX +126% (also had an 8-K), SCLX +27% (13D), ARWR +24%, VERX +22%.

**The "no filing" bucket is not FDA, trials or DoD.** Two of 83. Whatever drives
38% of large moves, it is not on these three sites — it is sector sympathy,
analyst actions, index events, squeezes and peer news, none of which this
repository reaches.

## Forward, FDA and trials: 684 events, entry at next session open

Government sources publish date-only, so the earliest actionable price is the
open of the following session. Same rule as the 8-K test, so the numbers are
comparable.

| source | n | d0 | d1 | d5 | d10 | t(d10) | **excess vs own baseline** | t | p |
|---|---|---|---|---|---|---|---|---|---|
| FDA drug submissions | 39 | −0.60% | −0.79% | +0.73% | +1.07% | +0.90 | +0.39% | +0.53 | 0.598 |
| FDA device PMA | 39 | +0.44% | −1.03% | −0.78% | −0.48% | −0.56 | **−1.99%** | −3.25 | **0.002** |
| FDA 510(k) | 7 | +0.91% | +0.73% | −3.86% | −3.47% | −1.23 | **−3.98%** | −2.95 | 0.026 |
| trial results posted | 56 | +0.12% | −0.35% | −1.81% | −1.40% | −1.01 | **−2.19%** | −2.16 | 0.035 |
| trial record updates | 543 | +0.03% | −0.16% | +0.44% | +0.91% | **+2.69** | **−0.70%** | −2.53 | **0.012** |
| **all gov** | **684** | +0.03% | −0.25% | +0.16% | +0.61% | +1.99 | **−0.87%** | **−3.57** | **0.000** |
| *(8-K, same rule)* | *1,861* | *−0.39%* | *−0.84%* | *−1.76%* | *−2.55%* | *−8.99* | — | — | — |
| one observation per name | 142 | | | | | | **−3.16%** | **−4.99** | **0.000** |

**The one apparently positive result is the one that dissolves.** Trial record
updates show +0.91% at t=+2.69 — significant, and it would have been reportable.
But those names' own baseline over any 10-day window in July was **+1.62%**. The
event dates delivered *less* than picking a random date in the same names. It was
never information; it was a marker for "biotech with an active pipeline" in a
month when those did fine.

A ClinicalTrials.gov `LastUpdatePostDate` is mostly administrative anyway —
recruitment status, site additions, contact changes. And the events that *are*
news, the 56 actual results postings, are the second-worst category at −2.19%
excess.

Every category is at or below its own baseline. Aggregated: **−0.87%, t=−3.57.**
Collapsed to one observation per name so 543 updates on 145 names cannot pose as
543 independent draws: **−3.16%, t=−4.99.**

## Forward, DoD: it is a large-cap story, and there is no small-cap version

111 awards across 7 sampled digest days (Jul 1–29), **$38.3bn total**, harvested
from war.gov via WebFetch — the site's Akamai edge refuses container curl.

| | count | dollars |
|---|---|---|
| awards in sample | 111 | $38.3bn |
| matched to a public ticker | **27 (24%)** | $27.0bn (**71%**) |
| unmatched | 78 | $11.3bn |

The 78 unmatched are private LLCs, joint ventures and non-profits: RAND, Johns
Hopkins APL, Thoma-Sea Marine Constructors, Aventis LLC, GMHill-Baker JV,
Goodwill Industries of South Florida, Industries of the Blind, DZSP 21 LLC. They
have no stock.

Every matched name is large cap:

| ticker | awards | total $m | cap $bn | awards as % of cap |
|---|---|---|---|---|
| LMT | 9 | 13,207 | 116.6 | 11.3% |
| GD | 2 | 6,458 | 92.4 | 7.0% |
| HII | 1 | 3,745 | 11.4 | 32.9% |
| RTX | 2 | 1,863 | 247.3 | 0.8% |
| LHX | 2 | 542 | 53.2 | 1.0% |
| AVAV | 1 | 500 | 13.2 | 3.8% |
| CLF | 1 | 400 | 6.6 | 6.0% |
| JLL, LDOS, USFD, BAH, NOC, AMTM | 7 | 305 | 5.3–87.2 | ≤0.7% |

**Median award is 0.7% of market cap.** The smallest genuine match is AMTM at
$5.3bn. There is not one small or micro cap in the sample.

Two matches that *looked* like small caps were name collisions and were dropped:
**"Protagonist Technology LLC" is not Protagonist Therapeutics (PTGX)**, and
"Integer Technologies LLC" is not Integer Holdings (ITGR). Both were among the
smallest apparent matches, which is exactly where a collision does the most
damage to a conclusion.

Forward test on the 23 awards to 12 genuine public names:

| horizon | mean | median | win | t |
|---|---|---|---|---|
| d0 | +0.78% | +0.24% | 52% | +1.67 |
| d1 | −0.26% | −1.21% | 43% | −0.44 |
| d5 | −0.06% | −1.09% | 38% | −0.04 |
| d10 | +0.57% | −0.62% | 48% | +0.30 |

Against the same names' own baseline: award dates **+0.57%** against a baseline
of **+3.34%** — excess **−2.77%**, t=−1.69, p=0.106. Not significant at n=21, but
pointing the same way as everything else.

The ≥$1bn awards (n=3) show +10.67% and +6.30% excess. Three observations on
LMT/GD/RTX during a defence-sector rally is an anecdote, not a finding.

## What this settles

**Neither DoD, FDA nor trials is the missing catalyst.** They explain 2% of the
20%+ moves, and on the forward test every one of them underperforms buying the
same names on a random day.

**The DoD idea has a structural problem, not a measurement problem.** The awards
go to companies too large for a contract to matter, or to private entities with
no stock. A $500m award against a $116bn market cap cannot produce a moonshot,
and the entities where it *would* matter are LLCs. No amount of faster scraping
changes that.

**The trial-update result is the cautionary one.** t=+2.69 on 543 observations,
and completely spurious — a name effect that the within-name baseline exposed
immediately. Any future source added to this project should be tested that way
before anything else.

## Caveats

**Name matching is a floor, not an estimate.** 9% of FDA/trial events and 24% of
DoD awards matched a ticker, using exact matching on normalised names. Fuzzy
matching would raise the rate and manufacture false positives — the PTGX collision
shows what those cost. Real coverage is higher than these rates; whether the
unmatched events behave differently is untested, though there is no obvious reason
the *matchability* of a company name would correlate with its return.

**One month.** 684 gov events and 111 DoD awards over 30 days, with DoD sampled
at 7 of 21 digest days.

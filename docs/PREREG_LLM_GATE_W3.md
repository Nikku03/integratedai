# Pre-registration: window C of the filing-reading test

Committed **before** `--build` is run on window C and before any outcome for it
is computed. The git timestamp is the evidence.

Windows A and B produced opposite answers. The bucket table pooled over both
suggested a narrower hypothesis than the one originally tested, and that
hypothesis was chosen *after* seeing the data, which makes it worthless as
evidence until it is tested forward. This is that forward test.

## Window

Offset 30: **2026-06-05 → 2026-06-26**, fifteen sessions, no overlap with A
(2026-07-21 → 08-10) or B (2026-06-29 → 07-20). No result document in this
repository reports outcomes for it. It post-dates the reader's knowledge cutoff.

## What changed in the machinery

`company_context.py` had four defects, all now fixed and all documented in its
module docstring: DEF 14A pay-versus-performance facts scaled 1000× being
preferred over the 10-K; the missing fourth quarter silently routing TTM
through that path; market caps computed from a share count on a different split
basis than the panel's volume; and an `EntityPublicFloat` up to eighteen months
stale printed beside a current market cap. A fifth defect was in the *fix* — the
year-roll double-counted quarters — and is also corrected.

The nine tape-derived context columns are now given to the **ranker** as well as
the reader, which is what was asked for and was not done in window B.

## Hypotheses, in order

1. **Primary.** `veto −2 only` — take the model's top gated name unless the
   filing reads strongly negative, then step down — beats `model k=1`.
   Pooled over A+B this was +4.90pp per trade. **Post-hoc there; forward here.**
2. **Secondary.** Filings judged −2 underperform the rest of the shortlist.
   Pooled over A+B: 12 of 13 losers, mean −16.6%.
3. **Expected to fail.** The blanket veto (reject anything `judge < 0`). In A+B
   the −1 bucket returned +5.56% with 8 winners in 11, so rejecting it should
   cost money. Recorded so that confirming it is not presented as a discovery.
4. **Open.** Whether the context features help the ranker: `model k=1` with the
   nine context columns against `--no-context`. No directional prediction.

## Rules fixed in advance

* Direction is judged −2…+2 and materiality 0…3, from the filing and the
  context block only, for all 45 shortlist entries, before `--score` is run.
* The primary comparison is the mean net return per trade over the fifteen
  sessions, costs at 20bp, horizon 10 sessions, exactly as in windows A and B.
* Fifteen trades cannot establish an effect. A positive result here means the
  hypothesis survives to a fourth window; it does not mean the edge is real.
* Windows A and B are not re-judged. A's context was absent and B's was
  corrupted, but both have already been scored, so re-reading them would not be
  blind.

# Result: $80, one month, trading the filing feed

A concrete simulation rather than an aggregate: **$80**, at most **two $40
positions** at once, compounding, reacting to SEC filings within a minute of
EDGAR accepting them, over the last 30 days of real 1-minute bars.

```
17 trades (17.0/month vs 20 targeted)    win rate 41.2%
mean -0.31%/trade, median -2.80%          median hold 25.4h
exits: 8 stop, 5 time, 4 target
$80.00 -> $77.73   (-2.8%)
```

## The trades

| ticker | items | filed (ET) | PR | entry | entry px | already moved | exit | why | held | ret |
|---|---|---|---|---|---|---|---|---|---|---|
| AVNS | 7.01,9.01 | 07-02 10:10:31 | attached | 10:12 | 24.925 | −0.02% | 07-14 10:48 | time | 12.0d | +0.10% |
| SKYQ | 1.01,1.02,2.03 | 07-02 14:25:17 | no EX-99 | 14:27 | 2.527 | −0.13% | 07-06 05:54 | stop | 3.6d | −4.00% |
| ESI | 7.01,9.01 | 07-06 09:13:10 | attached | 09:30 | 44.310 | −1.20% | 07-06 09:33 | stop | **3m** | −4.00% |
| SSB | 7.01,9.01 | 07-06 09:39:50 | attached | 09:42 | 100.740 | +0.15% | 07-09 07:21 | stop | 2.9d | −4.00% |
| MAIN | 2.02,9.01 | 07-09 09:38:49 | no EX-99 | 09:40 | 51.130 | −0.02% | 07-15 11:35 | time | 6.1d | +4.83% |
| LKFN | 7.01,9.01 | 07-14 14:16:22 | no EX-99 | 14:26 | 60.635 | +0.06% | 07-28 09:54 | target | 13.8d | +6.00% |
| SRXH | 7.01,9.01 | 07-15 15:45:14 | attached | 15:47 | 2.250 | +0.00% | 07-15 15:58 | stop | **11m** | −4.00% |
| MAIN | 2.02,9.01 | 07-16 09:15:53 | no EX-99 | 09:30 | 53.680 | +0.43% | 07-17 04:06 | target | 18.6h | +6.00% |
| CCRN | 5.07,9.01 | 07-17 08:19:25 | no EX-99 | 09:30 | 13.250 | +0.00% | 07-20 16:00 | time | 3.3d | 0.00% |
| MNSB | 8.01 | 07-21 09:32:16 | no EX-99 | 09:42 | 24.170 | −0.94% | 07-21 14:47 | stop | 5.1h | −4.00% |
| JMSB | 2.02,9.01 | 07-22 08:40:12 | attached | 09:30 | 22.890 | **+4.38%** | 07-22 09:32 | stop | **2m** | −4.00% |
| AROW | 2.02,7.01,8.01 | 07-23 07:29:51 | attached | 09:30 | 40.235 | −1.22% | 07-24 09:30 | stop | 1.0d | −4.00% |
| ARCB | 8.01,9.01 | 07-24 11:07:30 | attached | 11:09 | 153.320 | +0.09% | 07-27 10:19 | stop | 3.0d | −4.00% |
| CARE | 7.01,9.01 | 07-27 11:24:16 | no EX-99 | 11:26 | 34.330 | −0.10% | 07-29 15:04 | time | 2.2d | +0.64% |
| SRXH | 3.02 | 07-28 09:57:16 | no EX-99 | 09:59 | 1.470 | +0.68% | 07-28 10:43 | target | 44m | +6.00% |
| AMIX | 8.01 | 07-28 11:36:42 | no EX-99 | 11:39 | 2.680 | **+3.08%** | 07-28 13:16 | target | 97m | +6.00% |
| USCB | 7.01,9.01 | 07-28 13:46:36 | no EX-99 | 13:48 | 22.995 | −0.02% | 07-29 15:09 | time | 25.4h | −2.80% |

## There was no gap to be early to

Read the `already moved` column. It is −0.02%, −0.13%, +0.15%, −0.02%, +0.06%,
+0.00%, +0.43%, +0.00%, −0.94%, −1.22%, +0.09%, −0.10%, +0.68%, −0.02%.

**The filings did not move the stocks.** Not "the move was gone before we could
act" — there was no move. Arriving one minute after an 8-K put us in a stock
trading exactly where it had been trading a minute earlier, which is the same
place it would be trading an hour later.

The two exceptions are instructive. JMSB had run **+4.38%** by entry and
stopped out **two minutes later**. AMIX had run +3.08% and worked. One of each
is not a pattern; it is the sample size.

## The constraint that actually bound was slots, not selection

```
FILINGS SKIPPED (1,077 of 1,094)
  no free slot            667
  outside bar coverage    220
  no trade at T+1min      184
  sub-$1                    3
  illiquid name             1
  entry bar too thin        1
  already ran >50%          1
```

**667 skipped because both slots were occupied.** With two positions and a
25-hour median hold, the account is nearly always full, so it takes *whatever
arrives next* rather than anything chosen. The trap filters — the part designed
to avoid pumps and illiquidity — rejected **six filings in total**.

This matters for interpreting the result: the strategy did not pick badly, it
never got to pick. Any conclusion here is about the filing feed as a whole,
not about a selection method.

It also explains why the 20-trades-a-month target came in at 17 and could not
simply be raised. More trades requires more slots or shorter holds, and both
change the strategy rather than tuning it.

## Where the press release actually was

**41% of trades had the press release filed as EX-99 to the 8-K.** For those,
the filing *is* the announcement — one act, no interval between paperwork and
news. There is no window there to be early to, by construction rather than by
bad luck.

## Two bugs found and fixed before reporting

**Position sizing was off equity, not cash — and it had been off cash.** Sizing
from uninvested cash makes the second concurrent position half the size of the
first (cash is already down by one position). Realised sizes ranged \$18.82 to
\$40.00 with a median of \$24.32, against a spec of two \$40 positions. Fixed to
size off account equity. This is why the reported loss moved from −0.5% to
−2.8%: the first run was accidentally risking about 40% less capital.

**The balance column reported idle cash rather than account value.** Correct at
the end, when everything is closed, and misleading at every intermediate row.

Both were mine, both were found by checking the output against the spec rather
than by the run failing.

## What this does not establish

Seventeen trades is not a test of anything. The mean of −0.31% per trade has a
standard error far larger than itself, and a month containing one biotech
surprise would flip the sign. This is an *illustration* of the mechanism, and
its value is in the `already moved` column and the skip table, not in the P&L.

The fill assumption is deliberately pessimistic: bought at the entry minute's
high, sold at the exit minute's low — the worst prices that actually printed.
At \$40 there is no market impact at all, so the spread is the entire cost, and
filling at the midpoint would assume away the only thing that matters at this
size.

"""Staged, shardable bulk fetcher for Colab (or any set of independent machines).

Read this before choosing how to run it
=======================================
The fetch used to be one thing -- "get everything for these tickers" -- and it
was dominated by a single step. Form 4 documents were 99% of the request budget
and everything else was rounding error, so the only lever was more machines.

Fetching Form 4 from the SEC's quarterly bulk archives removed that step almost
entirely (~895,000 requests to 46, see :mod:`iai.sources.insiders_bulk`), and
what is left has a different shape. Some steps are per-ticker and shard well;
one is per-quarter and sharding it is *pure duplication*, because every shard
would download the same 46 archives and parse all of them. Splitting the run
into named stages makes that structural rather than a footnote.

Stages
------
=============  ==================  ==========  ===================================
stage          scales with         shardable   ~wall clock, 2,000 names, 2015-2026
=============  ==================  ==========  ===================================
``candidates``  quarters (46)       no          ~2 min
``prices``      candidates (~6k)    **yes**     ~50 min / n_shards
``screen``      local              no          ~1 min
``events``      universe (~2k)      **yes**     ~8 min / n_shards
``insiders``    quarters (46)       **no**      ~2 min
``merge``       local              no          ~1 min
=============  ==================  ==========  ===================================

One machine end to end is about an hour. Four machines is about twenty minutes,
and the gain comes entirely from the two per-ticker stages -- running
``insiders`` on four machines would take exactly as long as running it on one
and download four times as much.

Where the remaining time goes
-----------------------------
**Prices, and it is not the SEC's fault.** Yahoo's undocumented limit is
stricter than the SEC's published 10 req/s and it answers abuse with blocks
rather than 429s, so this stage runs at 2 req/s by choice. It is the reason
``prices`` is worth sharding and the reason the candidate pool is screened down
before the ``events`` stage rather than after.

Why the universe is not pre-filtered harder
-------------------------------------------
It is tempting to shrink the candidate pool before the price fetch -- rank names
by filing activity, keep the top 2,000, save half an hour. Every such ranking is
computed over the whole window and therefore picks the 2015 universe using facts
from 2026. The ``screen`` stage cuts the pool using a trailing cap-and-liquidity
screen instead, which is knowable on the day it is applied. The extra price
requests are what that costs.

Rate limits
-----------
**The SEC's ~10 req/s is enforced per IP.** Threads on one machine hide latency
but cannot exceed it; cores do nothing for the download and a lot for the
parsing; separate machines are the only real multiplier because each has its own
address. Do not run several shards in one notebook -- they share the IP, and the
SEC answers with a 403 on the whole address, which is a block and not a throttle.

Colab quickstart
----------------
.. code-block:: python

    !pip -q install git+https://github.com/nikku03/integratedai@claude/trading-ml-model-design-p5ux05
    !pip -q install lightgbm pyarrow

    from google.colab import drive; drive.mount('/content/drive')
    OUT = '/content/drive/MyDrive/iai_shards'
    UA  = "your-name your@email.com"

    # once, on any one machine
    !python -m scripts.colab_fetch --stage candidates --out $OUT --user-agent "$UA"

    # then on machine i of 4, all four at the same time
    !python -m scripts.colab_fetch --stage prices --shard 0 --n-shards 4 \
        --start 2015-01-01 --end 2026-01-01 --out $OUT --user-agent "$UA"

    # once all four finish, on any one machine
    !python -m scripts.colab_fetch --stage screen --out $OUT --user-agent "$UA"

    # then shard again for filings, and run insiders on ONE machine only
    !python -m scripts.colab_fetch --stage events --shard 0 --n-shards 4 ...
    !python -m scripts.colab_fetch --stage insiders --out $OUT --user-agent "$UA"
    !python -m scripts.colab_fetch --stage merge --out $OUT --user-agent "$UA"

**Set a real ``--user-agent``.** The SEC requires a contact address and blocks
anonymous scrapers outright. A blocked IP is a blocked Colab session.
"""

from __future__ import annotations

import argparse
import ast
import logging
import os
import sys
import time
from pathlib import Path

import pandas as pd

log = logging.getLogger("colab_fetch")

# SEC's published ceiling. Do not raise this. Exceeding it earns a 403 on the
# whole IP, which is a block rather than a throttle and does not clear quickly.
SEC_RATE_LIMIT = 9.0

CANDIDATES = "candidates.txt"
UNIVERSE = "universe.txt"
MEMBERS = "members.parquet"
CAP_PANEL = "cap_panel.parquet"


def shard_tickers(tickers: list[str], shard: int, n_shards: int) -> list[str]:
    """Deterministic, contiguous-free slicing.

    Round-robin rather than contiguous blocks: alphabetical blocks correlate
    with listing venue and sector, so a contiguous split would give one shard
    all the biotechs and another all the banks, and their runtimes would differ
    by hours.
    """
    if n_shards <= 1:
        return sorted(tickers)
    return [t for i, t in enumerate(sorted(tickers)) if i % n_shards == shard]


def _setup(args):
    """Config, HTTP client and the full SEC ticker map. Shared by every stage."""
    from iai.core.config import Config
    from iai.core.http import HttpClient
    from iai.core.universe import Universe

    cfg = Config.moonshot()
    cfg.data.user_agent = args.user_agent
    cfg.features.min_adv_usd = args.min_adv
    cfg.ensure_dirs()

    client = HttpClient(
        cfg.data.cache_dir, cfg.data.user_agent,
        rate_per_sec=SEC_RATE_LIMIT, ttl_hours=args.cache_hours, max_retries=6,
    )
    return cfg, client, Universe.from_sec(client)


def _read_list(path: Path) -> list[str]:
    if not path.exists():
        raise SystemExit(
            f"ERROR: {path} not found. Run the earlier stage first "
            f"(candidates -> prices -> screen -> events/insiders -> merge)."
        )
    return [ln.strip().upper() for ln in path.read_text().splitlines() if ln.strip()]


# --------------------------------------------------------------------- stages


def stage_candidates(args, out_dir: Path) -> int:
    """Every SEC registrant that filed a cover-page share count in the window.

    One request per quarter returns all ~2,700 filers for that quarter, so the
    whole pool costs 46 requests. Cheap enough that it is not worth sharding
    and not worth caching by hand -- the HTTP layer already does.
    """
    from iai.universe_builder import operating_issuers, quarter_frames

    _, client, full = _setup(args)
    periods = quarter_frames(args.start, args.end)
    pool = operating_issuers(client, full, periods)
    if pool.empty:
        log.error("no candidates; check the user agent and the date range")
        return 1

    (out_dir / CANDIDATES).write_text("\n".join(sorted(pool["ticker"])) + "\n")
    pool.to_parquet(out_dir / "candidate_pool.parquet")
    log.info("candidates: %d issuers -> %s", len(pool), out_dir / CANDIDATES)
    return 0


def stage_prices(args, out_dir: Path) -> int:
    from iai.sources.prices import YahooPrices, add_derived

    cfg, _, full = _setup(args)
    pool = _read_list(out_dir / CANDIDATES)
    mine = shard_tickers(pool, args.shard, args.n_shards)
    tag = f"shard{args.shard:02d}of{args.n_shards:02d}"
    log.info("%s: %d of %d candidates", tag, len(mine), len(pool))

    # Yahoo, not the SEC, so it gets its own client with its own (stricter) limit.
    from iai.core.http import HttpClient
    px_client = HttpClient(
        cfg.data.cache_dir, cfg.data.user_agent,
        rate_per_sec=args.yahoo_rate, ttl_hours=args.cache_hours, max_retries=6,
    )
    t0 = time.time()
    prices = YahooPrices(cfg, px_client, workers=args.workers).fetch(
        full.subset(mine).tickers, pd.Timestamp(args.start), pd.Timestamp(args.end)
    )
    if prices.empty:
        log.error("%s: no prices returned; aborting", tag)
        return 1
    prices = add_derived(prices, cfg)
    prices.to_parquet(out_dir / f"prices_{tag}.parquet")
    log.info("%s: %d bars, %d tickers (%.1f min)",
             tag, len(prices), prices["ticker"].nunique(), (time.time() - t0) / 60)
    return 0


def stage_screen(args, out_dir: Path) -> int:
    """Cut the candidate pool to the traded universe, point-in-time."""
    from iai.universe_builder import (
        MICRO_CAP,
        build_smallmid_universe,
        quarter_frames,
        rolling_universe,
    )

    _, client, full = _setup(args)
    price_files = sorted(out_dir.glob("prices_shard*.parquet"))
    if not price_files:
        raise SystemExit("ERROR: no prices_shard*.parquet found; run --stage prices first.")
    prices = pd.concat([pd.read_parquet(f) for f in price_files], ignore_index=True)
    prices = prices.drop_duplicates(subset=["date", "ticker"])
    log.info("screening %d tickers, %d bars", prices["ticker"].nunique(), len(prices))

    _, panel = build_smallmid_universe(
        client, full, prices,
        min_cap=args.min_cap, max_cap=args.max_cap,
        min_adv_usd=args.min_adv, min_price=args.min_price,
        periods=quarter_frames(args.start, args.end),
    )
    if panel.empty:
        log.error("empty cap panel; cannot screen")
        return 1

    members = rolling_universe(
        panel, max_names=args.max_names, min_cap=args.min_cap, max_cap=args.max_cap
    )
    if members.empty:
        log.error("no names passed the screen")
        return 1

    tickers = sorted(members["ticker"].unique())
    (out_dir / UNIVERSE).write_text("\n".join(tickers) + "\n")
    members.to_parquet(out_dir / MEMBERS)
    panel.to_parquet(out_dir / CAP_PANEL)

    per_q = members.groupby("period", observed=True)["ticker"].nunique()
    log.info("universe: %d distinct names, %d-%d per quarter -> %s",
             len(tickers), per_q.min(), per_q.max(), out_dir / UNIVERSE)
    if args.min_cap <= MICRO_CAP:
        log.info("cap floor is at or below the micro-cap line; expect thin names")
    return 0


def stage_events(args, out_dir: Path) -> int:
    """Per-issuer EDGAR filing history. Shardable -- one request per CIK."""
    from iai.core.types import events_to_frame, validate_events
    from iai.sources.edgar import EdgarFilings

    cfg, client, full = _setup(args)
    uni_list = _read_list(out_dir / UNIVERSE)
    mine = shard_tickers(uni_list, args.shard, args.n_shards)
    tag = f"shard{args.shard:02d}of{args.n_shards:02d}"
    log.info("%s: edgar for %d of %d universe names", tag, len(mine), len(uni_list))

    t0 = time.time()
    events = EdgarFilings(cfg, client, full.subset(mine), workers=args.workers).fetch(
        pd.Timestamp(args.start, tz="UTC"), pd.Timestamp(args.end, tz="UTC")
    )
    ev = validate_events(events_to_frame(events))
    ev.assign(payload=ev["payload"].map(repr)).to_parquet(out_dir / f"edgar_{tag}.parquet")
    log.info("%s: edgar %d events (%.1f min)", tag, len(ev), (time.time() - t0) / 60)
    return 0


def stage_insiders(args, out_dir: Path) -> int:
    """Form 4 from the quarterly bulk archives. Run this on ONE machine.

    Sharding by ticker would make every shard download and parse all 46
    archives to keep its own slice -- n times the bytes for none of the speed.
    The parallelism that helps here is inside :func:`load_quarters`, which
    overlaps the downloads with parsing on separate cores.
    """
    from iai.core.types import events_to_frame, validate_events
    from iai.sources.insiders_bulk import BulkInsiderTransactions

    cfg, client, full = _setup(args)
    uni_list = _read_list(out_dir / UNIVERSE)
    if args.n_shards > 1:
        log.warning(
            "--stage insiders ignores sharding: every shard would fetch all "
            "%d archives. Running the whole universe here.", 4 * (int(args.end[:4]) - int(args.start[:4]) + 1)
        )

    t0 = time.time()
    src = BulkInsiderTransactions(cfg, client, full.subset(uni_list), processes=args.processes)
    events = src.fetch(pd.Timestamp(args.start, tz="UTC"), pd.Timestamp(args.end, tz="UTC"))
    iev = validate_events(events_to_frame(events))
    iev.assign(payload=iev["payload"].map(repr)).to_parquet(out_dir / "insiders_bulk.parquet")
    log.info("insiders: %d events (%.1f min)", len(iev), (time.time() - t0) / 60)
    return 0


def stage_merge(args, out_dir: Path) -> int:
    out = merge_shards(out_dir, args.prefix)
    for k, v in out.items():
        print(f"{k}: {len(v):,} rows")
    return 0


def merge_shards(out_dir: str | Path, prefix: str = "wide") -> dict[str, pd.DataFrame]:
    """Combine stage outputs into the files the analysis scripts expect.

    Deduplicates on the event ``uid`` and on ``(date, ticker)`` for prices, so a
    re-run shard, an overlapping ticker list, or a stage run twice cannot
    double-count.
    """
    out_dir = Path(out_dir)
    result: dict[str, pd.DataFrame] = {}

    price_files = sorted(out_dir.glob("prices_shard*.parquet"))
    if price_files:
        prices = pd.concat([pd.read_parquet(f) for f in price_files], ignore_index=True)
        # Keep only names that survived the screen, if it has been run.
        uni_path = out_dir / UNIVERSE
        if uni_path.exists():
            keep = set(_read_list(uni_path))
            prices = prices[prices["ticker"].isin(keep)]
        prices = prices.drop_duplicates(subset=["date", "ticker"]).sort_values(["ticker", "date"])
        prices.to_parquet(out_dir / f"{prefix}_prices.parquet")
        result["prices"] = prices

    frames = []
    for pattern in ("edgar_shard*.parquet", "insiders_bulk.parquet", "insiders_shard*.parquet"):
        for f in sorted(out_dir.glob(pattern)):
            df = pd.read_parquet(f)
            df["payload"] = df["payload"].map(
                lambda s: ast.literal_eval(s) if isinstance(s, str) else s
            )
            frames.append(df)
    if frames:
        events = pd.concat(frames, ignore_index=True).drop_duplicates(subset="uid")
        events = events.sort_values("available_ts").reset_index(drop=True)
        events.assign(payload=events["payload"].map(repr)).to_parquet(
            out_dir / f"{prefix}_events.parquet"
        )
        result["events"] = events

    for name, key in ((MEMBERS, "members"), (CAP_PANEL, "cap_panel")):
        if (out_dir / name).exists():
            result[key] = pd.read_parquet(out_dir / name)
    return result


STAGES = {
    "candidates": stage_candidates,
    "prices": stage_prices,
    "screen": stage_screen,
    "events": stage_events,
    "insiders": stage_insiders,
    "merge": stage_merge,
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--stage", choices=sorted(STAGES), required=True)
    ap.add_argument("--shard", type=int, default=0, help="this machine's index, 0-based")
    ap.add_argument("--n-shards", type=int, default=1, help="how many machines in total")
    ap.add_argument("--out", default="./iai_shards", help="output directory (mount Drive first)")
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--end", default="2026-01-01")
    ap.add_argument("--workers", type=int, default=8,
                    help="download threads; past ~8 you queue against the rate limit")
    ap.add_argument("--processes", type=int, default=None,
                    help="parse processes for bulk archives; 0 parses inline")
    ap.add_argument("--yahoo-rate", type=float, default=2.0,
                    help="Yahoo requests/sec; it throttles harder than the SEC and 429s")
    ap.add_argument("--max-names", type=int, default=2000,
                    help="per-quarter universe cap, filled by trailing dollar volume")
    ap.add_argument("--min-cap", type=float, default=50_000_000.0)
    ap.add_argument("--max-cap", type=float, default=10_000_000_000.0)
    ap.add_argument("--min-price", type=float, default=2.0)
    ap.add_argument("--min-adv", type=float, default=500_000.0)
    ap.add_argument("--cache-hours", type=float, default=720.0)
    ap.add_argument("--user-agent", default=os.environ.get("IAI_USER_AGENT", ""),
                    help="REQUIRED by the SEC: 'your name your@email.com'")
    ap.add_argument("--prefix", default="wide")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S", stream=sys.stderr,
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    if not args.user_agent or "@" not in args.user_agent:
        print("ERROR: --user-agent must be a real contact, e.g. 'Jane Doe jane@example.com'.\n"
              "The SEC blocks anonymous scrapers and the block applies to the whole IP.",
              file=sys.stderr)
        return 2
    if args.shard >= args.n_shards:
        print(f"ERROR: --shard {args.shard} is out of range for --n-shards {args.n_shards}",
              file=sys.stderr)
        return 2

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    return STAGES[args.stage](args, out_dir)


if __name__ == "__main__":
    raise SystemExit(main())

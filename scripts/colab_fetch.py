"""Shardable bulk fetcher, built for Colab (or any set of independent machines).

Read this before choosing how many workers to run
-------------------------------------------------
**The bottleneck is the SEC's ~10 requests/second, and it is enforced per IP.**

That single fact determines the whole design:

* Adding *threads* on one machine hides network latency but cannot exceed
  10 req/s. Past about 8 threads you are queueing, not accelerating.
* Adding *cores* on one machine does nothing for the download at all. It does
  help the XML parsing, which is genuinely CPU-bound -- roughly 40% of wall
  clock once the network is saturated.
* Adding *machines* is the only thing that multiplies throughput, because each
  Colab session, each VM, each home connection is a separate IP with its own
  10 req/s budget.

So: run `--n-shards N` across N independent Colab notebooks. Each takes a
disjoint slice of tickers, respects the rate limit on its own, and writes its
own parquet files. Merge afterwards with `merge_shards()`.

Do not run several shards inside one notebook expecting a speed-up. They will
share the IP and the SEC will start returning 403s, which is a block, not a
throttle -- it does not clear quickly and it applies to the whole address.

Rough timings, measured
-----------------------
The 341-name / 4-year fetch used here ran 55,548 Form 4 documents in about
70 minutes on one IP. Scaling from that:

===================  ==========  ==============  =====================
universe             years       ~documents      one IP / 6 shards
===================  ==========  ==============  =====================
341 names            2021-2024   56k             1.2 h  /  12 min
1,000 names          2021-2024   165k            3.5 h  /  35 min
2,000 names          2015-2024   730k            20 h   /  3.4 h
===================  ==========  ==============  =====================

Colab quickstart
----------------
.. code-block:: python

    !pip -q install git+https://github.com/nikku03/integratedai@claude/trading-ml-model-design-p5ux05
    !pip -q install lightgbm pyarrow

    from google.colab import drive; drive.mount('/content/drive')
    OUT = '/content/drive/MyDrive/iai_shards'

    # In notebook 0 of 6:
    !python -m iai.scripts.colab_fetch --shard 0 --n-shards 6 \
        --start 2015-01-01 --end 2024-12-31 --out $OUT \
        --user-agent "your-name your@email.com"

Change ``--shard`` in each notebook. Everything else stays identical.

**Set a real ``--user-agent``.** The SEC requires a contact address and blocks
anonymous scrapers outright. A blocked IP is a blocked Colab session.
"""

from __future__ import annotations

import argparse
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


def _parse_batch(payloads: list[tuple[str, str, str, str]]) -> list[dict]:
    """Parse a batch of Form 4 XML bodies in a worker process.

    Parsing is the CPU-bound half of this job and Python's GIL makes threads
    useless for it, so it runs in processes while the download runs in threads.
    """
    from iai.sources.insiders import parse_form4

    out = []
    for ticker, url, body, accepted in payloads:
        try:
            trades = parse_form4(body, pd.Timestamp(accepted), url.rsplit("/", 2)[-2])
        except Exception:  # noqa: BLE001 - one malformed filing must not kill the batch
            continue
        for t in trades:
            out.append({
                "ticker": ticker, "cik": t.cik, "owner": t.owner, "owner_cik": t.owner_cik,
                "role": t.role, "code": t.code, "shares": t.shares, "price": t.price,
                "transaction_date": t.transaction_date, "accepted_ts": t.accepted_ts,
                "accession": t.accession,
            })
    return out


def run_shard(args) -> int:
    from iai.core.config import Config
    from iai.core.http import HttpClient
    from iai.core.types import events_to_frame, validate_events
    from iai.core.universe import Universe
    from iai.seeds import SMALLMID_CORE, SMALLMID_SEED
    from iai.sources.edgar import EdgarFilings
    from iai.sources.insiders_bulk import BulkInsiderTransactions
    from iai.sources.prices import YahooPrices, add_derived

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"shard{args.shard:02d}of{args.n_shards:02d}"

    cfg = Config.moonshot()
    cfg.data.user_agent = args.user_agent
    cfg.features.min_adv_usd = args.min_adv
    cfg.ensure_dirs()

    client = HttpClient(
        cfg.data.cache_dir, cfg.data.user_agent,
        rate_per_sec=SEC_RATE_LIMIT, ttl_hours=args.cache_hours, max_retries=6,
    )

    full = Universe.from_sec(client)
    if args.tickers:
        pool = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    elif args.all_sec:
        # Everything the SEC knows about. The cap and liquidity screens run
        # later; this is the widest possible candidate pool.
        pool = full.tickers
    else:
        pool = SMALLMID_SEED if args.wide else SMALLMID_CORE

    mine = shard_tickers(pool, args.shard, args.n_shards)
    log.info("%s: %d of %d candidate tickers", tag, len(mine), len(pool))
    uni = full.subset(mine)

    t0 = time.time()

    # ---- prices ------------------------------------------------------------
    # Yahoo, not the SEC, so it has its own (undocumented, stricter) limit.
    px_client = HttpClient(
        cfg.data.cache_dir, cfg.data.user_agent,
        rate_per_sec=args.yahoo_rate, ttl_hours=args.cache_hours, max_retries=6,
    )
    prices = YahooPrices(cfg, px_client).fetch(
        uni.tickers, pd.Timestamp(args.start), pd.Timestamp(args.end)
    )
    if prices.empty:
        log.error("%s: no prices returned; aborting shard", tag)
        return 1
    prices = add_derived(prices, cfg)
    prices.to_parquet(out_dir / f"prices_{tag}.parquet")
    log.info("%s: prices %d bars, %d tickers (%.1f min)",
             tag, len(prices), prices["ticker"].nunique(), (time.time() - t0) / 60)

    live = uni.subset(sorted(prices["ticker"].unique()))

    # ---- EDGAR filings -----------------------------------------------------
    edgar = EdgarFilings(cfg, client, live).fetch(
        pd.Timestamp(args.start, tz="UTC"), pd.Timestamp(args.end, tz="UTC")
    )
    ev = validate_events(events_to_frame(edgar))
    ev.assign(payload=ev["payload"].map(repr)).to_parquet(out_dir / f"edgar_{tag}.parquet")
    log.info("%s: edgar %d events (%.1f min)", tag, len(ev), (time.time() - t0) / 60)

    # ---- Form 4 ------------------------------------------------------------
    src = BulkInsiderTransactions(cfg, client, live)
    insider_events = src.fetch(
        pd.Timestamp(args.start, tz="UTC"), pd.Timestamp(args.end, tz="UTC")
    )
    iev = validate_events(events_to_frame(insider_events))
    iev.assign(payload=iev["payload"].map(repr)).to_parquet(out_dir / f"insiders_{tag}.parquet")
    log.info("%s: insiders %d events (%.1f min)", tag, len(iev), (time.time() - t0) / 60)

    pd.DataFrame([{
        "shard": args.shard, "n_shards": args.n_shards,
        "tickers_requested": len(mine), "tickers_with_prices": prices["ticker"].nunique(),
        "price_bars": len(prices), "edgar_events": len(ev), "insider_events": len(iev),
        "start": args.start, "end": args.end, "minutes": (time.time() - t0) / 60,
    }]).to_parquet(out_dir / f"manifest_{tag}.parquet")

    log.info("%s: COMPLETE in %.1f min -> %s", tag, (time.time() - t0) / 60, out_dir)
    return 0


def merge_shards(out_dir: str | Path, prefix: str = "wide") -> dict[str, pd.DataFrame]:
    """Combine shard outputs into the files the analysis scripts expect.

    Run once, after every shard has finished. Deduplicates on the event ``uid``
    so a shard re-run (or an overlapping ticker list) cannot double-count.
    """
    import ast

    out_dir = Path(out_dir)
    result: dict[str, pd.DataFrame] = {}

    price_files = sorted(out_dir.glob("prices_shard*.parquet"))
    if price_files:
        prices = pd.concat([pd.read_parquet(f) for f in price_files], ignore_index=True)
        prices = prices.drop_duplicates(subset=["date", "ticker"]).sort_values(["ticker", "date"])
        prices.to_parquet(out_dir / f"{prefix}_prices.parquet")
        result["prices"] = prices

    frames = []
    for pattern in ("edgar_shard*.parquet", "insiders_shard*.parquet"):
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

    manifests = sorted(out_dir.glob("manifest_shard*.parquet"))
    if manifests:
        result["manifest"] = pd.concat(
            [pd.read_parquet(f) for f in manifests], ignore_index=True
        )
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--shard", type=int, default=0, help="this machine's index, 0-based")
    ap.add_argument("--n-shards", type=int, default=1, help="how many machines in total")
    ap.add_argument("--out", default="./iai_shards", help="output directory (mount Drive first)")
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--workers", type=int, default=8,
                    help="download threads; past ~8 you queue against the rate limit")
    ap.add_argument("--yahoo-rate", type=float, default=2.0,
                    help="Yahoo requests/sec; it throttles harder than the SEC and 429s")
    ap.add_argument("--min-adv", type=float, default=500_000.0)
    ap.add_argument("--cache-hours", type=float, default=720.0)
    ap.add_argument("--user-agent", default=os.environ.get("IAI_USER_AGENT", ""),
                    help="REQUIRED by the SEC: 'your name your@email.com'")
    ap.add_argument("--wide", action="store_true", help="~480-name seed pool")
    ap.add_argument("--all-sec", action="store_true",
                    help="every SEC-registered ticker (~10,400); screens apply later")
    ap.add_argument("--tickers", help="explicit comma-separated list, overrides the pools")
    ap.add_argument("--merge", action="store_true", help="merge finished shards and exit")
    ap.add_argument("--prefix", default="wide")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S", stream=sys.stderr,
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    if args.merge:
        out = merge_shards(args.out, args.prefix)
        for k, v in out.items():
            print(f"{k}: {len(v):,} rows")
        if "manifest" in out:
            print(out["manifest"].to_string(index=False))
        return 0

    if not args.user_agent or "@" not in args.user_agent:
        print("ERROR: --user-agent must be a real contact, e.g. 'Jane Doe jane@example.com'.\n"
              "The SEC blocks anonymous scrapers and the block applies to the whole IP.",
              file=sys.stderr)
        return 2
    if args.shard >= args.n_shards:
        print(f"ERROR: --shard {args.shard} is out of range for --n-shards {args.n_shards}",
              file=sys.stderr)
        return 2

    return run_shard(args)


if __name__ == "__main__":
    raise SystemExit(main())

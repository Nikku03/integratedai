"""Real-data run: small/mid-cap short-horizon catalyst study.

Usage:
    python scripts/run_smallmid.py --start 2021-01-01 --end 2024-12-31 --max-names 120

Writes prices/events/caps to the store so the expensive fetch is done once.
"""

from __future__ import annotations

import argparse
import logging
import sys
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

from iai.core.config import Config  # noqa: E402
from iai.diagnostics import (  # noqa: E402
    coverage_report,
    event_study,
    event_study_summary,
    label_lift,
)
from iai.labels import build_labels  # noqa: E402
from iai.pipeline import fetch_smallmid  # noqa: E402

#: Seed list of liquid US small/mid caps across sectors where discrete
#: catalysts plausibly move price. Screening the full 10k-name SEC universe
#: would need ~10k price requests; this keeps the fetch tractable while staying
#: sector-diverse. The point-in-time cap screen then runs on top of it.
SEED = """
ARWR SRPT IONS BLUE FOLD RARE AXSM HALO PTCT ACAD SAGE VKTX MDGL DVAX ARDX
CRSP NTLA BEAM EDIT VCYT EXAS PACB TWST CDNA NVAX OCGN INO VXRT ATRA
IRWD AMPH COLL SUPN HRMY ANIP PCRX EOLS EVH OMCL
ON WOLF MPWR SLAB LSCC AMBA SITM ALGM POWI DIOD SMTC MTSI FORM ACLS UCTT
COHU ONTO AEIS ICHR AOSL SGH PLAB VECO
X CLF AA MP UEC CCJ DNN NXE SMR CDE HL AG EXK PAAS SSRM
ENPH SEDG RUN NOVA ARRY SHLS CSIQ JKS MAXN AMRC
PLUG BE FCEL BLDP CHPT BLNK EVGO WKHS RIDE GOEV NKLA HYLN
CALX EXTR NTGR DGII INFN AAOI LITE VIAV
SKYW ALGT JBLU SAVE MESA
SM MTDR CIVI CRC BRY REPX AMPY VTLE
CVI PARR DINO ALTO GEVO REX
BGFV CATO SCVL DXLG ZUMZ CHUY PTLO NDLS
UPWK FVRR CARG CARS QNST YELP EVER
""".split()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--max-names", type=int, default=120)
    ap.add_argument("--min-cap", type=float, default=50e6)
    ap.add_argument("--max-cap", type=float, default=10e9)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--reuse", action="store_true", help="load from store instead of refetching")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)-24s %(message)s",
        datefmt="%H:%M:%S", stream=sys.stderr,
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    cfg = Config.short_horizon()
    cfg.data.user_agent = "integratedai research chhillarnaresh03@gmail.com"
    cfg.ensure_dirs()
    store = cfg.data.store_dir

    if args.reuse and (store / "sm_prices.parquet").exists():
        prices = pd.read_parquet(store / "sm_prices.parquet")
        events = pd.read_parquet(store / "sm_events.parquet")
        caps = pd.read_parquet(store / "sm_caps.parquet")
        events["payload"] = events["payload"].map(
            lambda s: __import__("ast").literal_eval(s) if isinstance(s, str) else s
        )
        print(f"reused: {len(prices):,} bars, {len(events):,} events", file=sys.stderr)
    else:
        prices, events, uni, caps = fetch_smallmid(
            cfg, args.start, args.end,
            seed_tickers=SEED, max_names=args.max_names,
            min_cap=args.min_cap, max_cap=args.max_cap,
            include_slow=False, workers=args.workers,
        )
        prices.to_parquet(store / "sm_prices.parquet")
        events.assign(payload=events["payload"].map(repr)).to_parquet(store / "sm_events.parquet")
        caps.to_parquet(store / "sm_caps.parquet")

    pd.set_option("display.width", 250)
    print("=" * 100)
    print(f"SMALL/MID-CAP REAL DATA  {args.start} .. {args.end}")
    print("=" * 100)
    print(f"tickers : {prices['ticker'].nunique()}")
    print(f"bars    : {len(prices):,}")
    print(f"events  : {len(events):,}")
    print()
    print("COVERAGE BY SOURCE")
    print(coverage_report(events, prices["ticker"].nunique()).to_string(index=False))
    print()

    if not caps.empty:
        band = caps.dropna(subset=["market_cap"]).groupby("cap_band", observed=True)["ticker"].nunique()
        print("CAP BANDS (point-in-time)")
        print(band.to_string())
        print()

    labels = build_labels(prices, cfg)
    print(f"LABELS: n={len(labels):,}  base_rate={labels['label'].mean():.3f}  "
          f"median_hold={labels['holding_days'].median():.0f}d")
    print()

    study = event_study(events, prices, cfg, min_events=40, post=cfg.labels.max_holding_days + 5)
    summ = event_study_summary(study)
    print(f"EVENT STUDY  ({len(summ)} kinds tested, post=+{cfg.labels.max_holding_days + 5}d)")
    print(summ[["kind", "n_events", "pre_car", "day0_car", "drift_car", "drift_t",
                "p_raw", "survives_fdr", "verdict"]].to_string(index=False))
    print()
    print(f"*** kinds surviving FDR: {int(summ['survives_fdr'].sum())} of {len(summ)} ***")
    print()

    lift = label_lift(events, labels, cfg, min_events=40)
    if not lift.empty:
        print("LABEL LIFT")
        print(lift.to_string(index=False))

    out = Path(store) / "smallmid_study.csv"
    summ.to_csv(out, index=False)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

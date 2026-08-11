"""Read the cached filings with a language model instead of regular expressions.

`RESULT_TEXT_VALUE.md` closed the regex arm: 27 hand-written patterns per filing
moved the walk-forward ranking by −0.217pp with a CI straddling zero, and a
text-only model reached the same separability as a price-only one, meaning the
two carried the *same* information. The patterns recovered what kind of filing
it was; the panel already knew that from the 8-K item codes.

`RESULT_LLM_PILOT.md` measured what a reader adds on 64 blind, anonymised
filings: 0.700 against 0.656 for the best hindsight-picked regex feature, a
paired gap of +0.043 with a CI from −0.066 to +0.150. Promising, undecided, and
only resolvable by extracting the whole corpus and running it through the same
evaluation the regex arm went through.

This is that extractor. It emits the same table shape as ``text_features.py`` —
one row per filing keyed by accession, every feature numeric — so
``merge_text_panel.py`` and ``text_value_test.py`` consume it unchanged and the
comparison stays like-for-like.

What it asks for, and why those things
--------------------------------------
Not a summary. Summaries are unfalsifiable and unrankable. It asks for the
specifics a pattern cannot reach and a trader would actually want: whether a
p-value was reported and whether it cleared significance, how many patients,
which trial phase, whether the endpoint named was primary and whether it was
met, how much money changes hands and in which direction, how imminent the
implied share issuance is, and how much of the language is claim rather than
result. Two summary judgements sit on top — expected move and news direction —
because on the pilot the composite outperformed every component except the
dilution read.

Cost, and why the batch path is the default
-------------------------------------------
The corpus is 7,601 filings, roughly 16M input tokens once clipped. The Batches
API halves the price and the job is not latency-sensitive, so batch is the
default and the synchronous path exists for small ``--limit`` runs while
iterating on the prompt. Everything is written to JSONL as it lands and keyed by
accession, so an interrupted run resumes without re-paying for finished work.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from filing_corpus import client, document, filing_table  # noqa: E402

MODEL = "claude-opus-5"
CHARS = 12000
BATCH_SIZE = 5000
MAX_TOKENS = 1600

#: Batch pricing is half of list. Input/output per million tokens.
PRICES = {"claude-opus-5": (5.0, 25.0), "claude-sonnet-5": (3.0, 15.0),
          "claude-haiku-4-5": (1.0, 5.0)}

SYSTEM = """\
You are reading SEC Form 8-K filings from small and micro-cap healthcare
companies and extracting structured facts for a quantitative model. You are not
writing a summary and no prose is wanted. Return only the JSON object.

Read the filing as an experienced biotech analyst would, then fill every field.
Rules that matter more than they look:

* Report what the document says, not what you know about the company. If the
  filing does not state a patient count, that field is 0. Inventing a plausible
  number is worse than a zero, because a zero is a fact the model can split on
  and a guess is noise it cannot detect.
* `p_value_reported` and `p_value_significant` are different. Many releases say
  "statistically significant" without a number; that is reported=0,
  significant=1. A stated p of 0.08 is reported=1, significant=0.
* `endpoint_met` describes the endpoint the filing leads with. -1 missed, 0 not
  applicable or not stated, 1 met.
* `dilution_imminence` is about supply of stock arriving, not about whether
  raising money is wise. An executed at-the-market facility, an equity line, a
  closed convertible or a priced offering is 3. An authorised but undrawn shelf
  is 1. A cash-funded milestone or a licence payment received is 0.
* `hype` measures claim exceeding evidence: superlatives, market-size language,
  and prominence given to preclinical or anecdotal results. A filing can be
  strongly positive and score 0 on hype if the claims are backed by data.
* `expected_move_pct` is your estimate of the signed percentage move in the
  stock over the following ten trading sessions, given this filing and nothing
  else. Use the full range. Most 8-Ks are administrative and deserve a number
  near zero; reserve anything past +/-15 for filings that genuinely reprice a
  company.
* `surprise` is how far the filing departs from what a holder already expected.
  A pre-announced closing is 0 no matter how large the number attached to it.

Answer for every field. Never return null.
"""

#: Every value numeric, because the consumer is a gradient-boosted tree on a
#: panel and because a number is checkable in a way a category string is not.
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["event_type", "expected_move_pct", "news_direction", "surprise",
                 "materiality", "trial_phase", "patient_n", "effect_size_reported",
                 "p_value_reported", "p_value_significant", "endpoint_met",
                 "primary_endpoint", "safety_concern", "regulatory_action",
                 "usd_amount", "money_in", "dilution_imminence", "share_count",
                 "partner_tier", "binding", "catalyst_days", "hype", "hedging",
                 "specificity", "going_concern"],
    "properties": {
        "event_type": {"type": "integer", "minimum": 0, "maximum": 13,
                       "description": "0 other, 1 clinical result, 2 regulatory "
                       "approval, 3 regulatory setback, 4 regulatory procedural, "
                       "5 M&A, 6 licence or partnership, 7 dilutive financing, "
                       "8 non-dilutive financing, 9 commercial or revenue, "
                       "10 earnings, 11 governance or personnel, 12 litigation, "
                       "13 listing or compliance"},
        "expected_move_pct": {"type": "number", "minimum": -90, "maximum": 300},
        "news_direction": {"type": "integer", "minimum": -2, "maximum": 2},
        "surprise": {"type": "integer", "minimum": 0, "maximum": 3},
        "materiality": {"type": "integer", "minimum": 0, "maximum": 3},
        "trial_phase": {"type": "integer", "minimum": 0, "maximum": 4,
                        "description": "0 none or preclinical, 4 phase 3 or "
                        "registrational"},
        "patient_n": {"type": "integer", "minimum": 0},
        "effect_size_reported": {"type": "integer", "minimum": 0, "maximum": 1},
        "p_value_reported": {"type": "integer", "minimum": 0, "maximum": 1},
        "p_value_significant": {"type": "integer", "minimum": 0, "maximum": 1},
        "endpoint_met": {"type": "integer", "minimum": -1, "maximum": 1},
        "primary_endpoint": {"type": "integer", "minimum": 0, "maximum": 1},
        "safety_concern": {"type": "integer", "minimum": 0, "maximum": 3},
        "regulatory_action": {"type": "integer", "minimum": -2, "maximum": 2,
                              "description": "-2 hold or CRL, -1 delay or "
                              "deficiency, 0 none, 1 designation or acceptance, "
                              "2 approval"},
        "usd_amount": {"type": "number", "minimum": 0,
                       "description": "largest dollar figure central to the "
                       "filing, in dollars, 0 if none"},
        "money_in": {"type": "integer", "minimum": -1, "maximum": 1,
                     "description": "1 company receives, -1 company pays, 0 neither"},
        "dilution_imminence": {"type": "integer", "minimum": 0, "maximum": 3},
        "share_count": {"type": "number", "minimum": 0,
                        "description": "shares being issued if stated, else 0"},
        "partner_tier": {"type": "integer", "minimum": 0, "maximum": 3,
                         "description": "0 none, 1 small private, 2 mid-cap or "
                         "academic, 3 large pharma or a household name"},
        "binding": {"type": "integer", "minimum": 0, "maximum": 1},
        "catalyst_days": {"type": "integer", "minimum": 0,
                          "description": "days until a dated future event the "
                          "filing names, 0 if none named"},
        "hype": {"type": "integer", "minimum": 0, "maximum": 3},
        "hedging": {"type": "integer", "minimum": 0, "maximum": 3},
        "specificity": {"type": "integer", "minimum": 0, "maximum": 3},
        "going_concern": {"type": "integer", "minimum": 0, "maximum": 1},
    },
}

FIELDS = list(SCHEMA["properties"])
JSON_BLOB = re.compile(r"\{.*\}", re.S)


def prompt_for(row, text: str) -> str:
    items = ", ".join(sorted(row["items"]))
    return (f"8-K items reported: {items}\n\n"
            f"--- filing text ---\n{text}\n--- end ---\n\n"
            f"Return the JSON object.")


def params_for(row, text: str, model: str, thinking: bool) -> dict:
    p = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        # The rubric is identical on every request and the filing text is not,
        # so the breakpoint goes after the system block. On Opus 5 the minimum
        # cacheable prefix is 512 tokens and the rubric clears that comfortably.
        "system": [{"type": "text", "text": SYSTEM,
                    "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": prompt_for(row, text)}],
        "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}},
    }
    if thinking:
        p["thinking"] = {"type": "adaptive"}
    return p


def parse_out(msg) -> dict | None:
    """Pull the object out of a response, whichever shape it came back in."""
    txt = ""
    for b in getattr(msg, "content", []) or []:
        if getattr(b, "type", "") == "text":
            txt += b.text
    if not txt:
        return None
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        m = JSON_BLOB.search(txt)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None


def coerce(d: dict) -> dict:
    """Numbers only, missing fields zeroed, so the panel merge cannot fail."""
    out = {}
    for f in FIELDS:
        v = d.get(f, 0)
        try:
            out[f] = float(v)
        except (TypeError, ValueError):
            out[f] = 0.0
    # Dollar and share counts span nine orders of magnitude; a tree splits far
    # better on the exponent than on the raw figure.
    out["log_usd"] = float(np.log10(out["usd_amount"])) if out["usd_amount"] > 0 else 0.0
    out["log_shares"] = float(np.log10(out["share_count"])) if out["share_count"] > 0 else 0.0
    del out["usd_amount"], out["share_count"]
    return out


def load_done(path: Path) -> dict:
    done = {}
    if path.exists():
        with path.open() as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("acc"):
                    done[r["acc"]] = r
    return done


def estimate(g: pd.DataFrame, texts: dict, model: str, thinking: bool) -> None:
    n = len(g)
    inp = sum(len(t) for t in texts.values()) / 4 + n * len(SYSTEM) / 4
    out = n * (900 if thinking else 320)
    pi, po = PRICES.get(model, PRICES[MODEL])
    cost = (inp / 1e6 * pi + out / 1e6 * po) * 0.5
    print(f"  {n:,} filings, ~{inp / 1e6:.1f}M input and ~{out / 1e6:.1f}M output "
          f"tokens\n  estimated batch cost on {model}: ${cost:,.0f} "
          f"(${cost * 2:,.0f} synchronous)")


def run_sync(cl, g, texts, out_path, model, thinking) -> int:
    n = 0
    with out_path.open("a") as fh:
        for _, r in g.iterrows():
            p = params_for(r, texts[r.acc], model, thinking)
            try:
                msg = cl.messages.create(**p)
            except Exception as e:                                # noqa: BLE001
                if "output_config" in str(e) or "format" in str(e):
                    p.pop("output_config")
                    msg = cl.messages.create(**p)
                else:
                    print(f"  {r.acc}: {type(e).__name__} {str(e)[:120]}")
                    continue
            d = parse_out(msg)
            if d is None:
                continue
            fh.write(json.dumps({"acc": r.acc, "ticker": r.ticker,
                                 "available_ts": str(r.available_ts),
                                 **coerce(d)}) + "\n")
            fh.flush()
            n += 1
            if n % 25 == 0:
                print(f"  {n}/{len(g)}", flush=True)
    return n


def run_batch(cl, g, texts, out_path, model, thinking, poll) -> int:
    total = 0
    recs = g.to_dict("records")
    meta = {r["acc"]: r for r in recs}
    for s in range(0, len(recs), BATCH_SIZE):
        chunk = recs[s:s + BATCH_SIZE]
        reqs = [{"custom_id": r["acc"],
                 "params": params_for(r, texts[r["acc"]], model, thinking)}
                for r in chunk]
        b = cl.messages.batches.create(requests=reqs)
        print(f"  batch {b.id} submitted with {len(reqs):,} requests", flush=True)
        while True:
            st = cl.messages.batches.retrieve(b.id)
            if st.processing_status == "ended":
                break
            c = st.request_counts
            print(f"    {st.processing_status}  succeeded {c.succeeded} "
                  f"errored {c.errored} processing {c.processing}", flush=True)
            time.sleep(poll)
        ok = 0
        with out_path.open("a") as fh:
            for res in cl.messages.batches.results(b.id):
                if res.result.type != "succeeded":
                    continue
                d = parse_out(res.result.message)
                if d is None:
                    continue
                r = meta[res.custom_id]
                fh.write(json.dumps({"acc": res.custom_id, "ticker": r["ticker"],
                                     "available_ts": str(r["available_ts"]),
                                     **coerce(d)}) + "\n")
                ok += 1
        total += ok
        print(f"  batch {b.id}: {ok:,} extracted", flush=True)
    return total


def to_parquet(jsonl: Path, out: Path) -> None:
    done = load_done(jsonl)
    if not done:
        print("nothing to write")
        return
    f = pd.DataFrame(list(done.values())).drop_duplicates("acc")
    for c in f.columns:
        if c not in ("acc", "ticker", "available_ts"):
            f[c] = pd.to_numeric(f[c], errors="coerce").astype(np.float32)
    f["available_ts"] = pd.to_datetime(f["available_ts"], utc=True, errors="coerce")
    f.to_parquet(out)
    print(f"wrote {out}  ({len(f):,} filings, "
          f"{len([c for c in f.columns if c not in ('acc', 'ticker', 'available_ts')])} "
          f"features, {f.ticker.nunique()} tickers)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--out", default=None, help="jsonl of raw extractions")
    ap.add_argument("--parquet", default=None, help="feature table for the merge")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--chars", type=int, default=CHARS)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sync", action="store_true", help="skip the Batches API")
    ap.add_argument("--no-thinking", action="store_true")
    ap.add_argument("--poll", type=int, default=60)
    ap.add_argument("--dry-run", action="store_true",
                    help="cost estimate and one rendered prompt, no API calls")
    ap.add_argument("--merge-only", action="store_true",
                    help="turn an existing jsonl into the feature table")
    args = ap.parse_args(argv)
    root = Path(args.root)
    jsonl = Path(args.out) if args.out else root / "llm_feats_bio.jsonl"
    parq = Path(args.parquet) if args.parquet else root / "llm_feats_bio.parquet"
    thinking = not args.no_thinking

    if args.merge_only:
        to_parquet(jsonl, parq)
        return 0

    known = pd.read_parquet(root / "text_feats_bio.parquet", columns=["acc"])
    g = filing_table(root, set(known.acc))
    done = load_done(jsonl)
    if done:
        print(f"{len(done):,} already extracted, resuming")
        g = g[~g.acc.isin(done)].reset_index(drop=True)
    if args.limit:
        g = g.head(args.limit)
    print(f"{len(g):,} filings to read", flush=True)
    if g.empty:
        to_parquet(jsonl, parq)
        return 0

    sec = client()
    texts = {}
    for i, r in g.iterrows():
        texts[r.acc] = document(sec, r, args.chars)
        if (i + 1) % 1000 == 0:
            print(f"  loaded {i + 1:,}", flush=True)
    g = g[g.acc.map(lambda a: len(texts.get(a, "")) > 300)].reset_index(drop=True)
    print(f"{len(g):,} with usable text")
    estimate(g, texts, args.model, thinking)

    if args.dry_run:
        r = g.iloc[0]
        print("\n--- system ---\n" + SYSTEM)
        print("--- user (first 1200 chars) ---")
        print(prompt_for(r, texts[r.acc])[:1200])
        return 0

    try:
        import anthropic
    except ImportError:
        print("\nthe anthropic SDK is not installed: pip install anthropic")
        return 1
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print("\nno ANTHROPIC_API_KEY in the environment; nothing was sent")
        return 1
    cl = anthropic.Anthropic()
    fn = run_sync if args.sync else run_batch
    kw = {} if args.sync else {"poll": args.poll}
    n = fn(cl, g, texts, jsonl, args.model, thinking, **kw)
    print(f"\nextracted {n:,} filings")
    to_parquet(jsonl, parq)
    return 0


if __name__ == "__main__":
    sys.exit(main())

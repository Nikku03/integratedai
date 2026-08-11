"""The cached filing corpus, cleaned enough for a language model to read.

`text_features.py` fetched 7,601 biotech 8-Ks and reduced each to 27 numbers by
regular expression. `RESULT_TEXT_VALUE.md` recorded the outcome: the ranking
difference was −0.217pp with a confidence interval straddling zero, and a
text-only model reached the same 0.5366 separability as a price-only one, which
means the two carried *the same* information rather than complementary
information. The regex captured what kind of filing it was; the panel already
knew that from the 8-K item codes.

What it never captured is the substance — effect sizes, p-values, patient
counts, which endpoint was hit, whether the language is specific or promotional.
Reading that needs a reader. This module is the shared front end for that: it
reconstructs the same filing list and hands back the document text, so both the
model-driven extractor and the blind pilot see exactly the same corpus and the
comparison against the regex arm stays like-for-like.

Nothing here touches the network in the normal case. The 8-Ks are already in the
on-disk HTTP cache from the regex pass, so a re-read is a local file read; the
client is constructed with a five-year TTL for that reason. A cache miss falls
back to a throttled fetch rather than failing.

Cleaning is deliberately conservative
-------------------------------------
Tag stripping leaves EDGAR's XBRL header, style fragments and entity noise in
front of the actual press release, and that junk is expensive: it is the first
thing a reader sees and it displaces real content inside any length budget. So
the header is cut at the first plausible start-of-document marker and the
remainder is de-noised — but no attempt is made to summarise or reorder, because
the point of the exercise is to test what a reader gets from the *document*.
"""

from __future__ import annotations

import ast
import html
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from text_features import EXHIBIT_ITEMS, fetch_text  # noqa: E402
from oos_clinical import BIO_SIC  # noqa: E402

#: A real address is required by the SEC even for a cache-only run, because a
#: miss falls through to a live request.
UA = "integratedai research chhillarnaresh03@gmail.com"

#: Where the readable part of an EDGAR document actually begins.
#:
#: An 8-K opens with an XBRL header, then a cover page — registrant name,
#: address, telephone, the four "check the appropriate box" provisions, the
#: registered-securities table — and only then the numbered item. That cover
#: page runs about eleven hundred characters and is identical across every
#: filing by the same company, so leaving it in front spends a fifth of a short
#: reading budget on the issuer's zip code. The first ``Item N.NN`` heading
#: after the check-box block is the real start; the alternatives are fallbacks
#: for filings that do not follow the usual layout.
ITEM_HEAD = re.compile(r"Item\s+\d\.\d\d", re.I)
COVER_END = re.compile(r"Check the appropriate box|Securities registered pursuant", re.I)
START = re.compile(
    r"(?:FOR\s+IMMEDIATE\s+RELEASE|PRESS\s+RELEASE|"
    r"UNITED\s+STATES\s+SECURITIES\s+AND\s+EXCHANGE)", re.I)

#: The signature block and the exhibit index close the 8-K body. Anything after
#: them is either the registrant's officer's name or a file-name list, and the
#: EX-99 press release that follows is appended separately by ``fetch_text``.
TAIL = re.compile(r"SIGNATURES?\s*\n?\s*Pursuant to the requirements", re.I)

#: The registrant's legal name sits immediately before this phrase on the cover
#: page of essentially every 8-K, which makes it the cheapest reliable way to
#: learn what to redact.
REGISTRANT = re.compile(r"\(\s*Exact name of (?:the )?[Rr]egistrant", re.I)

#: What ends the run-up to the name. The cover page prints the event date
#: directly before the legal name, so the last date-like token in the window is
#: the left edge. Without this the capture runs backwards into the header and
#: redaction blanks "September" and "2020" out of the body — which is not a
#: cosmetic problem, it removes the timeline from a clinical narrative.
NAME_LEFT = re.compile(r"\b(?:19|20)\d{2}\b|\d{1,2}\s*,|\breported\s*\)?\s*:?")

#: Words too generic to redact — striking them would blank half the document
#: and tell the reader nothing was hidden.
GENERIC = {"inc", "inc.", "corp", "corp.", "corporation", "company", "co",
           "co.", "ltd", "ltd.", "llc", "plc", "holdings", "group", "the",
           "and", "of", "sa", "nv", "ag", "limited", "incorporated", "n.v.",
           "s.a.", "pharmaceuticals", "pharmaceutical", "pharma", "therapeutics",
           "biosciences", "bioscience", "sciences", "science", "labs",
           "laboratories", "medical", "health", "healthcare", "technologies"}

#: Boilerplate that appears in nearly every biotech press release and carries no
#: information about this particular one. Dropping it is not summarising: these
#: are fixed legal blocks, identical across thousands of documents.
DROP = re.compile(
    r"(?:forward-looking statements? (?:within the meaning|are based)"
    r".{0,4000}?(?:Exchange Act of 1934,? as amended\.|except as required by law\.)"
    r"|safe harbor statement under the private securities litigation reform act"
    r".{0,4000}?\.)", re.I | re.S)

ENTITY = re.compile(r"&[a-z]+;|&#\d+;", re.I)
NOISE = re.compile(r"[^\x20-\x7e\n]+")
SPACES = re.compile(r"[ \t]{2,}")
BREAKS = re.compile(r"\n{3,}")


def registrant(text: str) -> str:
    """The filer's legal name as it appears on the cover page, or ``''``."""
    m = REGISTRANT.search(text[:20000])
    if not m:
        return ""
    win = text[max(0, m.start() - 140):m.start()]
    cut = 0
    for mm in NAME_LEFT.finditer(win):
        cut = mm.end()
    win = re.sub(r"[^A-Za-z0-9&.,'\- ]+", " ", win[cut:])
    name = re.sub(r"\s+", " ", win).strip(" ,.-")
    return name if 2 < len(name) <= 80 else ""


def _body_start(t: str) -> int:
    """Index of the first character worth reading."""
    cover = COVER_END.search(t[:12000])
    if cover:
        item = ITEM_HEAD.search(t, cover.end())
        if item and item.start() < 30000:
            return item.start()
    item = ITEM_HEAD.search(t[:12000])
    if item:
        return item.start()
    m = START.search(t[:20000])
    return m.start() if m and m.start() > 200 else 0


def clean(text: str, limit: int = 0) -> str:
    """Header-stripped, de-boilerplated document text."""
    t = html.unescape(text or "")
    t = ENTITY.sub(" ", t)
    t = t[_body_start(t):]
    tail = TAIL.search(t)
    if tail:
        # Keep whatever came after the signature: ``fetch_text`` appends the
        # EX-99 press release there and that is usually the substantive half.
        t = t[:tail.start()] + "\n\n" + t[tail.end():]
    t = DROP.sub(" ", t)
    t = NOISE.sub(" ", t)
    t = SPACES.sub(" ", t)
    t = BREAKS.sub("\n\n", t).strip()
    return t[:limit] if limit else t


def redact(text: str, ticker: str, name: str = "") -> str:
    """Blank the issuer's identity so a reader is judging the document, not the name.

    Only used for the blind pilot. A model that recognises "Sarepta, eteplirsen,
    2016" is answering from memory of the outcome, not from the filing, and the
    whole point of the pilot is to measure the second thing. Redaction is
    imperfect — drug names and trial acronyms survive — so the result is an
    upper bound on the leakage-free signal, and that caveat is reported.
    """
    out = text
    words = [w for w in re.split(r"[^A-Za-z0-9.]+", name or "")
             if len(w) > 2 and w.lower() not in GENERIC]
    for w in [ticker, *words]:
        if not w:
            continue
        out = re.sub(rf"\b{re.escape(w)}\b", "COMPANY", out, flags=re.I)
    if name:
        out = re.sub(re.escape(name), "COMPANY", out, flags=re.I)
    return re.sub(r"(?:COMPANY[ ,]*){2,}", "COMPANY ", out)


def filing_table(root: Path, accs: set[str] | None = None) -> pd.DataFrame:
    """The biotech 8-K list, one row per filing, in the same form the regex pass used.

    ``accs`` restricts to a known accession set — pass the index of
    ``text_feats_bio.parquet`` to guarantee the LLM arm and the regex arm read
    the identical documents rather than merely a similar sample.
    """
    d = pd.read_parquet(root / "edgar_shard00of01.parquet",
                        columns=["kind", "ticker", "available_ts", "payload"])
    d = d[d.kind.str.startswith("8-K")].copy()
    pl = d.payload.map(ast.literal_eval)
    d["acc"] = pl.map(lambda x: x.get("id"))
    d["cik"] = pl.map(lambda x: x.get("cik"))
    d["sic"] = pl.map(lambda x: str(x.get("sic", "")))
    d["url"] = pl.map(lambda x: x.get("url"))
    d["item"] = d.kind.str[4:]
    g = (d.groupby("acc")
           .agg(ticker=("ticker", "first"), cik=("cik", "first"),
                sic=("sic", "first"), url=("url", "first"),
                available_ts=("available_ts", "first"),
                items=("item", lambda s: set(s))).reset_index())
    g = g[g.sic.isin(BIO_SIC) & g.url.notna()]
    if accs is not None:
        g = g[g.acc.isin(accs)]
    return g.reset_index(drop=True)


def client(cache_dir: Path | None = None):
    from iai.core.config import Config
    from iai.core.http import HttpClient
    cfg = Config.load()
    return HttpClient(cache_dir or cfg.data.cache_dir, UA, rate_per_sec=9.0,
                      ttl_hours=24 * 365 * 5, max_retries=3)


def document(sec, row, limit: int = 0, anonymous: bool = False) -> str:
    """Cleaned text for one filing, primary document plus its EX-99 when relevant."""
    raw = fetch_text(sec, row)
    name = registrant(html.unescape(raw or "")) if anonymous else ""
    t = clean(raw)
    if anonymous:
        t = redact(t, str(row["ticker"]), name)
    return t[:limit] if limit else t


__all__ = ["EXHIBIT_ITEMS", "UA", "clean", "client", "document", "filing_table",
           "redact", "registrant"]

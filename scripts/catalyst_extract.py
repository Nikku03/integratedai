"""Structured catalyst extraction, and the two engines that consume it.

Replaces "largest dollar amount in the document" with a typed record per filing:

    {event_category, is_binding, transaction_value_usd, value_confidence,
     has_toxic_financing, toxic_signals}

**The extractor is pluggable and the default is deterministic.** The intended
implementation is a small LLM under a strict JSON schema, which is the only thing
that reliably separates "total bank deposits of $790M" from "a binding purchase
order worth $15M". No model is available in this container -- no Ollama, no SDK,
no GPU, no key -- so :func:`extract_rules` implements the same schema with
pattern matching over the standardised legal vocabulary filings actually use.
That is materially better than max-amount regex because it uses *structure*
(binding language, financing language, event type) rather than magnitude alone,
and materially worse than a model because it cannot read.

``extract`` dispatches on ``--extractor``; wiring a model in means implementing
one function with the same signature and return type.

Why binding-ness is the load-bearing field
------------------------------------------
The direction study found that item codes do not separate up-movers from
down-movers at all (4.1% vs 4.2% carry a bearish code). The hypothesis this tests
is that the separation is not in the *code* but in the *commitment*: a definitive
agreement, purchase order or FDA approval is money; a memorandum of understanding,
letter of intent or "non-binding indication of interest" is a press release. Item
codes cannot tell these apart because both file under 1.01 or 8.01.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CATEGORIES = ("COMMERCIAL_CONTRACT", "FDA_APPROVAL", "CLINICAL_RESULT",
              "MA_ACTIVITY", "DILUTION_OFFERING", "DEBT_SETTLEMENT",
              "EARNINGS", "ADMINISTRATIVE")

#: Language that commits the counterparty. Ordered strongest first.
BINDING = re.compile(
    r"definitive\s+agreement|purchase\s+order|firm\s+order|binding\s+"
    r"agreement|executed\s+(?:a\s+)?contract|awarded\s+(?:a\s+)?contract|"
    r"entered\s+into\s+(?:a\s+)?(?:definitive|binding|master|supply|"
    r"distribution)|signed\s+(?:a\s+)?definitive|task\s+order|"
    r"delivery\s+order|statement\s+of\s+work", re.I)

#: Language that commits nobody.
NONBINDING = re.compile(
    r"memorandum\s+of\s+understanding|\bMOU\b|letter\s+of\s+intent|\bLOI\b|"
    r"non-?binding|indication\s+of\s+interest|term\s+sheet|"
    r"preliminary\s+(?:discussions|agreement)|intends?\s+to\s+enter|"
    r"expects?\s+to\s+(?:sign|enter)|framework\s+agreement|"
    r"strategic\s+partnership\s+to\s+explore|no\s+assurance\s+that", re.I)

#: Financing structures that dilute, in the vocabulary filings use for them.
TOXIC = {
    "atm": re.compile(r"at-?the-?market\s+(?:offering|program|facility)|\bATM\s+"
                      r"(?:offering|program|facility)", re.I),
    "equity_line": re.compile(r"equity\s+line|committed\s+equity\s+facility|"
                              r"standby\s+equity|purchase\s+agreement\s+with\s+"
                              r"(?:Lincoln|Tumim|White\s+Lion|Keystone)", re.I),
    "convertible": re.compile(r"convertible\s+(?:note|debenture|preferred)|"
                              r"original\s+issue\s+discount|\bOID\b", re.I),
    "warrant_reprice": re.compile(r"warrant\s+(?:re-?pric|inducement|exercise\s+"
                                  r"price\s+reduc|amendment)|reduce[d]?\s+the\s+"
                                  r"exercise\s+price|repriced", re.I),
    "ratchet": re.compile(r"full\s+ratchet|anti-?dilution\s+adjust|price\s+"
                          r"protection|reset\s+(?:price|provision)", re.I),
    "shelf": re.compile(r"shelf\s+registration|Form\s+S-3\s+registration|"
                        r"universal\s+shelf", re.I),
    "going_concern": re.compile(r"substantial\s+doubt|going\s+concern", re.I),
    "reverse_split": re.compile(r"reverse\s+(?:stock\s+)?split", re.I),
}

CATEGORY_PATTERNS = [
    ("FDA_APPROVAL", re.compile(
        r"FDA\s+(?:has\s+)?approv|marketing\s+authorization|510\(k\)\s+clear|"
        r"premarket\s+approval|breakthrough\s+therapy|orphan\s+drug|"
        r"accelerated\s+approval|\bPMA\b\s+approv|CE\s+mark", re.I)),
    ("CLINICAL_RESULT", re.compile(
        r"topline\s+(?:data|results)|primary\s+endpoint|phase\s+(?:1|2|3|I{1,3})"
        r"\s+(?:trial|study|data|results)|met\s+the\s+primary|"
        r"statistically\s+significant", re.I)),
    ("MA_ACTIVITY", re.compile(
        r"merger\s+agreement|to\s+be\s+acquired|acquisition\s+of\s+all|"
        r"tender\s+offer|business\s+combination|definitive\s+merger", re.I)),
    ("DILUTION_OFFERING", re.compile(
        r"public\s+offering|private\s+placement|registered\s+direct|"
        r"underwritten\s+offering|sale\s+of\s+(?:common\s+stock|securities)|"
        r"at-?the-?market", re.I)),
    ("DEBT_SETTLEMENT", re.compile(
        r"credit\s+(?:agreement|facility)|term\s+loan|refinanc|"
        r"note\s+purchase|indenture|debt\s+(?:restructur|exchange)", re.I)),
    ("COMMERCIAL_CONTRACT", re.compile(
        r"purchase\s+order|supply\s+agreement|distribution\s+agreement|"
        r"awarded\s+(?:a\s+)?contract|contract\s+(?:award|valued|worth)|"
        r"master\s+services|licensing\s+agreement|\bOEM\b", re.I)),
    ("EARNINGS", re.compile(
        r"reported\s+(?:financial\s+)?results|(?:first|second|third|fourth)\s+"
        r"quarter\s+(?:results|revenue)|fiscal\s+year\s+results|"
        r"earnings\s+per\s+share", re.I)),
]

#: Amounts qualified by transaction language, used when a category is known.
VALUE_NEAR = re.compile(
    r"(?:valued\s+at|worth|totall?ing|of\s+approximately|aggregate\s+of|"
    r"proceeds\s+of|contract\s+value|award(?:ed)?\s+(?:of|worth)|"
    r"purchase\s+price\s+of|consideration\s+of)\s*\$\s?([\d,]+(?:\.\d+)?)"
    r"\s*(thousand|million|billion)?", re.I)
MULT = {"thousand": 1e3, "million": 1e6, "billion": 1e9, None: 1.0, "": 1.0}


@dataclass
class Catalyst:
    event_category: str = "ADMINISTRATIVE"
    is_binding: bool = False
    transaction_value_usd: float | None = None
    value_confidence: str = "NONE"          # HIGH | MEDIUM | LOW | NONE
    has_toxic_financing: bool = False
    toxic_signals: list[str] = field(default_factory=list)

    def asdict(self) -> dict:
        return {"event_category": self.event_category,
                "is_binding": self.is_binding,
                "transaction_value_usd": self.transaction_value_usd,
                "value_confidence": self.value_confidence,
                "has_toxic_financing": self.has_toxic_financing,
                "toxic_signals": ",".join(self.toxic_signals)}


def extract_rules(text: str) -> Catalyst:
    """Deterministic stand-in for the LLM pass, same schema.

    Reads the first ~24k characters, which covers a press release and the head of
    an earnings table without letting a long financial-statement appendix
    dominate the pattern counts.
    """
    t = text[:24000]
    c = Catalyst()

    for name, rx in TOXIC.items():
        if rx.search(t):
            c.toxic_signals.append(name)
    c.has_toxic_financing = bool(c.toxic_signals)

    for cat, rx in CATEGORY_PATTERNS:
        if rx.search(t):
            c.event_category = cat
            break

    nb, b = NONBINDING.search(t), BINDING.search(t)
    # Non-binding language wins ties: a filing that says both "definitive
    # agreement" and "non-binding letter of intent" is describing the LOI.
    c.is_binding = bool(b) and not bool(nb)

    m = VALUE_NEAR.search(t)
    if m:
        try:
            c.transaction_value_usd = (float(m.group(1).replace(",", ""))
                                       * MULT.get((m.group(2) or "").lower(), 1.0))
            c.value_confidence = "HIGH"
        except (ValueError, KeyError):
            pass
    return c


def extract(text: str, backend: str = "rules") -> Catalyst:
    if backend == "rules":
        return extract_rules(text)
    raise NotImplementedError(
        f"extractor backend {backend!r} is not wired up. Implement a function "
        "returning a Catalyst and dispatch it here; the schema is the contract.")


# --------------------------------------------------------------------------
# The two engines. Kept as pure functions of a Catalyst plus fundamentals so
# they can be tested without re-reading a document.
# --------------------------------------------------------------------------

def top_line_shock(c: Catalyst, ttm_revenue: float | None) -> float | None:
    """Transaction value over trailing revenue -- the proposed normaliser.

    Revenue rather than market cap, because market cap distorts on heavy debt,
    micro-floats and depressed valuations. Returns None when either side is
    missing, and is deliberately undefined for zero-revenue companies rather
    than infinite: a pre-revenue biotech's first contract is not an infinite
    shock, it is unmeasurable on this scale.
    """
    if c.transaction_value_usd is None or not ttm_revenue or ttm_revenue <= 0:
        return None
    return c.transaction_value_usd / ttm_revenue


def negative_engine(c: Catalyst, item_codes: set[str]) -> tuple[bool, str]:
    """Blacklist / short side. Returns (flagged, reason)."""
    if "3.02" in item_codes:
        return True, "item 3.02 unregistered equity issued"
    if "3.01" in item_codes:
        return True, "item 3.01 delisting notice"
    if "4.02" in item_codes:
        return True, "item 4.02 non-reliance"
    if c.has_toxic_financing:
        return True, "toxic financing: " + ",".join(c.toxic_signals)
    if c.event_category == "DILUTION_OFFERING":
        return True, "offering"
    return False, ""


def long_engine(c: Catalyst, shock: float | None, *, min_shock: float = 0.50
                ) -> tuple[bool, str]:
    """Long side, requiring commitment AND size AND no toxicity."""
    if c.has_toxic_financing:
        return False, "toxic financing present"
    if c.event_category not in ("COMMERCIAL_CONTRACT", "FDA_APPROVAL",
                                "CLINICAL_RESULT", "MA_ACTIVITY"):
        return False, f"category {c.event_category}"
    if c.event_category == "COMMERCIAL_CONTRACT":
        if not c.is_binding:
            return False, "non-binding commercial language"
        if shock is None:
            return False, "no measurable top-line shock"
        if shock < min_shock:
            return False, f"shock {shock:.2f} below {min_shock}"
    return True, f"{c.event_category}" + (f" shock={shock:.2f}" if shock else "")

"""A symbol dictionary for company text, built by code from the memory bank's own passages.

Each entry is a common word or phrase of up to four words, and has a short code. Encoding is exact: ``decode(encode(t))
== t`` for any text. Entries are spelled exactly as they occur:
- capitalisation is kept, so "Company" and "company" are separate entries;
- an entry may end with the space that follows it.

Left as plain text:
- names: words that are nearly always capitalised, and any word passed in ``exclude`` (the memory bank's people,
  organisations and projects);
- numbers and identifiers, because only letters form words;
- rare words: an entry is kept only if it saves bytes.

**Codes.** A code is two bytes. The first byte is one of the 13 values that never occur in UTF-8 (0xC0, 0xC1,
0xF5-0xFF), so encoded text is plain UTF-8 for everything that is not an entry. There is room for 3,328 entries.
``symbols`` shows the same encoding with one visible character per entry (Unicode private-use characters, U+E000
onwards), and ``legend`` lists what each one means.

Command line: ``python -m cie.memory.lexicon --tenant NAME {build,evaluate} ...``. ``evaluate`` measures the dictionary
on documents it was not built from, against zstd with and without a trained dictionary, and optionally in tokens of a
tokenizer. The results are in ``docs/LEXICON.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TOKEN = re.compile(r"[A-Za-z]+|[^A-Za-z]+")
LEADS = bytes([0xC0, 0xC1, *range(0xF5, 0x100)])  # bytes that valid UTF-8 never contains
LEAD_SET = frozenset(LEADS)
CODE_BYTES = 2
CAPACITY = len(LEADS) * 256
MAX_WORDS = 4
SYMBOL_BASE = 0xE000  # Unicode private-use area


@dataclass
class Lexicon:
    entries: list[str]
    counts: list[int] = field(default_factory=list)
    built_from: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.entries) > CAPACITY:
            raise ValueError(f"{len(self.entries)} entries; two-byte codes hold {CAPACITY}")
        self.code = {e: i for i, e in enumerate(self.entries)}

    @property
    def version(self) -> str:
        return hashlib.sha1(json.dumps(self.entries).encode()).hexdigest()[:12]

    # ------------------------------------------------------------- encoding
    def units(self, text: str) -> list[str | int]:
        """The text as a list of literal strings and entry codes (greedy, longest entry first)."""
        toks = TOKEN.findall(text)
        out: list[str | int] = []
        i, carry = 0, None  # carry: what is left of a separator whose leading space an entry took
        while i < len(toks):
            t = carry if carry is not None else toks[i]
            carry = None
            if not t[0].isalpha():
                out.append(t)
                i += 1
                continue
            hit = None
            for n in range(MAX_WORDS, 0, -1):
                last = i + 2 * (n - 1)
                if last >= len(toks) or any(toks[k] != " " for k in range(i + 1, last, 2)):
                    continue
                phrase = " ".join(toks[k] for k in range(i, last + 1, 2))
                nxt = toks[last + 1] if last + 1 < len(toks) else ""
                if nxt.startswith(" ") and phrase + " " in self.code:
                    hit = (self.code[phrase + " "], last + 1, nxt[1:])
                elif phrase in self.code:
                    hit = (self.code[phrase], last + 1, None)
                if hit:
                    break
            if hit is None:
                out.append(t)
                i += 1
                continue
            code, i, rest = hit
            out.append(code)
            if rest is not None:
                if rest:
                    carry = rest
                else:
                    i += 1  # the separator was a single space, now inside the entry
        return out

    def encode(self, text: str) -> bytes:
        parts = []
        for u in self.units(text):
            parts.append(bytes([LEADS[u >> 8], u & 0xFF]) if isinstance(u, int) else u.encode())
        return b"".join(parts)

    def decode(self, data: bytes) -> str:
        out, i, start = [], 0, 0
        while i < len(data):
            if data[i] in LEAD_SET:
                if start < i:
                    out.append(data[start:i].decode())
                out.append(self.entries[LEADS.index(data[i]) * 256 + data[i + 1]])
                i += 2
                start = i
            else:
                i += 1
        if start < len(data):
            out.append(data[start:].decode())
        return "".join(out)

    def symbols(self, text: str) -> str:
        """The encoding with one visible character per entry, for people and for a model shown ``legend``."""
        return "".join(chr(SYMBOL_BASE + u) if isinstance(u, int) else u for u in self.units(text))

    def legend(self, texts: Iterable[str]) -> str:
        used = sorted({u for t in texts for u in self.units(t) if isinstance(u, int)})
        return "\n".join(f"{chr(SYMBOL_BASE + c)} = {self.entries[c]!r}" for c in used)

    # ------------------------------------------------------------- files
    def save(self, path: Path) -> None:
        path.write_text(json.dumps({"version": self.version, "built_from": self.built_from,
                                    "entries": [[e, c] for e, c in zip(self.entries, self.counts, strict=True)]}, indent=0, ensure_ascii=False))

    @classmethod
    def load(cls, path: Path) -> Lexicon:
        d = json.loads(path.read_text())
        lex = cls([e for e, _ in d["entries"]], [c for _, c in d["entries"]], d.get("built_from", {}))
        if d.get("version") and d["version"] != lex.version:
            raise ValueError(f"{path}: entries do not match version {d['version']}")
        return lex


def candidates(texts: list[str], exclude: Iterable[str] = (), min_count: int = 5) -> tuple[list[tuple[str, int]], dict[str, Any]]:
    """Words and phrases of up to four words, names left out, ranked by the bytes they would save if every occurrence
    were encoded: (occurrences) x (length in bytes - the two code bytes). Overlapping phrases are all counted, so the
    ranking overstates phrases that share words; encoding prefers the longest entry that fits."""
    toks = [TOKEN.findall(t) for t in texts]
    lower = Counter(w.lower() for ts in toks for w in ts if w[0].isalpha())
    capital = Counter(w.lower() for ts in toks for w in ts if w[0].isupper())
    banned = {w.lower() for w in exclude}
    # a word written with a capital nearly every time is a name, not vocabulary
    names = {w for w, n in lower.items() if capital[w] >= 0.9 * n}
    usable = {w for w, n in lower.items() if n >= min_count and w not in banned and w not in names}
    cand: Counter = Counter()
    for ts in toks:
        for i, t in enumerate(ts):
            if not t[0].isalpha() or t.lower() not in usable:
                continue
            for n in range(1, MAX_WORDS + 1):
                last = i + 2 * (n - 1)
                if last >= len(ts) or ts[last].lower() not in usable or (n > 1 and ts[last - 1] != " "):
                    break
                phrase = " ".join(ts[k] for k in range(i, last + 1, 2))
                nxt = ts[last + 1] if last + 1 < len(ts) else ""
                cand[phrase + " " if nxt.startswith(" ") else phrase] += 1
    scored = sorted(((c * (len(e.encode()) - CODE_BYTES), c, e) for e, c in cand.items() if c >= min_count), reverse=True)
    info = {"texts": len(texts), "words": sum(lower.values()), "distinct_words": len(lower),
            "names_left_out": len(names | (banned & set(lower))), "min_count": min_count, "max_words_per_entry": MAX_WORDS}
    return [(e, c) for s, c, e in scored if s > 0], info


def build(texts: Iterable[str], exclude: Iterable[str] = (), max_entries: int = CAPACITY, min_count: int = 5) -> Lexicon:
    """The best-ranked candidates, as many as two-byte codes hold. (Re-ranking them by the bytes they actually saved
    once encoded, and refilling, changed the size on held-out documents by less than half a point: docs/LEXICON.md.)"""
    ranked, info = candidates(list(texts), exclude, min_count)
    chosen = ranked[:max_entries]
    return Lexicon([e for e, _ in chosen], [c for _, c in chosen], info)


def coverage(lex: Lexicon, texts: Iterable[str]) -> float:
    """The share of word occurrences that end up inside an entry."""
    total = inside = 0
    for t in texts:
        n_words = sum(1 for w in TOKEN.findall(t) if w[0].isalpha())
        left = sum(1 for u in lex.units(t) if isinstance(u, str) and u[0].isalpha())
        total += n_words
        inside += n_words - left
    return inside / total if total else 0.0


# ------------------------------------------------------------------ evaluation
def evaluate(lex: Lexicon, train: list[str], test: list[str], tokenizer_file: str | None = None) -> dict[str, Any]:
    """Bytes and tokens on ``test`` (texts the dictionary was not built from), each text stored on its own."""
    res: dict[str, Any] = {"lexicon_version": lex.version, "entries": len(lex.entries), "test_texts": len(test)}
    exact = sum(lex.decode(lex.encode(t)) == t for t in test)
    res["exact_round_trips"] = f"{exact} of {len(test)}"
    raw = sum(len(t.encode()) for t in test)
    sizes = {"plain text": raw, "symbol dictionary": sum(len(lex.encode(t)) for t in test)}
    try:
        import zstandard

        z = zstandard.ZstdCompressor(level=3)
        sizes["zstd"] = sum(len(z.compress(t.encode())) for t in test)
        sizes["symbol dictionary, then zstd"] = sum(len(z.compress(lex.encode(t))) for t in test)
        zd = zstandard.ZstdCompressor(level=3, dict_data=zstandard.train_dictionary(65536, [t.encode() for t in train]))
        sizes["zstd with a 64 KB dictionary trained on the same documents"] = sum(len(zd.compress(t.encode())) for t in test)
    except ImportError:
        res["zstd"] = "not installed"
    res["bytes"] = {k: {"bytes": v, "share": round(v / raw, 3)} for k, v in sizes.items()}
    res["word_coverage"] = round(coverage(lex, test), 3)
    if tokenizer_file:
        from tokenizers import Tokenizer

        tok = Tokenizer.from_file(tokenizer_file)

        def n(s: str) -> int:
            return len(tok.encode(s, add_special_tokens=False).ids)

        plain_t = sum(n(t) for t in test)
        sym_t = sum(n(lex.symbols(t)) for t in test)
        res["tokens"] = {"plain": plain_t, "symbols": sym_t, "symbols_share": round(sym_t / plain_t, 3),
                         "legend_for_these_texts": n(lex.legend(test))}
    return res


def _texts(conn, tenant_id, skip: int, docs: int) -> list[str]:
    ids = [r[0] for r in conn.execute("SELECT id FROM documents WHERE tenant_id = %s AND deleted_at IS NULL ORDER BY md5(id::text) "
                                      "OFFSET %s LIMIT %s", (tenant_id, skip, docs))]
    return [r[0] for r in conn.execute("SELECT text FROM sections WHERE document_id = ANY(%s) ORDER BY document_id, order_index", (ids,))]


def _names(conn, tenant_id) -> set[str]:
    rows = conn.execute("SELECT summary FROM memory_records WHERE tenant_id = %s AND type IN ('person', 'organization', 'project')",
                        (tenant_id,))
    return {w for (s,) in rows for w in TOKEN.findall(s or "") if w[0].isalpha()}


def main(argv: Iterable[str] | None = None) -> Any:
    ap = argparse.ArgumentParser(description="a symbol dictionary built from the memory bank's passages")
    ap.add_argument("--db", default=None)
    ap.add_argument("--tenant", required=True, help="tenant id or name")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the dictionary from a sample of documents")
    b.add_argument("--docs", type=int, default=1000, help="documents to build from (a fixed sample: ordered by a hash of their id)")
    b.add_argument("--min-count", type=int, default=5)
    b.add_argument("--out", required=True)
    e = sub.add_parser("evaluate", help="measure it on documents it was not built from")
    e.add_argument("--lexicon", required=True)
    e.add_argument("--test-docs", type=int, default=50, help="taken after the documents the dictionary was built from")
    e.add_argument("--tokenizer", default=None, help="a tokenizer.json, to count tokens as a model would")
    a = ap.parse_args(list(argv) if argv is not None else None)
    from cie.memory.facts import _connect, tenant_id_of

    if a.db is None:
        from cie.core.settings import get_settings

        a.db = get_settings().database_url
    conn = _connect(a.db)
    tid = tenant_id_of(conn, a.tenant)
    if a.cmd == "build":
        lex = build(_texts(conn, tid, 0, a.docs), exclude=_names(conn, tid), min_count=a.min_count)
        lex.built_from.update({"documents": a.docs, "tenant": a.tenant})
        lex.save(Path(a.out))
        print(json.dumps({"out": a.out, "version": lex.version, "entries": len(lex.entries), **lex.built_from}, indent=1))
        return lex
    lex = Lexicon.load(Path(a.lexicon))
    n_train = int(lex.built_from.get("documents", 0))
    res = evaluate(lex, _texts(conn, tid, 0, n_train), _texts(conn, tid, n_train, a.test_docs), a.tokenizer)
    print(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":  # pragma: no cover
    sys.exit(0 if main() is not None else 1)

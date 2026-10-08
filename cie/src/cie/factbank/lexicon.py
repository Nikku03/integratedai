"""Learning what words mean from the company's own documents, with no language model.

Two kinds of evidence, both counted:

1. **Words used in the same places (a word space).** Each word is described by the words found within four places of it
   in the documents. The counts are weighted by positive pointwise mutual information and reduced to 150 dimensions with
   a singular value decomposition. These are classic count-based word vectors (latent semantic analysis), with no neural
   network and nothing pretrained. Words used alike end up close.
2. **The kind of value a word goes with (typing).** In the text, person names, dates, statuses and small numbers are
   replaced by markers, and the words within three places of each marker are counted. A word found next to names more
   often than words usually are ("handled by Sofia", "owner: Sofia") is a word about people. One found next to dates
   ("target Mar 5", "due Friday") is a word about dates, and so on. The names and statuses come from the documents' own
   fields.

(A third kind was tried in development and left out: sentences that name a ticket together with one of its field values,
"Sofia is handling ENG-4278". There were too few of them: 219 stating an assignee in 200,000 documents.)

The caller says which documents to leave out (every test set). Nothing else is used.

    python -m cie.factbank.lexicon build --index index.json --root <benchmark> --exclude <work folders> --out lexicon.npz
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from array import array
from collections import Counter, defaultdict
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from cie.factbank.engine import stem

TOKEN = re.compile(r"[a-z][a-z0-9]+")
KEY = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d{2,7}\b")
PR_REF = re.compile(r"(?:#|\bPR[- ]?|/pull/)(\d{3,7})\b", re.I)
SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
SPEAKER = re.compile(r"^[A-Za-z][\w .'-]{0,40}:\s+")  # "Ava: ..." in a chat; elsewhere "Owner: ..." is kept
CHAT_KEYS = {"messages", "transcript"}
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}"
                     r"(?:st|nd|rd|th)?(?:,?\s+\d{4})?\b|\b(?:monday|tuesday|wednesday|thursday|friday)\b", re.I)
NUM_RE = re.compile(r"(?<![\w.#/:-])\d{1,3}(?![\w.%:/-])")
NAME_RE = re.compile(r"\b([A-Z][a-z]+(?:[- ][A-Z][a-z']+){1,2})\b")
MARKS = {"who": " zzwho ", "when": " zzwhen ", "state": " zzstate ", "num": " zznum "}
TYPES = {"zzwho": "who", "zzwhen": "when", "zzstate": "state", "zznum": "num"}
FIELDS = {"linear": ("assignee", "creator", "due_date", "status"), "jira": ("assignee", "reporter", "due_date", "status"),
          "github": ("author", "reviewers", "state")}
SKIP_KEYS = {"id", "key", "url", "link", "path", "email", "thread_id", "meeting_id", "dsid"}
SOURCES = ("slack", "gmail", "confluence", "google_drive", "fireflies", "linear", "jira", "github", "hubspot")


_stem = lru_cache(maxsize=1_000_000)(stem)


def tokens(s: str) -> list[str]:
    return [_stem(t) for t in TOKEN.findall(s.lower())]


def texts_of(raw: Any, out: list[str] | None = None, key: str = "") -> list[str]:
    """Every piece of free text in a record: strings of four words or more, split into sentences."""
    out = [] if out is None else out
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k not in SKIP_KEYS:
                texts_of(v, out, k)
    elif isinstance(raw, list):
        for v in raw:
            texts_of(v, out, key)
    elif isinstance(raw, str) and raw.count(" ") >= 3:
        for s in SPLIT.split(raw.replace("\\n", "\n").replace("\\t", " ")):
            s = SPEAKER.sub("", s.strip()) if key in CHAT_KEYS else s.strip()
            if s.count(" ") >= 2:
                out.append(s)
    return out


def _read(root: Path, rel: str) -> Any:
    try:
        return json.loads((root / rel).read_text(errors="replace")) if rel.endswith(".json") else None
    except (OSError, ValueError):
        return None


def sample(index: dict[str, str], exclude: set[str], n: int, seed: int) -> list[str]:
    """``n`` documents stratified by source, none in ``exclude``."""
    by: dict[str, list[str]] = defaultdict(list)
    for d, rel in sorted(index.items()):
        src = rel.split("/")[0]
        if d not in exclude and src in SOURCES:
            by[src].append(d)
    total = sum(len(v) for v in by.values())
    rng = random.Random(seed)
    out: list[str] = []
    for src in sorted(by):
        out += rng.sample(by[src], min(len(by[src]), max(1, round(n * len(by[src]) / total))))
    return out


# ---------------------------------------------------------------------------------------------------------------- the word space
class WordSpace:
    def __init__(self, vocab: list[str], vectors: np.ndarray):
        self.vocab = vocab
        self.ix = {w: i for i, w in enumerate(vocab)}
        v = vectors.astype(np.float32)
        self.v = v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)

    def sim(self, a: str, b: str) -> float:
        i, j = self.ix.get(a), self.ix.get(b)
        if i is None or j is None:
            return 1.0 if a == b else 0.0
        return float(self.v[i] @ self.v[j])

    def neighbours(self, w: str, among: list[str], k: int = 3, floor: float = 0.4) -> list[tuple[str, float]]:
        i = self.ix.get(w)
        cand = [c for c in among if c != w and c in self.ix]
        if i is None or not cand:
            return []
        s = self.v[[self.ix[c] for c in cand]] @ self.v[i]
        order = np.argsort(-s)[:k]
        return [(cand[j], float(s[j])) for j in order if s[j] >= floor]


def build_space(sentences: Iterable[list[str]], min_count: int = 10, max_vocab: int = 40_000, window: int = 4, dim: int = 150,
                alpha: float = 0.75, log=print) -> WordSpace:
    from scipy import sparse
    from scipy.sparse.linalg import svds

    # one pass: every word gets a provisional id; then the vocabulary keeps the frequent ones
    first: dict[str, int] = {}
    ids = array("i")  # 4 bytes a word: hundreds of millions fit
    gap = array("i", [-1] * window)  # sentences do not touch
    n_sent = 0
    for s in sentences:
        n_sent += 1
        ids.extend([first.setdefault(t, len(first)) for t in s])
        ids.extend(gap)
        if log is not None and n_sent % 5_000_000 == 0:
            log(f"    {n_sent:,} sentences, {len(ids):,} words so far")
    raw = np.frombuffer(ids, dtype=np.int32).copy()
    del ids
    counts = np.bincount(raw[raw >= 0], minlength=len(first))
    words_by_id = list(first)
    order = [i for i in np.argsort(-counts, kind="stable")[:max_vocab] if counts[i] >= min_count]
    vocab = [words_by_id[i] for i in order]
    remap = np.full(len(first) + 1, -1, dtype=np.int32)
    remap[np.array(order, dtype=np.int64)] = np.arange(len(order), dtype=np.int32)
    arr = remap[raw]  # -1 stays -1 (the last slot)
    del raw
    V = len(vocab)
    log(f"  word space: {n_sent:,} sentences, {int((arr >= 0).sum()):,} tokens, {V:,} words")
    C = sparse.csr_matrix((V, V), dtype=np.float32)
    step = 50_000_000
    for d in range(1, window + 1):
        w = np.float32((window - d + 1) / window)
        for lo in range(0, len(arr) - d, step):
            a, b = arr[lo:min(lo + step, len(arr) - d)], arr[lo + d:min(lo + step, len(arr) - d) + d]
            m = (a >= 0) & (b >= 0)
            C = C + sparse.coo_matrix((np.full(int(m.sum()), w, np.float32), (a[m], b[m])), shape=(V, V)).tocsr()
    C = (C + C.T).tocsr()
    total = float(C.sum())
    row = np.asarray(C.sum(axis=1)).ravel()
    col = np.asarray(C.sum(axis=0)).ravel() ** alpha
    col_p = col / col.sum()
    row_p = row / total
    C = C.tocoo()
    pmi = np.log(np.maximum(C.data / total, 1e-30) / (row_p[C.row] * col_p[C.col]))
    keep = pmi > 0
    M = sparse.csr_matrix((pmi[keep].astype(np.float32), (C.row[keep], C.col[keep])), shape=(V, V))
    U, S, _ = svds(M, k=min(dim, V - 1))
    return WordSpace(vocab, U * np.sqrt(S))


# ------------------------------------------------------------------------------------------------- the documents' own fields
def _person_forms(v: Any) -> list[str]:
    from cie.ingest.sources import person_name

    out = []
    for x in v if isinstance(v, list) else [v]:
        n = person_name(x) if x else None
        if n:
            out.append(n.lower())
    return out


def item_facts(raw: dict[str, Any], src: str) -> tuple[str, dict[str, list[str]]] | None:
    """A ticket's or pull request's reference and the values of its fields, in the forms a sentence would use (the people and
    statuses that typing marks come from here)."""
    if src == "github":
        n = str(raw.get("pr_number") or "")
        if not n.isdigit():
            return None
        ref = f"pr:{n}"
    else:
        k = str(raw.get("key") or "").upper()
        if not KEY.fullmatch(k):
            return None
        ref = k
    vals: dict[str, list[str]] = {}
    for f in FIELDS[src]:
        v = raw.get(f)
        if not v:
            continue
        if f in ("due_date",):
            vals[f] = [str(v)[:10]]
        elif f in ("status", "state"):
            vals["status"] = [str(v).lower()]
        else:
            forms = _person_forms(v)
            vals[f] = forms + [p.split()[0] for p in forms if len(p.split()[0]) >= 3]
    return ref, vals


class Anchors:
    """How strongly a word goes with a kind of value: its share of occurrences near a marker of that kind, above the usual
    share (``add_near``). ``add`` counts whole sentences instead."""

    def __init__(self, d: dict[str, Any] | None = None):
        d = d or {}
        self.n = float(d.get("n", 0))
        self.field = Counter(d.get("field", {}))
        self.word = Counter(d.get("word", {}))
        self.pair: dict[str, Counter] = defaultdict(Counter, {w: Counter(v) for w, v in d.get("pair", {}).items()})

    def add(self, words: set[str], fields: set[str]) -> None:
        self.n += 1
        self.field.update(fields)
        self.word.update(words)
        for w in words:
            self.pair[w].update(fields)

    def add_near(self, words: list[str], near: dict[str, set[str]]) -> None:
        """One sentence's words, and for each type the words found near one of its markers."""
        self.n += len(words)
        self.word.update(words)
        for t, ws in near.items():
            self.field[t] += len(ws)
            for w in ws:
                self.pair[w][t] += 1

    def score(self, w: str, field: str, k: float = 3.0, min_count: int = 3) -> float:
        if self.n <= 0 or self.word.get(w, 0) < min_count or not self.field.get(field):
            return 0.0
        p = self.field[field] / self.n
        q = (self.pair.get(w, {}).get(field, 0) + k * p) / (self.word[w] + k)
        return max(0.0, (q - p) / (1 - p)) if p < 1 else 0.0

    def to_json(self, min_count: int = 3) -> dict[str, Any]:
        keep = {w for w, c in self.word.items() if c >= min_count}
        return {"n": self.n, "field": dict(self.field), "word": {w: self.word[w] for w in keep},
                "pair": {w: dict(self.pair[w]) for w in keep if self.pair.get(w)}}


_STATUS_RES: dict[frozenset, tuple[re.Pattern | None, re.Pattern | None]] = {}


def _status_res(statuses: set[str]) -> tuple[re.Pattern | None, re.Pattern | None]:
    key = frozenset(statuses)
    if key not in _STATUS_RES:
        multi = sorted((v for v in statuses if " " in v), key=len, reverse=True)
        single = sorted(v.capitalize() for v in statuses if " " not in v)
        # a one-word status only where it is written as one: capitalised, not at the start of the sentence
        _STATUS_RES[key] = (re.compile(r"(?i)\b(?:" + "|".join(map(re.escape, multi)) + r")\b") if multi else None,
                            re.compile(r"(?<=\S )(?:" + "|".join(map(re.escape, single)) + r")\b") if single else None)
    return _STATUS_RES[key]


def mark(sentence: str, people: set[str], statuses: set[str]) -> str:
    """The sentence with person names, dates, statuses and small numbers replaced by markers."""
    s = DATE_RE.sub(MARKS["when"], sentence)
    s = NAME_RE.sub(lambda m: MARKS["who"] if m.group(1).lower() in people else m.group(0), s)
    for rx in _status_res(statuses):
        if rx is not None:
            s = rx.sub(MARKS["state"], s)
    return NUM_RE.sub(MARKS["num"], s)


def typing(sentences: list[str], people: set[str], statuses: set[str], window: int = 3) -> Anchors:
    ty = Anchors()
    for sent in sentences:
        toks = tokens(mark(sent, people, statuses))
        if not toks:
            continue
        near: dict[str, set[str]] = defaultdict(set)
        for i, t in enumerate(toks):
            if t in TYPES:
                for j in range(max(0, i - window), min(len(toks), i + window + 1)):
                    if toks[j] not in TYPES:
                        near[TYPES[t]].add(toks[j])
        ty.add_near([t for t in dict.fromkeys(toks) if t not in TYPES], near)
    return ty


# ---------------------------------------------------------------------------------------------------------- general English
# docs/FACTBANK_GENERAL_PREREGISTRATION.md: two public bodies of ordinary English, counted the same way as the company's text
WIKITEXT = [f"https://huggingface.co/datasets/Salesforce/wikitext/resolve/main/wikitext-103-raw-v1/train-0000{i}-of-00002.parquet"
            for i in (0, 1)]
C4 = [f"https://huggingface.co/datasets/allenai/c4/resolve/main/en/c4-train.0000{i}-of-01024.json.gz" for i in (0, 1)]
HEADING = re.compile(r"^\s*=+ .* =+\s*$")


def general_sentences(tmp: Path, log=print, wikitext: list[str] = WIKITEXT, c4: list[str] = C4):
    """Sentences of WikiText-103 (downloaded one file at a time, read, deleted) and of C4 (streamed, never stored)."""
    import gzip
    import urllib.request

    import pyarrow.parquet as pq

    tmp.mkdir(parents=True, exist_ok=True)
    for url in wikitext:
        path = tmp / "wikitext.parquet"
        with urllib.request.urlopen(url, timeout=120) as r, open(path, "wb") as f:
            while chunk := r.read(1 << 22):
                f.write(chunk)
        n = 0
        for batch in pq.ParquetFile(path).iter_batches(columns=["text"], batch_size=50_000):
            for line in batch.column(0).to_pylist():
                if line and not HEADING.match(line):
                    for s in SPLIT.split(line.replace(" @-@ ", "-").replace(" @,@ ", ",").replace(" @.@ ", ".")):
                        if s.count(" ") >= 2:
                            n += 1
                            yield s
        path.unlink()
        log(f"  {url.rsplit('/', 1)[-1]}: {n:,} sentences")
    for url in c4:
        n = 0
        with urllib.request.urlopen(url, timeout=120) as r, gzip.GzipFile(fileobj=r) as g:
            for line in g:
                text = json.loads(line).get("text") or ""
                for s in SPLIT.split(text):
                    if s.count(" ") >= 2:
                        n += 1
                        yield s
        log(f"  {url.rsplit('/', 1)[-1]}: {n:,} sentences")


def build_general(out: Path, tmp: Path, window: int = 2, dim: int = 200, max_vocab: int = 80_000, min_count: int = 10, log=print,
                  wikitext: list[str] = WIKITEXT, c4: list[str] = C4) -> dict[str, Any]:
    """The general-English word space, saved as a lexicon with no value kinds."""
    t0 = time.perf_counter()
    space = build_space((tokens(s) for s in general_sentences(tmp, log, wikitext, c4)), min_count=min_count, max_vocab=max_vocab,
                        window=window, dim=dim, log=log)
    info = {"corpus": "WikiText-103 train + C4 en train 00000-00001", "sources": wikitext + c4, "window": window, "dim": dim,
            "words": len(space.vocab), "seconds": round(time.perf_counter() - t0, 1)}
    Lexicon(space, None, info).save(out)
    return info


# ---------------------------------------------------------------------------------------------------------------- the lexicon
class Lexicon:
    def __init__(self, space: WordSpace, types: Anchors | None = None, info: dict[str, Any] | None = None):
        self.space = space
        self.types = types or Anchors()
        self.info = info or {}

    def save(self, path: str | Path) -> None:
        np.savez_compressed(path, vocab=np.array(self.space.vocab), vectors=self.space.v.astype(np.float16),
                            types=np.array(json.dumps(self.types.to_json(min_count=5))), info=np.array(json.dumps(self.info)))

    @classmethod
    def load(cls, path: str | Path) -> Lexicon:
        z = np.load(path, allow_pickle=False)
        return cls(WordSpace([str(w) for w in z["vocab"]], z["vectors"]), Anchors(json.loads(str(z["types"]))), json.loads(str(z["info"])))

    def kind_of(self, w: str, kind: str) -> float:
        """How strongly a word goes with a kind of value (who, when, state, num)."""
        return self.types.score(w, kind, k=20.0, min_count=20)


def build(index_path: Path, root: Path, exclude_dirs: list[Path], out: Path, n_docs: int = 60_000, seed: int = 23, window: int = 4,
          log=print, drop_dirs: list[Path] | None = None) -> dict[str, Any]:
    """``drop_dirs``: work folders whose documents are removed after sampling, so the rest of the sample stays the same (used to
    check that a test set drawn later did not gain from being in the sample)."""
    t0 = time.perf_counter()
    index = json.loads(index_path.read_text())["index"]
    exclude = set().union(*(set(json.loads((d / "haystack.json").read_text())["dsids"]) for d in exclude_dirs))
    drop = set().union(*(set(json.loads((d / "haystack.json").read_text())["dsids"]) for d in drop_dirs or []))
    src = root / "generated_data" / "sources"
    from cie.ingest.sources import PEOPLE_FIELDS

    sents: list[str] = []
    people: set[str] = set()
    for d in sample(index, exclude, n_docs, seed):
        if d in drop:
            continue
        raw = _read(src, index[d])
        if raw is not None:
            sents += texts_of(raw)
            if isinstance(raw, dict):
                for f in PEOPLE_FIELDS:
                    people.update(p for p in _person_forms(raw.get(f)) if " " in p)
    log(f"  {len(sents):,} sentences from {n_docs:,} documents, {time.perf_counter() - t0:.0f} s")
    statuses: set[str] = set()
    for d, rel in index.items():
        s = rel.split("/")[0]
        if d in exclude or d in drop or s not in FIELDS:
            continue
        raw = _read(src, rel)
        got = item_facts(raw, s) if isinstance(raw, dict) else None
        if got:
            statuses.update(got[1].get("status", []))
            for f in ("assignee", "creator", "reporter", "author", "reviewers"):
                people.update(p for p in got[1].get(f, []) if " " in p)
    statuses = {v for v in statuses if len(v) >= 4 and v.replace(" ", "").isalpha()}
    ty = typing(sents, people, statuses)
    log(f"  typing: {len(people):,} people, {len(statuses)} statuses, words near a marker: {dict(ty.field)}")
    space = build_space((tokens(s) for s in sents), window=window, log=log)
    info = {"documents": n_docs, "seed": seed, "window": window, "dropped_documents": len(drop), "sentences": len(sents), "excluded_documents": len(exclude), "words": len(space.vocab),
            "people": len(people), "statuses": sorted(statuses),
            "typed": dict(ty.field), "seconds": round(time.perf_counter() - t0, 1)}
    lex = Lexicon(space, ty, info)
    lex.save(out)
    return info


def main(argv: list[str] | None = None) -> Any:
    ap = argparse.ArgumentParser(prog="python -m cie.factbank.lexicon")
    ap.add_argument("cmd", choices=["build", "general", "near"])
    ap.add_argument("--index")
    ap.add_argument("--root")
    ap.add_argument("--exclude", nargs="*", default=[])
    ap.add_argument("--out")
    ap.add_argument("--docs", type=int, default=60_000)
    ap.add_argument("--window", type=int, default=4)
    ap.add_argument("--drop", nargs="*", default=[], help="build: work folders whose documents are removed after sampling")
    ap.add_argument("--words", nargs="*", default=[])
    a = ap.parse_args(argv)
    if a.cmd == "general":
        out = build_general(Path(a.out), Path(a.out).parent / "general_tmp", window=a.window)
        print(json.dumps(out, indent=1))
        return out
    if a.cmd == "build":
        out = build(Path(a.index), Path(a.root), [Path(x) for x in a.exclude], Path(a.out), a.docs, window=a.window,
                    drop_dirs=[Path(x) for x in a.drop])
        print(json.dumps(out, indent=1))
        return out
    lex = Lexicon.load(a.out)
    for w in a.words:
        s = stem(w)
        near = lex.space.neighbours(s, lex.space.vocab[:20_000], k=8, floor=0.0)
        kinds = {t: round(lex.kind_of(s, t), 3) for t in lex.types.field}
        print(f"{w}: " + ", ".join(f"{n} {v:.2f}" for n, v in near) + f" | kinds {kinds}")
    return None


if __name__ == "__main__":
    main()

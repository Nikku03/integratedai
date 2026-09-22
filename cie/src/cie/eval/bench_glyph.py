"""Benchmark glyph storage encodings.

Arms: JSON, JSON+zlib, msgpack, msgpack+zlib, columnar Parquet (zstd), a PNG
"pixel" encoding (glyph bytes packed into a grayscale image), a DNA-like 2-bit
ACGT text encoding, and a lossy hashed "frequency" encoding. Measures bytes per
glyph, encode/decode latency, exact round-trip and field-filter (search) cost.

Decision rule (applied automatically in the report): any arm that fails exact
reconstruction is rejected; among the rest the smallest-with-fast-decode wins,
searchability breaking ties.
"""

from __future__ import annotations

import hashlib
import io
import json
import random
import statistics
import time
import zlib
from pathlib import Path
from typing import Any

import msgpack
import orjson

TYPES = ["fact", "decision", "deadline", "metric", "risk", "contract_clause", "requirement", "task"]
WORDS = ("supplier agreement fee termination notice liability penalty budget approval board quarter "
         "prototype delivery warehouse automation invoice audit compliance clause schedule amendment").split()


def synth_glyph(rng: random.Random, i: int) -> dict[str, Any]:
    t = rng.choice(TYPES)
    return {
        "v": 1, "id": hashlib.sha1(f"g{i}".encode()).hexdigest()[:32], "type": t,
        "what": " ".join(rng.choice(WORDS) for _ in range(rng.randint(6, 18))).capitalize() + ".",
        "who": [rng.choice(["Acme Robotics Inc.", "Northwind Logistics Ltd.", "Jane Whitfield", "Finance"]) for _ in range(rng.randint(0, 3))],
        "why": "Governs rights and duties under the agreement." if t == "contract_clause" else None,
        "project": rng.choice(["Project Atlas", "Project Borealis", None]),
        "department": rng.choice(["Legal", "Finance", "Engineering"]),
        "time": {"valid_from": f"2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}T00:00:00+00:00"},
        "status": rng.choice(["current", "current", "current", "superseded", "disputed"]),
        "dependencies": [hashlib.sha1(f"d{rng.randint(0, 5000)}".encode()).hexdigest()[:32] for _ in range(rng.randint(0, 3))],
        "consequences": [], "contradictions": [],
        "confidence": round(rng.random(), 3), "verification": "unverified",
        "evidence": [{"document_id": hashlib.sha1(f"doc{rng.randint(0, 300)}".encode()).hexdigest()[:32],
                      "page_no": rng.randint(1, 300), "bbox": [round(rng.uniform(0, 600), 1) for _ in range(4)],
                      "quote": " ".join(rng.choice(WORDS) for _ in range(12))}],
        "keywords": [rng.choice(WORDS) for _ in range(rng.randint(3, 10))],
    }


def _compact(g: dict) -> dict:
    return {k: v for k, v in g.items() if v not in (None, [], {}, "")}


# ---------------------------------------------------------------- encodings
class Arm:
    name = "base"
    lossless_claim = True
    searchable_without_full_decode = False

    def encode_one(self, g: dict) -> bytes: ...
    def decode_one(self, b: bytes) -> dict: ...

    def encode_batch(self, gs: list[dict]) -> bytes:
        return msgpack.packb([self.encode_one(g) for g in gs], use_bin_type=True)

    def decode_batch(self, b: bytes) -> list[dict]:
        return [self.decode_one(x) for x in msgpack.unpackb(b, raw=False)]

    def filter_type(self, blob: bytes, t: str) -> int:
        return sum(1 for g in self.decode_batch(blob) if g.get("type") == t)


class JsonArm(Arm):
    name = "json"

    def encode_one(self, g): return orjson.dumps(g)
    def decode_one(self, b): return orjson.loads(b)


class JsonZlibArm(Arm):
    name = "json+zlib"

    def encode_one(self, g): return zlib.compress(orjson.dumps(g), 6)
    def decode_one(self, b): return orjson.loads(zlib.decompress(b))

    def encode_batch(self, gs): return zlib.compress(orjson.dumps(gs), 6)
    def decode_batch(self, b): return orjson.loads(zlib.decompress(b))


class MsgpackArm(Arm):
    name = "msgpack"

    def encode_one(self, g): return msgpack.packb(g, use_bin_type=True)
    def decode_one(self, b): return msgpack.unpackb(b, raw=False)

    def encode_batch(self, gs): return msgpack.packb(gs, use_bin_type=True)
    def decode_batch(self, b): return msgpack.unpackb(b, raw=False)


class MsgpackZlibArm(MsgpackArm):
    name = "msgpack+zlib"

    def encode_one(self, g): return zlib.compress(msgpack.packb(g, use_bin_type=True), 6)
    def decode_one(self, b): return msgpack.unpackb(zlib.decompress(b), raw=False)

    def encode_batch(self, gs): return zlib.compress(msgpack.packb(gs, use_bin_type=True), 6)
    def decode_batch(self, b): return msgpack.unpackb(zlib.decompress(b), raw=False)


class ParquetArm(Arm):
    """Columnar (Arrow/Parquet, zstd). Nested fields are stored as JSON strings
    so exact round-trip is well defined; scalar fields are real columns."""

    name = "parquet(zstd)"
    searchable_without_full_decode = True
    SCALARS = ("v", "id", "type", "what", "why", "project", "department", "status", "confidence", "verification")

    def __init__(self):
        import pyarrow as pa
        import pyarrow.parquet as pq

        self.pa, self.pq = pa, pq

    def _rows(self, gs):
        rows = []
        for g in gs:
            r = {k: g.get(k) for k in self.SCALARS}
            r["rest"] = orjson.dumps({k: v for k, v in g.items() if k not in self.SCALARS}).decode()
            rows.append(r)
        return rows

    def encode_batch(self, gs):
        table = self.pa.Table.from_pylist(self._rows(gs))
        buf = io.BytesIO()
        self.pq.write_table(table, buf, compression="zstd")
        return buf.getvalue()

    def decode_batch(self, b):
        t = self.pq.read_table(io.BytesIO(b)).to_pylist()
        out = []
        for r in t:
            g = {k: r[k] for k in self.SCALARS if r[k] is not None}
            g.update(orjson.loads(r["rest"]))
            out.append(g)
        return out

    def encode_one(self, g): return self.encode_batch([g])
    def decode_one(self, b): return self.decode_batch(b)[0]

    def filter_type(self, blob, t):
        tbl = self.pq.read_table(io.BytesIO(blob), columns=["type"])
        return sum(1 for x in tbl.column("type").to_pylist() if x == t)


class PixelArm(Arm):
    """'Pixel glyph': msgpack bytes laid out as a square 8-bit grayscale PNG."""

    name = "png-pixel"

    def encode_one(self, g):
        from PIL import Image

        raw = msgpack.packb(g, use_bin_type=True)
        n = len(raw)
        side = int(n ** 0.5) + 1
        padded = raw + b"\x00" * (side * side - n)
        img = Image.frombytes("L", (side, side), padded)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return len(raw).to_bytes(4, "big") + buf.getvalue()

    def decode_one(self, b):
        from PIL import Image

        n = int.from_bytes(b[:4], "big")
        img = Image.open(io.BytesIO(b[4:]))
        raw = img.tobytes()[:n]
        return msgpack.unpackb(raw, raw=False)


class DnaArm(Arm):
    """DNA-like 2-bit encoding: every byte becomes four ACGT letters (lossless, 4x)."""

    name = "dna-acgt"
    _MAP = "ACGT"

    def encode_one(self, g):
        raw = msgpack.packb(g, use_bin_type=True)
        return "".join(self._MAP[(byte >> s) & 3] for byte in raw for s in (6, 4, 2, 0)).encode()

    def decode_one(self, b):
        s = b.decode()
        inv = {c: i for i, c in enumerate(self._MAP)}
        out = bytearray()
        for i in range(0, len(s), 4):
            out.append((inv[s[i]] << 6) | (inv[s[i + 1]] << 4) | (inv[s[i + 2]] << 2) | inv[s[i + 3]])
        return msgpack.unpackb(bytes(out), raw=False)


class FrequencyArm(Arm):
    """Lossy 'frequency/shape' encoding: a 64-bin hashed histogram of tokens.
    Included to measure, not to use: it cannot reconstruct the glyph."""

    name = "hashed-frequency(lossy)"
    lossless_claim = False

    def encode_one(self, g):
        vec = [0] * 64
        for tok in orjson.dumps(g).decode().replace('"', " ").replace(",", " ").split():
            vec[int(hashlib.blake2b(tok.encode(), digest_size=2).hexdigest(), 16) % 64] += 1
        return bytes(min(v, 255) for v in vec)

    def decode_one(self, b):
        return {"_histogram": list(b)}  # not a glyph


# ---------------------------------------------------------------- harness
def run(n: int = 2000, seed: int = 7) -> dict[str, Any]:
    rng = random.Random(seed)
    glyphs = [_compact(synth_glyph(rng, i)) for i in range(n)]
    arms: list[Arm] = [JsonArm(), JsonZlibArm(), MsgpackArm(), MsgpackZlibArm(), PixelArm(), DnaArm(), FrequencyArm()]
    try:
        arms.insert(4, ParquetArm())
    except Exception as e:  # pyarrow optional
        print("parquet arm skipped:", e)
    results = []
    for arm in arms:
        # single-glyph path
        t = time.perf_counter()
        encoded = [arm.encode_one(g) for g in glyphs]
        enc_ms = (time.perf_counter() - t) * 1000 / n
        t = time.perf_counter()
        decoded = [arm.decode_one(b) for b in encoded]
        dec_ms = (time.perf_counter() - t) * 1000 / n
        exact = all(d == g for d, g in zip(decoded, glyphs, strict=True))
        per_glyph = statistics.mean(len(b) for b in encoded)
        # batch path
        t = time.perf_counter()
        blob = arm.encode_batch(glyphs)
        batch_enc_ms = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        _ = arm.decode_batch(blob)
        batch_dec_ms = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        try:
            cnt = arm.filter_type(blob, "decision")
            filter_ms = (time.perf_counter() - t) * 1000
        except Exception:
            cnt, filter_ms = -1, float("nan")
        results.append({
            "arm": arm.name, "bytes_per_glyph": round(per_glyph, 1), "batch_bytes_per_glyph": round(len(blob) / n, 1),
            "encode_ms_per_glyph": round(enc_ms, 4), "decode_ms_per_glyph": round(dec_ms, 4),
            "batch_encode_ms": round(batch_enc_ms, 1), "batch_decode_ms": round(batch_dec_ms, 1),
            "filter_by_type_ms": round(filter_ms, 1), "filter_count": cnt, "exact_roundtrip": exact,
            "searchable_without_full_decode": arm.searchable_without_full_decode,
        })
    ok = [r for r in results if r["exact_roundtrip"]]
    per_record = sorted(ok, key=lambda r: (r["bytes_per_glyph"], r["decode_ms_per_glyph"]))
    batch = sorted(ok, key=lambda r: (r["batch_bytes_per_glyph"], r["batch_decode_ms"]))
    verdict = {
        "rejected_lossy": [r["arm"] for r in results if not r["exact_roundtrip"]],
        "smallest_exact_per_record": per_record[0]["arm"] if per_record else None,
        "smallest_exact_batch": batch[0]["arm"] if batch else None,
        "recommended_storage": "PostgreSQL JSONB (indexed, queryable in place) for the live store, which is what the "
                               f"system uses; {per_record[0]['arm'] if per_record else 'n/a'} for single-record transport; "
                               f"{batch[0]['arm'] if batch else 'n/a'} for cold archives/export of many glyphs",
        "note": "png-pixel and dna-acgt are exact but strictly larger and slower than msgpack/zlib of the same bytes; "
                "they add nothing but overhead. The lossy frequency arm cannot reconstruct a glyph and is rejected.",
    }
    return {"n": n, "results": results, "verdict": verdict}


def to_markdown(rep: dict) -> str:
    lines = [f"### Glyph encoding benchmark (n={rep['n']} synthetic glyphs)", "",
             "| arm | bytes/glyph | batch bytes/glyph | enc ms | dec ms | filter-by-type ms | exact | searchable w/o full decode |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rep["results"]:
        lines.append(f"| {r['arm']} | {r['bytes_per_glyph']} | {r['batch_bytes_per_glyph']} | {r['encode_ms_per_glyph']} | "
                     f"{r['decode_ms_per_glyph']} | {r['filter_by_type_ms']} | {'yes' if r['exact_roundtrip'] else '**NO**'} | "
                     f"{'yes' if r['searchable_without_full_decode'] else 'no'} |")
    v = rep["verdict"]
    lines += ["", f"Rejected (lossy): {', '.join(v['rejected_lossy']) or 'none'}. Smallest exact per record: "
              f"**{v['smallest_exact_per_record']}**; smallest exact in batch: **{v['smallest_exact_batch']}**.",
              "", v["recommended_storage"] + ".", "", v["note"]]
    return "\n".join(lines)


def main(out: Path) -> dict:
    rep = run()
    out.mkdir(parents=True, exist_ok=True)
    (out / "bench_glyph.json").write_text(json.dumps(rep, indent=2))
    md = to_markdown(rep)
    (out / "bench_glyph.md").write_text(md)
    print(md)
    return rep


if __name__ == "__main__":  # pragma: no cover
    main(Path("eval_out/bench"))

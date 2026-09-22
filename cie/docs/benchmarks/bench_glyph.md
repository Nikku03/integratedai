### Glyph encoding benchmark (n=2000 synthetic glyphs)

| arm | bytes/glyph | batch bytes/glyph | enc ms | dec ms | filter-by-type ms | exact | searchable w/o full decode |
|---|---|---|---|---|---|---|---|
| json | 746.1 | 749.1 | 0.0037 | 0.005 | 21.4 | yes | no |
| json+zlib | 460.7 | 157.6 | 0.0267 | 0.0137 | 12.2 | yes | no |
| msgpack | 683.1 | 683.1 | 0.0026 | 0.0052 | 8.3 | yes | no |
| msgpack+zlib | 478.8 | 168.3 | 0.0335 | 0.0144 | 15.4 | yes | no |
| parquet(zstd) | 5865.3 | 149.7 | 1.6359 | 1.3201 | 1.3 | yes | yes |
| png-pixel | 734.6 | 737.6 | 0.1138 | 0.0581 | 115.8 | yes | no |
| dna-acgt | 2732.4 | 2735.4 | 0.1995 | 0.1387 | 285.0 | yes | no |
| hashed-frequency(lossy) | 64 | 66.0 | 0.0731 | 0.0085 | 3.4 | **NO** | no |

Rejected (lossy): hashed-frequency(lossy). Smallest exact per record: **json+zlib**; smallest exact in batch: **parquet(zstd)**.

PostgreSQL JSONB (indexed, queryable in place) for the live store, which is what the system uses; json+zlib for single-record transport; parquet(zstd) for cold archives/export of many glyphs.

png-pixel and dna-acgt are exact but strictly larger and slower than msgpack/zlib of the same bytes; they add nothing but overhead. The lossy frequency arm cannot reconstruct a glyph and is rejected.
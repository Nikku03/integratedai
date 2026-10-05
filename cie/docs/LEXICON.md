# A symbol dictionary for company text

The idea: give each common word or phrase a short code, and leave names, numbers and rare words as text. A company's
text would then take less space, and perhaps fewer tokens for a model. `cie.memory.lexicon` builds such a dictionary
from the memory bank's own passages and encodes text with it, exactly and reversibly. This page records what it gives.

## The dictionary

- **Entries.** A word or a phrase of up to four words, spelled exactly as it occurs: capitalisation is kept, and an
  entry may include the space after it. Entries are ranked by the bytes they save: occurrences × (bytes − 2).
- **Left as text.**
  - names: words written with a capital nearly every time, plus the memory bank's people, organisations and projects;
  - numbers and identifiers;
  - rare words: those seen fewer than 5 times, or that would not save a byte.
- **Codes.** Two bytes each. The first byte is one of the 13 values that never occur in UTF-8, so everything else stays
  plain UTF-8, and decoding is exact. That leaves room for 3,328 entries.
- **For people and models.** `symbols()` shows one private-use Unicode character per entry, and `legend()` lists what
  each means.

```bash
python -m cie.memory.lexicon --tenant erbfull-5000-9688c2 build --docs 1000 --out lexicon.json
python -m cie.memory.lexicon --tenant erbfull-5000-9688c2 evaluate --lexicon lexicon.json --test-docs 50 [--tokenizer tokenizer.json]
```

The dictionary built from 1,000 documents of the 5,000-document memory bank is in
`docs/benchmarks/lexicon/lexicon_erb_1000docs.json`. The documents are the benchmark's generated (fictional) company.

| | |
|---|---|
| words read | 854,785 (16,176 distinct) |
| names left out | 2,977 |
| entries | 3,328 (all two-byte codes), 910 of them phrases |
| top entries | "the ", "to ", "participant", "that ", "can ", "in the ", "in ", "will ", "confirm ", "request " |
| build time | about 6 s on 4 CPUs |

## Measured, 2026-10-05, on 50 documents the dictionary was not built from

Each of their 377 passages was encoded on its own, as the database stores passages. Every one decoded back exactly.

| storage | bytes | of plain text |
|---|---|---|
| plain text | 335,782 | 100% |
| symbol dictionary | 236,400 | 70.4% |
| zstd | 211,689 | 63.0% |
| symbol dictionary, then zstd | 187,098 | 55.7% |
| **zstd with a 64 KB dictionary trained on the same 1,000 documents** | **143,928** | **42.9%** |

- **Words covered.** 48.7% of the word occurrences fall inside an entry. There are 3,328 places, and company text has a
  long tail of terms.
- **Two variants, no better.**
  - A words-only dictionary (the commonest words, each with its space): 71.0%.
  - Re-ranking the entries by the bytes they actually saved, then refilling, over 3 and 6 rounds: 70.6% and 70.7%.

| tokens (Llama 3.1 tokenizer) | count |
|---|---|
| plain text | 80,637 |
| symbol form | 123,201 (153%) |
| legend a model would need for these 50 documents | 20,458 |

## What this means

- **For storage,** the symbol dictionary is beaten by zstd alone. A dictionary that zstd trains automatically does
  better still: 42.9% against 70.4%. That is the same idea, a learned table of common strings, done at the byte level.
- **For a model,** the symbol form costs 53% more tokens, before its legend. The tokenizer is already a learned
  dictionary: common words are one token each, and most symbols take one or two.
- **For the memory bank's capacity,** the text is about 4 of the roughly 60 bytes stored per token. The RAM that limits
  fast search is the vector index. So no text encoding changes how many documents fit in memory.

The module stays for these measurements and for anyone who wants to look at a company's vocabulary. The memory bank
does not use it to store text. If disk ever matters, a zstd dictionary on stored text is the measured better choice.

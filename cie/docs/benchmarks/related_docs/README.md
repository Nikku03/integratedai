# Related documents: organise neighbours at load time, extract from them at question time (50 documents)

## Plan (written before the run; the settings below are fixed and were not tuned)

**The idea, polished.** Many answers are spread over several documents. On the 5,000-document memory bank, 131 of the
196 answer facts that missed the model sat in documents outside the first 5. A further 6 of 147 facts on 50 documents
were split across a thread or several documents (`../inside_bm25/`, `../missing_facts/`). So:

1. **At load time, give every document a short list of related documents.** No model is involved, and three signals
   are tried:
   - **similar content:** the cosine of document vectors (the mean of the document's passage vectors);
   - **shared names and identifiers:** people, companies and the project from the memory card. Ticket keys, config
     and metric identifiers (snake_case, dotted or hyphenated names) and URLs found in the text also count. Each is
     weighted by rarity (log N / df). A name shared by 2 documents counts far more than one shared by 10. Names in
     more than 20% of documents are ignored, so "Redwood" or a company-wide person does not link everything;
   - **both:** the two rankings fused (RRF).

   Each document keeps its top 3.
2. **At question time, extract from the neighbours.** After today's search and document expansion:
   - take each of the first 3 documents and its 2 best neighbours;
   - from each neighbour, take the 3 passages that best match the question (BM25 and vector search inside that
     document, fused);
   - place them right after the first document's block, so related evidence arrives together.
3. **Added: the next passage.** Chat threads tell a fact over several turns. For each of the first 8 passages, the
   passage that follows it in the same document is placed right after it.

**Setup.**
- The same 50 documents, 26 development-half questions (all 8 types; 12 with 2 to 6 gold documents) and passages as
  `../missing_facts/`, built in memory, with no database.
- Today's search: BM25 and vector, fused by RRF, then expansion of 3 documents × 5 passages.

**Arms.**
1. today;
2. related documents by similar content;
3. related documents by shared names and identifiers;
4. related documents by both;
5. today plus the next passage;
6. related documents by both, plus the next passage.

**Budgets.** The model reads 6,000, 12,000 or 24,000 characters (each passage cut at 1,200, plus 120 characters of
labels).

**Measures.**
- **Findable answer facts reached.** A fact is reached when the word check finds it in what the model reads, or every
  passage the judge named for it (`../missing_facts/judge.json`) is in what the model reads. Facts the judge found
  only by inference, or only in part, are left out (11), which leaves 136.
- Questions with every findable fact reached.
- **Gold-document recall:** the share of a question's gold documents with a passage in what the model reads, for all
  26 questions and for the 12 multi-document questions.
- Characters read.
- **Neighbour quality:** the share of neighbour links that join two gold documents of one question.

The run happens once. No default changes on its result. If an arm helps, it gets a pre-registered test on the
5,000-document memory bank.

## Results (added after the single run)

**Neighbours.** They take 66 ms to build for 50 documents.

| signal | links joining two gold documents of one question | gold-document pairs linked |
|---|---|---|
| similar content | 66 of 150 | 39 of 50 |
| shared names and identifiers | 64 of 147 | 36 of 50 |
| both | 67 of 150 | 40 of 50 |

The links find most pairs of documents that one question needs together. More than half the links, though, join
documents that no question needs together: they relate to the document, not to the question.

**What reaches the model.** Findable facts reached, of 136; in brackets, gold-document recall on the 12
multi-document questions:

| arm | 6,000 characters | 12,000 characters | 24,000 characters |
|---|---|---|---|
| **today** | **75** (0.48) | **116** (0.83) | 129 (0.96) |
| related: similar content | 74 (0.48) | 99 (0.86) | 126 (0.96) |
| related: shared names and identifiers | 75 (0.52) | 101 (0.89) | 128 (0.96) |
| related: both | 74 (0.48) | 99 (0.89) | 128 (0.96) |
| today + next passage | 70 (0.48) | 103 (0.75) | **130** (0.96) |
| related: both + next passage | 69 (0.48) | 94 (0.72) | 125 (0.93) |

Today at 24,000 characters reaches 129 facts here. The missing-facts analysis said 130 because it also accepted the
judge's passages for one fact the word check missed (qst_0433.F5).

**By question** (related: both against today, `split.py`):

| budget | single-document questions (45 facts) | multi-document questions (91 facts) |
|---|---|---|
| 12,000 characters | 45 → 38 | 71 → 61 |
| 24,000 characters | 45 → 45 | 84 → 83 |

**Why it does not help here:**
- **Search already brings the related documents.** On 50 documents, multi-document questions get 83% of their gold
  documents at 12,000 characters and 96% at 24,000 without any links. The neighbours add little that was missing.
- **Neighbour passages take room.** They are placed early, so they push out the first documents' own deeper
  passages. In the first single-document question, the gold document's passages in what the model reads fell from 8
  to 5 at 12,000 characters.
- **The next passage costs as much as it gains:** +1 fact at 24,000 characters, −13 at 12,000.

**Decision.** No default changes, and no test at 5,000 documents follows from this result.

**What this cannot show.** The idea's real case is where search cannot find the related document: on the
5,000-document memory bank, 131 of the 196 missed facts sat in documents outside the first 5. 50 documents is too few
for that. A test there would need three things:
- neighbours added after what search found, not before it;
- a larger reading budget (the read-more arm), so they add rather than replace;
- links used only for questions that ask across documents.

Files: `related50.py` (the run), `split.py` (single against multi-document questions), `results.json` (every arm,
the neighbour lists and their quality).

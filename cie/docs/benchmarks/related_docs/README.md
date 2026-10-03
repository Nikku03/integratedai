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

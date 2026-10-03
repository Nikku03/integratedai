# Entities and links instead of 1,000-character passages: a 5-document pilot

## Plan (written before any extraction, and before the questions about these documents were read)

**Question.** Suppose each document is turned, at load time and without any question, into entities and the links
between them. Each link carries what the connection is, when, its figures, and its conditions (void clauses,
exceptions, thresholds). Does that bring a question's answer facts to the model better than today's passages of about
1,000 characters?

**Documents.** Five documents from the 5,000-document memory bank (tenant `erbfull-5000-9688c2`):

| | document | source | characters | passages |
|---|---|---|---|---|
| 1 | `dsid_58bdb9f3bb4241e089f4f2b102765db4` | confluence | 14,466 | 15 |
| 2 | `dsid_7159e8c7b7a84c45aa51b71fdfc837fc` | linear | 6,838 | 11 |
| 3 | `dsid_a3f94972391244f38ef773c05926af83` | confluence | 15,880 | 17 |
| 4 | `dsid_e34b1f14719d45d98b175cb1351fb540` | slack | 12,504 | 13 |
| 5 | `dsid_fad07fd45c964078ba757dfd8d79ee51` | linear | 6,012 | 10 |

How they were chosen: from the gold-document ids of the development-half questions only, without reading any
question. Among sets of 5 documents, this set covers the most development-half questions that span more than one
document (2), then the most answer facts. Questions covered: every development-half question whose gold documents all
sit in the set (4 questions).

**Extraction (blind to questions).** One extractor per document, a strong LLM run as an agent. Each extractor is given
only that document's text and a fixed schema, and is told not to open any other file:
- entities: name, type, aliases, attributes;
- the company itself;
- links: from, relation, to, a description of 30 words at most in the extractor's own words, time, figures,
  conditions, status, source passage.

Entities with the same normalised name are then merged across the 5 documents.

**Retrieval at question time** (the question is used here, as in any search):
- **passages:** BM25 over the 66 passages;
- **graph lines:** each link and each entity's attributes rendered as one line, BM25 over the lines;
- **graph by entity:** the links of the entities the question names, ranked by BM25, then the other lines by BM25.

Each arm fills a budget of 3,000, 6,000 or 12,000 characters, or takes everything.

**Fact check.** A judge agent gets the question's answer facts (all of them, not only the lexically checkable ones),
every passage and every graph line. For each fact it lists the passages, and the sets of graph lines, that state it
fully, including every number, name and date. Paraphrase counts; partial does not. The judge sees the question only
after extraction is finished. Coverage at each budget is then computed from those lists. The evidence audit's lexical
check is reported beside it.

**Reported:**
- facts held at all (graph against passages);
- facts within each budget, for each arm;
- size of the graph against the documents;
- extraction tokens per document;
- facts the graph loses, by kind.

This is a pilot with 4 questions. No default changes on its result.

## Results (added after the run)

The documents are the benchmark's generated (fictional) company documents.

**The extraction.**
- 403 entities, 356 after merging names; 31 entities appear in two or more documents.
- 649 links: 176 carry a time, 106 carry figures, and 162 carry conditions.

**It lost nothing.** The judge found every one of the 41 answer facts in the graph, as it did in the passages. ("The
answer must not ..." facts were left out: they constrain an answer and no evidence can hold them.)

**It is bigger than the documents.**
- Rendered as lines, the graph is 167,000 characters against 61,000 for the passages (2.7 times).
- As JSON it is 255,000 characters (4.2 times).

**At the same reading budget, passages bring more facts to the model** (answer facts within the budget, of 41, as the
judge counts them):

| Budget | passages (BM25) | graph lines (BM25) | graph by entity | graph → its passages* |
|---|---|---|---|---|
| 3,000 characters | 9 | 8 | 9 | 12 |
| 6,000 characters | **30** | 11 | 14 | 26 |
| 12,000 characters | **32** | 18 | 16 | 29 |
| everything | 41 (61,000 characters) | 41 (167,000 characters) | 41 | — |

\* Added after the planned arms were scored, so it was not planned. It ranks graph lines as the graph-lines arm does,
maps each line to the passage it came from, and gives the model those passages (`kg_pointer.py`). With the entity
route instead, it scores 11, 25 and 26.

Per question (`results.json`):

| question | type | facts | passages at 6k / 12k | graph lines at 6k / 12k |
|---|---|---|---|---|
| qst_0269 | semantic | 15 | 14 / 15 | 7 / 8 |
| qst_0353 | project_related | 7 | 2 / 3 | 0 / 2 |
| qst_0385 | constrained | 10 | 5 / 5 | 3 / 4 |
| qst_0409 | constrained | 9 | 9 / 9 | 1 / 4 |

The evidence audit's lexical check, for reference, with everything given: 29 facts in the passages and 22 in the graph
lines. Lexical checks undercount the graph, because its lines paraphrase.

**Why the graph loses at equal size:**
- **More words for the same facts.** Every link repeats both entity names and the relation. Many links are low value
  ("X reviewed the postmortem").
- **Facts are split.** A fact often needs 2 to 4 lines: a threshold on one line, its unit and condition on another.
  Search ranks each line on its own, so the parts of one fact land far apart.
- **Search picks the wrong lines.** The lines that share the most words with the question are often descriptions of
  the entities it names, not the lines with the answer.

**Cost of the extraction.** It writes about 4 characters of JSON per character of document. At the 50,000-document
load's average document (about 6,000 characters), that is roughly 6,000 output tokens a document. For 512,000
documents, that is roughly 3 billion output tokens (an estimate; the price depends on the model).

**What this does not show.**
- **Only 4 questions and 41 facts.** This is a pilot.
- **One judge per question,** from the same model family as the extractor. Its close calls were applied the same way
  to passages and graph lines, and are noted in `judge/verdict_*.json`.
- **Questions that list or count across many documents** ("every incident involving X"). A graph can follow an
  entity's links into thousands of documents, and passage search cannot. None of these 4 questions needed that.

**Decision.** Passages stay the unit the model reads. The graph did not replace them at any budget. Used as a pointer
to passages, it was not better beyond 3,000 characters either.

Files:
- `graph/doc*.json`: the extractions;
- `judge/`: the tasks and verdicts;
- `kg_eval.py`: prepare, tasks and score;
- `kg_pointer.py`;
- `results*.json`;
- `meta.json`: the documents.

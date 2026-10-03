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

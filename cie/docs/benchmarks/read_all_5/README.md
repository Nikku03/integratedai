# A model reads all 5 documents: does it find every answer fact?

## Setup

- **Documents and questions.** The 5 documents and 4 questions of the entity-graph pilot (`../entity_graph/`): 63,000
  characters. The questions carry 41 facts to find and 11 "the answer must not ..." rules.
- **Reader.** A fresh agent that had not seen the expected answers (an LLM standing in for the answering model). It
  read only the 5 documents and `questions.json`, and wrote `answers.json`, citing document and section.
- **Grader.** A separate agent graded each expected fact against the answers (`grades.json`). I checked every
  partial grade against the documents.

## Result

| | facts |
|---|---|
| covered fully | **37 of 41** |
| covered partly | 4 |
| missed | 0 |
| contradicted | 0 |
| "must not" rules respected | **11 of 11** |

The reader never confused the incident with the other incidents the rules warn about.

**The 4 partial facts all come from one question** (qst_0353: "what baseline key, min samples and dedupe key should
we enforce"):
- **F1 and F6** (the baseline key and the dedupe key):
  - every field was listed;
  - but the answer gave the design standard's version (ADR-0142) alongside the postmortem's and the Slack thread's,
    without saying the standard is the one to enforce;
  - F1's "fixed, immutable baseline" was not stated in this answer.
- **F2** (region and capacity_tier optional): the answer used the document's own condition ("when variance requires
  it"). The benchmark words it as "only if separate baselines are explicitly maintained". This is a wording
  difference, not a miss.
- **F3** (labels to keep out of the key): prompt bucket and run ids were named; "route" was left out.

## What it shows

- **When the right documents are in front of it, a strong model finds the facts.** It covered 37 of 41 fully and
  missed none. The losses measured elsewhere come from the right documents not reaching the model (`../inside_bm25/`,
  `../missing_facts/`), not from reading.
- **The one weakness is judgement between sources.** Asked what to enforce, it listed three documents' versions side
  by side instead of choosing the standard. Telling the model which document type has authority (a standard or ADR
  over an incident thread) would address it.

## Limits

- 4 questions on 5 documents.
- The reader was given exactly the right documents, with no distractors: this measures reading, not search.
- The reader was not the answering model the product uses (ChatGPT). Its quality there is not measured.

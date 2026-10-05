# Does the memory bank beat plain search? What decides, fixed before the run

I wrote this on 2026-10-05, before any run with a real model. The only runs so far used a stand-in model that copies
the first key or date it sees, to check the plumbing, on 50 documents. The results go in `docs/MEMORY_TEST.md`.

## Why

On finding documents, the memory bank has not earned its size:
- Plain passages with search found 85.7% of the right documents in the top 10. The full memory bank, with its records
  and links, found 84.8%. Both used PostgreSQL full text.
- Since then, BM25 alone (85.3%) comes close to the bank's whole search (87.8%).

The bank is meant for questions that search over text does badly:
- **owners and status:** who owns, who is assigned, which status;
- **deadlines;**
- **lists:** everything assigned to a person, or due in a window;
- **conflicts:** a figure that changed.

This test asks those questions, the same way, through plain search and through the memory bank. It also tests whether
the facts Llama extracted help.

## Set-up (fixed)

**Data.** EnterpriseRAG-Bench's fictional company. The haystack is the 5,000 documents of the earlier runs (every gold
document of the 500 questions plus a sample stratified by source, seed 5), plus the gold documents of the metadata
questions: 5,089 documents.

**Questions: 243.** `python -m cie.eval.memory_test questions` makes them from the benchmark checkout. The deadlines
and lists are drawn at random with seed 7.

| group | n | where from | checked by |
|---|---|---|---|
| owners | 100 | the benchmark's metadata questions (`extra_questions.jsonl`) | code: the gold document's field value that the gold answer names (96 of 100 have one) must be in the answer's final line; the judge is reported too |
| deadlines | 70 | 40 Linear issues' due dates, and 30 meeting action items that name an owner and a due date | code: the date in the final line |
| lists | 53 | every Linear issue assigned to a person (15), with a given status (10), or due in a two-week window (8); every Jira ticket assigned to a person (10); every pull request by an author (10). From 2 to 10 items each | code: F1 of the keys or numbers in the final line |
| conflicts | 20 | the benchmark's conflicting_info questions | the judge (gpt-5.4-mini): correct 1, partly 0.5, wrong 0 |

**Arms.** Every arm gives the same model the same prompt, with at most 24,000 characters of evidence.

| arm | evidence |
|---|---|
| `plain-words` | BM25 over the raw documents, with every field written as "name: value", in 1,000-character passages |
| `plain` | the same passages, with BM25 and vector search fused by reciprocal rank |
| `bank` | the memory bank's own search with its defaults: BM25, vectors, records, graph and document expansion |
| `bank+facts` | the Llama fact lines that match the question (up to 6,000 characters), then the bank's search |
| `bank+lookup` | the model writes a lookup on the documents' fields (and the action items' owners and due dates), and the bank runs it. The matching records come first (up to 12,000 characters), then the bank's search. With no usable lookup, or nothing found, the bank's search alone |

**Model.** Llama 3.1 8B Instruct, bf16, vLLM, temperature 0, at most 400 output tokens. It writes the lookups and the
answers.

**Facts.** Llama 3.1 8B with the fast setting (8-bit weights, the short instructions, repeated text left out), over
every passage of the bank. The fact-extraction notebook's file is reused where its passages' text is identical.

## Scores

- A group's score is:
  - owners and deadlines: the share correct;
  - lists: the mean F1;
  - conflicts: the judge's mean.
- Differences between two arms are paired over the same questions. Each comes with a 95% bootstrap interval.
- The mean of the four groups is the mean of their differences. When the judge did not run, it is the mean of the three
  code-checked groups, and the report says so.

## Rules

1. **Structured lookup earns its place** if `bank+lookup` minus `plain` is at least +0.10 on deadlines or on lists.
   It must also be at least −0.03 on owners, and on conflicts when the judge ran.
2. **The bank's search earns its place** if `bank` minus `plain` is at least +0.03 on the mean of the groups.
3. **The Llama facts earn their place** if `bank+facts` minus `bank` is at least +0.05 on the mean of the groups.
   It must also be at least −0.03 on every group that has a result.
4. **Vector search earns its place in plain search** if `plain` minus `plain-words` is at least +0.03 on the mean.

A rule that needs a result that is missing is undecided. The decision is made on the point estimates. The intervals are
reported, and a decision whose interval includes zero is called "not clearly".

## What each outcome means

- **Rule 1 met:** keep the documents' fields as structured data, and build the lookup into the product's search.
- **Rule 2 not met:** the bank's records and graph do not help search. They are kept only if rule 1 or 3 needs them.
- **Rule 3 met:** store the Llama facts and search them. Not met: do not store them.
- **Rules 1, 2 and 3 all not met:** cut the memory bank down to plain search over the text, with permissions.

## Also reported

- each kind of question;
- the share of "not found" answers;
- prompt tokens;
- search time;
- how often the lookup fell back;
- storage for this haystack: the bank's rows and BM25 index, and plain search's passages, BM25 index and vectors.

Every result is reported, including failures.

## Known limits

- The data is one fictional company, and the questions are in English.
- The deadline and list questions follow templates.
- The benchmark's metadata questions each concern one document.
- The fields the expected answers come from are the ones the bank keeps as data. Plain search sees them as text.
  That difference is what is being tested.
- Conflicts have 20 questions, so their differences are rough.

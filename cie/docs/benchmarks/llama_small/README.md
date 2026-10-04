# Can a small Llama find or extract the facts? (Llama 3.2 3B, local CPU)

## Setup

The same 5 documents and 4 questions as `../read_all_5/`: 41 facts to find and 11 "must not" rules. The model is
Llama 3.2 3B in Ollama, on 4 CPU cores with no GPU.

Llama 3.1 8B could not be tried here: its 4.9 GB download does not fit in the 3.5 GB of free disk.

Two jobs were tested, each graded by a separate judge agent. Scripts take `PILOT_DIR`, the folder holding
`kg/docs/doc1-5.txt` and `read5/questions.json`.

## 1. Reading the 5 documents and answering (question time)

The instructions were the same as the strong model's in `../read_all_5/`. All 5 documents went in the prompt, about
14,100 tokens (`llama_read.py`, `answers_llama3b.json`, `grades_llama3b.json`).

| | Llama 3.2 3B | strong model (`../read_all_5/`) |
|---|---|---|
| facts covered fully (of 41) | **12** | 37 |
| covered partly | 8 | 4 |
| missed | 19 | 0 |
| contradicted | 2 | 0 |
| wrong claims from another incident or document | **10** | 0 |
| "must not" rules respected | 11 of 11 | 11 of 11 |

**By question, fully covered:**
- the sidebar spec: 8 of 15;
- baseline key and dedupe: 0 of 7;
- the paging storm: 4 of 10;
- the KMS incident: 0 of 9.

**On two questions it mixed documents:**
- it recommended adding `prompt_bucket` and `kernel_id` to the baseline key, which the documents forbid;
- it attributed the KMS incident to the perf-canary incident's causes and mitigation.

Its answers were short: 186 to 427 tokens, against about 1,000 for the strong model.

**Speed on this CPU:**
- 11.5 minutes for the first question;
- 1.5 to 3.5 minutes for each of the rest, which reused the documents already read;
- reading at about 44 tokens a second and writing at about 2.2.

## 2. Turning one document into facts, passage by passage (load time, no question)

Each of the sidebar document's 10 passages was sent alone, with an instruction to list every fact it states
(`llama_extract.py`). It produced 163 lines in 4.6 minutes (2,437 output tokens). The judge checked them against the
document and against the 15 facts of the sidebar question (`grades_extract3b.json`).

| | |
|---|---|
| expected facts held fully (of 15) | **10** |
| held partly | 4 |
| missed | 1 (the scope list in the first passage) |
| extracted lines that are correct | 100 |
| duplicates | 39 (mostly the same tags repeated) |
| **wrong** | **14** (a role reversed, tags misread, details invented) |
| preamble | 10 |

**Examples of wrong lines:**
- "Asha Nair assigned the Private Console" (she is the assignee);
- "small heatmaps" (the document rules heatmaps out);
- a recovery-window update on 2026-03-09 that no passage mentions.

## What it shows

- **Answering from long context is not good enough.** It covered 12 facts fully against the strong model's 37, and
  made 10 wrong claims, including confusing two incidents.
- **Short-passage extraction is much better, but not clean.** It kept 14 of 15 expected facts at least in part.
  Of the 153 fact lines, though, 14 were wrong (9%), including role reversals. That is usable only if every
  extracted fact stays linked to its passage, and answers quote the passage rather than the extracted line.
- **Speed: this is a GPU job.** On this CPU it takes about 5 minutes per 6,000-character document, far too slow for
  512,000 documents.

## Limits

- One document for the extraction, and 4 questions for the reading.
- One judge per job.
- 8B was not run. Earlier Colab runs found Llama 3.1 8B not good enough as the analyst; its extraction quality is not
  measured.

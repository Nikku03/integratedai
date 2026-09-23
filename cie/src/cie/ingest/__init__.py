"""Structured-source ingestion: turns exported company-system records (Slack threads,
email threads, tickets, pull requests, wiki pages, drive docs, CRM accounts, meeting
transcripts) into the full memory bank at bulk speed.

* ``sources``: read one exported record (repository JSON or plain text) into a
  normalised ``SourceDoc`` with its people, companies, project, identifiers,
  references to other documents, dates and tags.
* ``builder``: a pure function from ``SourceDoc`` to ``DocMemory``: field-aware
  sections, an extractive summary, tags, typed records (from structured list fields
  and the rule extractor), entity mentions. Runs in worker processes.
* ``bulk``: writes ``DocMemory`` batches through binary COPY, resolves entities and
  projects company-wide, links documents that cite each other, finds near-duplicate
  documents and the facts they disagree on, builds text and vector indexes.
"""

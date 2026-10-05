"""Text helpers for indexing: the keyword (tsvector) expressions and normalisation.

The memory bank does not store tsvectors. They were bigger than the text they index (1,292 bytes per section against
876 bytes of text on the 5,000-document bank). Each table has a GIN index on an expression that computes the tsvector
from the row's own text. The expression is an IMMUTABLE SQL function, the same in the index and in every query, so the
planner uses the index. Ranking (``ts_rank_cd``) computes the tsvector of the rows that matched.
"""

from __future__ import annotations

from sqlalchemy import func

# One function per table. Weights: a section's title A and text B; a record's summary and keywords A, detail B.
TSV_FUNCTIONS = {
    "cie_section_tsv": """CREATE OR REPLACE FUNCTION cie_section_tsv(title text, body text) RETURNS tsvector
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $f$
SELECT setweight(to_tsvector('english'::regconfig, coalesce(title, '')), 'A')
    || setweight(to_tsvector('english'::regconfig, left(coalesce(body, ''), 200000)), 'B')
$f$""",
    "cie_record_tsv": """CREATE OR REPLACE FUNCTION cie_record_tsv(summary text, keywords character varying[], detail text) RETURNS tsvector
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $f$
SELECT setweight(to_tsvector('english'::regconfig, coalesce(summary, '')), 'A')
    || setweight(to_tsvector('english'::regconfig, coalesce(array_to_string(keywords, ' '), '')), 'A')
    || setweight(to_tsvector('english'::regconfig, left(coalesce(detail, ''), 20000)), 'B')
$f$""",
    "cie_facts_tsv": """CREATE OR REPLACE FUNCTION cie_facts_tsv(body text) RETURNS tsvector
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $f$
SELECT to_tsvector('english'::regconfig, coalesce(body, ''))
$f$""",
}
# the GIN index of each table, by table name: its statistics give the lexeme frequencies (cie.retrieval.lexical)
TSV_INDEX = {"sections": "ix_sections_tsv", "memory_records": "ix_records_tsv", "section_facts": "ix_section_facts_tsv"}


def tsv_of(model):
    """The tsvector expression of a table's rows, exactly as its GIN index is defined."""
    name = model.__tablename__
    if name == "sections":
        return func.cie_section_tsv(model.title, model.text)
    if name == "memory_records":
        return func.cie_record_tsv(model.summary, model.keywords, model.detail)
    if name == "section_facts":
        return func.cie_facts_tsv(model.text)
    raise ValueError(f"no keyword index on {name}")


def normalise_query(q: str) -> str:
    return " ".join(q.split())

"""Text helpers for indexing: tsvector expressions and normalisation."""

from __future__ import annotations

from sqlalchemy import func, literal_column


def tsvector_expr(title: str | None, body: str):
    """Weighted tsvector: title 'A', body 'B'. Postgres 'english' config."""
    body = (body or "")[:200_000]
    expr = func.setweight(func.to_tsvector(literal_column("'english'"), body), literal_column("'B'"))
    if title:
        expr = func.setweight(func.to_tsvector(literal_column("'english'"), title), literal_column("'A'")).op("||")(expr)
    return expr


def normalise_query(q: str) -> str:
    return " ".join(q.split())

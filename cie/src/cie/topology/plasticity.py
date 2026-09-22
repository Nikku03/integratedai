"""Spike-timing-dependent plasticity, translated: links that carried activity to
records the answer used are potentiated (LTP), links that recruited records the
answer did not use are depressed (LTD). Learning re-routes the source-to-sink
pathways: the next stimulus on the same tissue recruits the useful cliques first.

Weights stay in [floor, cap]; each update moves a weight a fraction of the way
towards the bound, so repeated confirmation saturates instead of exploding.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from cie.core.models import RecordLink


def stdp_update(session: Session, fired: list[uuid.UUID], traversed: list[tuple[uuid.UUID, uuid.UUID]], *,
                ltp: float = 0.15, ltd: float = 0.05, cap: float = 3.0, floor: float = 0.05) -> dict[str, Any]:
    """``fired``: records the output used (cited or top of the packet); ``traversed``:
    (from, to) pairs recruitment walked. Returns counts and the previous weights of
    every link touched, so an experiment can restore them."""
    fired_set = set(fired)
    if not fired_set:
        return {"potentiated": 0, "depressed": 0, "previous": {}}
    ids = list(fired_set | {a for a, _ in traversed} | {b for _, b in traversed})
    links = list(session.scalars(select(RecordLink).where(or_(RecordLink.src_id.in_(ids), RecordLink.dst_id.in_(ids)))))
    walked = {frozenset(p) for p in traversed}
    previous: dict[str, float] = {}
    pot = dep = 0
    for link in links:
        pair = frozenset((link.src_id, link.dst_id))
        if link.src_id in fired_set and link.dst_id in fired_set:
            previous[str(link.id)] = float(link.weight)
            link.weight = float(link.weight) + ltp * (cap - float(link.weight))
            pot += 1
        elif pair in walked and not (link.src_id in fired_set and link.dst_id in fired_set):
            previous[str(link.id)] = float(link.weight)
            link.weight = float(link.weight) - ltd * (float(link.weight) - floor)
            dep += 1
    session.flush()
    return {"potentiated": pot, "depressed": dep, "previous": previous}


def restore(session: Session, previous: dict[str, float]) -> int:
    """Put the weights back (experiments must leave the bank as they found it)."""
    if not previous:
        return 0
    ids = [uuid.UUID(k) for k in previous]
    n = 0
    for link in session.scalars(select(RecordLink).where(RecordLink.id.in_(ids))):
        link.weight = previous[str(link.id)]
        n += 1
    session.flush()
    return n

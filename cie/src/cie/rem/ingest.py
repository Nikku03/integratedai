"""Source records -> typed graph.

A bundle names scopes, source documents (kept in the immutable vault, extracted into sections by the existing
pipeline), the passages and claims those documents contain, business records from systems of record, their
relationships and exact stock quantities. Loading a bundle is itself a change event, so it is versioned,
idempotent and passes through the rules (for example R0, which records conflicts between claims and records).

Every passage node points at the exact place it came from: document id, section id, page, character span within
the section and the quoted text. Claims are linked to the passage that states them. In this bundle format claims
are annotated by hand (``extracted_by: annotation``); a claim proposed by a model extractor is marked
``extracted_by: model``, and its link to the passage is then a model-inferred hypothesis until verified.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cie.core.models import Document, ScopeKind, Section
from cie.memory.scopes import create_scope
from cie.rem.budget import est_tokens
from cie.rem.change import process_event, submit_event

NODE_ORDER = {"company": 0, "department": 1, "project": 2, "team": 3}


def ensure_scopes(session: Session, tenant_id: uuid.UUID, scopes: list[dict[str, Any]]) -> dict[str, uuid.UUID]:
    out: dict[str, uuid.UUID] = {}
    for s in scopes:
        parent = out.get(s.get("parent")) if s.get("parent") else None
        sc = create_scope(session, tenant_id, ScopeKind(s["kind"]), s["name"], parent)
        out[s["name"]] = sc.id
    session.flush()
    return out


def _locate(session: Session, document: Document, quote: str) -> dict[str, Any]:
    secs = session.scalars(select(Section).where(Section.document_id == document.id).order_by(Section.order_index)).all()
    for s in secs:
        i = s.text.find(quote)
        if i >= 0:
            return {"document_id": str(document.id), "section_id": str(s.id), "page": s.page_start, "char_start": i,
                    "char_end": i + len(quote), "quote": quote, "sha256": document.sha256 if hasattr(document, "sha256") else None}
    raise ValueError(f"quote not found in {document.original_filename!r}: {quote[:60]!r}")


def store_document(session: Session, tenant_id: uuid.UUID, doc: dict[str, Any], scope_id: uuid.UUID, *, vault, embedder) -> Document:
    """Put a text document in the vault and extract it with the standard pipeline (idempotent by content hash)."""
    from cie.extraction.pipeline import run_extraction

    res = vault.ingest(session, tenant_id=tenant_id, data=doc["text"].encode(), filename=f"{doc['key']}.txt", scope_id=scope_id,
                       source=doc.get("source_system", "upload"), title=doc.get("title"), doc_type=doc.get("doc_type"),
                       sensitivity=int(doc.get("sensitivity", 1)), media_type="text/plain", extra={"rem_key": doc["key"]})
    d = res.document
    if d.status != "indexed":
        run_extraction(session, d, vault=vault, embedder=embedder)
    return d


def document_ops(session: Session, tenant_id: uuid.UUID, doc: dict[str, Any], d: Document) -> list[dict[str, Any]]:
    from cie.core.models import Blob

    blob = session.get(Blob, d.blob_id)
    root = f"doc:{blob.sha256[:16]}" if blob is not None else f"doc:{d.id}"
    common = {"scope": doc["scope"], "sensitivity": int(doc.get("sensitivity", 1)), "project_keys": doc.get("project_keys", []),
              "department_keys": doc.get("department_keys", []), "root_sources": [root]}
    ops = [{"op": "upsert_node", "type": "document", "key": doc["key"], "name": doc.get("title", doc["key"]),
            "summary": doc.get("summary", doc["text"][:200]),
            "attrs": {"source_system": doc.get("source_system", "document"), "source_date": doc.get("date"), "doc_type": doc.get("doc_type"),
                      "tokens": est_tokens(doc["text"])},
            "source_pointers": [{"document_id": str(d.id), "filename": d.original_filename, "sha256": blob.sha256 if blob else None}],
            "verification": doc.get("verification", "unverified"), **common}]
    for i, p in enumerate(doc.get("passages", [])):
        ptr = _locate(session, d, p["quote"])
        pkey = p.get("key", f"{doc['key']}#p{i + 1}")
        ops.append({"op": "upsert_node", "type": "passage", "key": pkey, "name": p.get("title", f"{doc.get('title', doc['key'])} ¶{i + 1}"),
                    "summary": p["quote"], "attrs": {"source_system": doc.get("source_system", "document"), "source_date": doc.get("date")},
                    "source_pointers": [ptr], "verification": doc.get("verification", "unverified"), **common})
        ops.append({"op": "upsert_edge", "src": ["passage", pkey], "kind": "derived_from", "dst": ["document", doc["key"]],
                    "source_pointers": [ptr]})
        for subj in p.get("supports", []):
            ops.append({"op": "upsert_edge", "src": ["passage", pkey], "kind": "supports", "dst": subj, "source_pointers": [ptr]})
    for i, c in enumerate(doc.get("claims", [])):
        ptr = _locate(session, d, c["quote"])
        ckey = c.get("key", f"{doc['key']}#c{i + 1}")
        pkey = c.get("passage") or f"{ckey}:passage"
        if not c.get("passage"):
            ops.append({"op": "upsert_node", "type": "passage", "key": pkey, "name": f"{doc.get('title', doc['key'])} (claim source)",
                        "summary": c["quote"], "attrs": {"source_system": doc.get("source_system", "document"), "source_date": doc.get("date")},
                        "source_pointers": [ptr], **common})
            ops.append({"op": "upsert_edge", "src": ["passage", pkey], "kind": "derived_from", "dst": ["document", doc["key"]],
                        "source_pointers": [ptr]})
        model = c.get("extracted_by") == "model"
        ops.append({"op": "upsert_node", "type": "claim", "key": ckey, "name": c.get("name", f"Claim in {doc.get('title', doc['key'])}"),
                    "summary": c["quote"], "attrs": {"subject_type": c["subject"][0], "subject_key": c["subject"][1], "attr": c["attr"],
                                                     "value": c["value"], "stated_on": c.get("stated_on", doc.get("date")),
                                                     "source_system": doc.get("source_system", "document")},
                    "source_pointers": [ptr], "verification": "unverified", **common})
        ops.append({"op": "upsert_edge", "src": ["claim", ckey], "kind": "derived_from", "dst": ["passage", pkey],
                    "provenance": "inferred" if model else "explicit", "source_pointers": [ptr],
                    "derivation": {"extracted_by": c.get("extracted_by", "annotation")} if model else None})
    return ops


def bundle_ops(session: Session, tenant_id: uuid.UUID, bundle: dict[str, Any], *, vault, embedder,
               scope_ids: dict[str, uuid.UUID]) -> list[dict[str, Any]]:
    nodes = sorted(bundle.get("nodes", []), key=lambda n: NODE_ORDER.get(n["type"], 9))
    ops = [{"op": "upsert_node", **n} for n in nodes]
    for doc in bundle.get("documents", []):
        d = store_document(session, tenant_id, doc, scope_ids[doc["scope"]], vault=vault, embedder=embedder)
        ops += document_ops(session, tenant_id, doc, d)
    ops += [{"op": "upsert_edge", **e} for e in bundle.get("edges", [])]
    ops += [{"op": "set_stock", **s} for s in bundle.get("stock", [])]
    return ops


def ingest_bundle(session: Session, tenant_id: uuid.UUID, bundle: dict[str, Any], *, vault, embedder, name: str = "bundle",
                  principal_id: uuid.UUID | None = None) -> dict[str, Any]:
    """Load a bundle as one idempotent change event and process it. Returns the event summary."""
    scope_ids = ensure_scopes(session, tenant_id, bundle.get("scopes", []))
    ops = bundle_ops(session, tenant_id, bundle, vault=vault, embedder=embedder, scope_ids=scope_ids)
    digest = hashlib.sha256(json.dumps(bundle, sort_keys=True, default=str).encode()).hexdigest()[:16]
    ev, _ = submit_event(session, tenant_id, kind="ops", payload={"ops": ops}, idempotency_key=f"ingest:{name}:{digest}",
                         principal_id=principal_id)
    summary = process_event(session, ev.id, embedder=embedder)
    return {"event_id": str(ev.id), **summary}

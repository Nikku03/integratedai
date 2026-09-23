"""Read exported company-system records into a normalised ``SourceDoc``.

Two layouts are supported:

* the structured export (one JSON object per record, e.g. the EnterpriseRAG-Bench
  repository): ``title_field_name`` / ``content_field_names`` name the title and body
  fields, every other field is metadata;
* a plain-text export (``dsid_<id>__<slug>.txt``: title on the first line, body after):
  no metadata, so only the text feeds the memory.

Field roles (people, companies, project, identifiers, references, tags, dates) are
declared per field name, not per source, because the same systems use the same names
(``assignee``, ``labels``, ``linked_issues``). Generation or export artefacts that a
real system would not have (``original_location``, ``dataset_noise_document``,
``file_path`` and friends) are dropped so they can never steer retrieval.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SOURCES = ["slack", "gmail", "linear", "google_drive", "hubspot", "fireflies", "github", "jira", "confluence"]

# export/generation artefacts: never metadata
ARTEFACT_FIELDS = {"title_field_name", "content_field_names", "dataset_doc_uuid", "dataset_noise_document", "original_location",
                   "file_path", "file_name", "filename", "filename_hint", "thread_filename", "_meta", "__meta_schema_version",
                   "file_notes", "file_type", "file_version", "encoding", "recording_notes"}
PEOPLE_FIELDS = {"author": "author", "owner": "owner", "creator": "creator", "assignee": "assignee", "reporter": "reporter",
                 "mailbox_owner": "mailbox owner", "redwood_owner": "owner", "se_assigned": "solutions engineer",
                 "csm_assigned": "customer success manager", "account_owner": "account owner", "primary_contact": "customer contact",
                 "reviewers": "reviewer", "collaborators": "collaborator", "participants_internal": "participant",
                 "participants_external": "external participant", "redwood_attendees": "attendee", "customer_attendees": "customer attendee",
                 "stakeholders": "stakeholder", "participants": "participant"}
ORG_FIELDS = ("customer_company", "related_account", "company_name")
PROJECT_FIELDS = ("project",)  # a Linear project; a Jira "project" is a queue (tagged, see below)
PROJECT_SOURCES = {"linear"}
DATE_CREATED = ("created_at", "created", "first_email_at", "recorded_at", "first_message_ts")
DATE_UPDATED = ("updated_at", "last_updated", "last_modified", "last_email_at", "last_message_ts", "merged_at", "last_activity_at")
TAG_LIST_FIELDS = ("labels", "tags", "components", "topics", "use_cases", "interested_products", "security_requirements",
                   "deployment_requirements", "affected_regions", "affected_models", "competitors_mentioned", "competitors")
TAG_SCALAR_FIELDS = ("status", "priority", "severity", "stage", "call_type", "thread_type", "issue_type", "doc_type", "team",
                     "owner_team", "space", "channel", "project", "industry", "customer_tier", "account_tier", "confidentiality",
                     "state", "repo", "drive_area", "region", "environment", "release", "ci_status", "hq_region")
# references to other documents: (field, link kind)
REF_FIELDS = {"dependencies": "depends_on", "parent_issue": "depends_on", "linked_issues": "references", "sub_issues": "references",
              "linked_linear": "references", "linked_jira": "references", "linked_support_tickets": "references",
              "related_links": "references", "linked_artifacts": "references", "links": "references",
              "related_github_prs": "references", "related_confluence_pages": "references", "related_pages": "references",
              "linked_gmail_threads": "references", "linked_fireflies": "references", "linked_drive_docs": "references",
              "crm_account_id": "references", "related_incident_id": "references", "attachments": "references"}
TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d{2,7})\b")
PR_URL_RE = re.compile(r"github\.com/[\w.-]+/([\w.-]+)/pulls?/(\d+)", re.I)
SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass
class SourceDoc:
    dsid: str | None
    source: str
    rel: str
    title: str
    fields: list[tuple[str, str]]  # (field label, text) in order: the body
    meta: dict[str, Any] = field(default_factory=dict)  # raw metadata (lists kept)
    created: datetime | None = None
    updated: datetime | None = None
    people: list[tuple[str, str]] = field(default_factory=list)  # (display name, role)
    orgs: list[str] = field(default_factory=list)
    project: str | None = None
    keys: list[str] = field(default_factory=list)  # identifiers other documents can cite this one by
    refs: list[tuple[str, str]] = field(default_factory=list)  # (identifier, link kind)
    tags: list[str] = field(default_factory=list)
    sensitivity: int = 1

    @property
    def body(self) -> str:
        return "\n\n".join(t for _, t in self.fields if t)


# ------------------------------------------------------------------ helpers
def slug(s: str) -> str:
    return SLUG_RE.sub("-", str(s).lower()).strip("-")


def tag(s: Any) -> str | None:
    t = slug(str(s))[:40].strip("-")
    return t if t and not t.isdigit() and t not in ("none", "null", "n-a", "na", "true", "false") else None


def as_list(v: Any) -> list[Any]:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("[") and s.endswith("]"):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return parsed
            except ValueError:
                pass
        return [s] if s else []
    return [v]


def text_of(v: Any) -> str:
    """A field value as readable text: lists become bullet lines, escaped newlines are unescaped."""
    if v is None:
        return ""
    if isinstance(v, list):
        return "\n".join(f"- {text_of(x)}" for x in v if x not in (None, ""))
    if isinstance(v, dict):
        return "\n".join(f"{k}: {text_of(x)}" for k, x in v.items())
    return str(v).replace("\\n", "\n").replace("\\t", " ").strip()


_ROLE_PAREN = re.compile(r"\s*[\(\[].*?[\)\]]\s*")
_EMAIL = re.compile(r"<[^>]+>|\S+@\S+")


def person_name(raw: Any) -> str | None:
    """'Priya Nair (Solutions Engineer)' -> 'Priya Nair'; 'kimberly_park' -> 'Kimberly Park';
    'Julia Park <julia@x.com>' -> 'Julia Park'. Single tokens and non-names are rejected."""
    s = str(raw or "").strip()
    if not s or len(s) > 80:
        return None
    s = _EMAIL.sub(" ", s)
    s = _ROLE_PAREN.sub(" ", s)
    s = s.split(" - ")[0].split(",")[0].strip(" -:")
    if re.fullmatch(r"[a-z]+[_.][a-z]+", s):
        s = " ".join(p.capitalize() for p in re.split(r"[_.]", s))
    toks = s.split()
    if not 2 <= len(toks) <= 4 or any(any(ch.isdigit() for ch in t) for t in toks):
        return None
    if not all(t[0].isupper() for t in toks if t[0].isalpha()):
        return None
    return " ".join(toks)


def org_name(raw: Any) -> str | None:
    s = str(raw or "").strip()
    if not s or len(s) > 80 or s.lower() in ("none", "n/a", "unknown"):
        return None
    if s.startswith("hubspot-company-"):
        s = s[len("hubspot-company-"):].replace("-", " ").title()
    return s


def parse_when(v: Any) -> datetime | None:
    if v in (None, ""):
        return None
    s = str(v).strip()
    if s.isdigit() and 9 <= len(s) <= 11:  # epoch seconds (Slack ts)
        try:
            return datetime.fromtimestamp(int(s), tz=UTC)
        except (ValueError, OverflowError, OSError):
            return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            d = datetime.strptime(s[:25] if "%z" in fmt else s[:19] if " " in fmt or "T" in fmt else s[:10], fmt)
            return d if d.tzinfo else d.replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except ValueError:
        return None


def infer_source(rel: str, keys: set[str]) -> str:
    head = rel.split("/")[0]
    if head in SOURCES:
        return head
    hints = [("channel", "slack"), ("thread_ts", "slack"), ("mailbox_owner", "gmail"), ("pr_number", "github"), ("meeting_id", "fireflies"),
             ("space", "confluence"), ("drive_area", "google_drive"), ("issue_type", "jira"), ("cycle", "linear"), ("company_domain", "hubspot")]
    for f, src in hints:
        if f in keys:
            return src
    return "unknown"


def own_keys(source: str, rel: str, meta: dict[str, Any]) -> list[str]:
    """Identifiers by which other documents cite this one."""
    out = []
    if meta.get("key"):
        out.append(str(meta["key"]).upper())
    if source == "github" and meta.get("pr_number"):
        if meta.get("repo"):
            out.append(f"pr:{slug(meta['repo'])}#{meta['pr_number']}")
        out.append(f"pr:#{meta['pr_number']}")
    for k in ("meeting_id", "thread_id", "company_id", "crm_deal_id", "deal_id"):
        if meta.get(k):
            out.append(f"id:{str(meta[k]).lower()}")
    if source == "hubspot" and meta.get("company_name"):
        out.append(f"id:hubspot-company-{slug(meta['company_name'])}")
    stem = Path(rel).stem
    if stem.startswith("dsid_") and "__" in stem:
        stem = stem.split("__", 1)[1]
    if source in ("confluence", "google_drive"):
        out.append(f"page:{slug(stem)}")
    return list(dict.fromkeys(out))


def reference_keys(field_name: str, value: Any) -> list[str]:
    """Identifiers cited by one metadata field."""
    out = []
    for item in as_list(value):
        s = str(item)
        out += [m.upper() for m in TICKET_RE.findall(s)]
        out += [f"pr:{slug(r)}#{n}" for r, n in PR_URL_RE.findall(s)]
        if field_name in ("related_pages", "related_confluence_pages", "linked_drive_docs") or ("/" in s and "github.com" not in s and "atlassian" not in s):
            last = s.rstrip("/").split("/")[-1].split("?")[0]
            last = re.sub(r"\.(json|pdf|xlsx|docx|md)$", "", last, flags=re.I)
            if len(last) > 6 and "-" in last:
                out.append(f"page:{slug(last)}")
        if field_name in ("crm_account_id", "linked_gmail_threads", "linked_fireflies", "related_incident_id") and s.strip():
            out.append(f"id:{s.strip().lower()}")
    return out


# ------------------------------------------------------------------ readers
def read(path: Path, rel: str) -> SourceDoc:
    return read_txt(path, rel) if path.suffix == ".txt" else read_json(path, rel)


def read_txt(path: Path, rel: str) -> SourceDoc:
    raw = path.read_text(errors="replace")
    stem = path.stem
    dsid = stem.split("__", 1)[0] if stem.startswith("dsid_") else None
    lines = raw.strip().splitlines()
    title = lines[0].strip() if lines else stem
    body = "\n".join(lines[1:]).replace("\\n", "\n").strip()
    source = infer_source(rel, set())
    return SourceDoc(dsid=dsid, source=source, rel=rel, title=title, fields=[("body", body)], keys=own_keys(source, rel, {}),
                     tags=[t for t in [tag(source)] if t])


def read_json(path: Path, rel: str) -> SourceDoc:
    d = json.loads(path.read_text(errors="replace"))
    title_field = d.get("title_field_name") or "title"
    content_fields = list(d.get("content_field_names") or [])
    if not content_fields:  # fall back to the long text fields
        content_fields = [k for k, v in d.items() if isinstance(v, str) and len(v) > 200 and k not in ARTEFACT_FIELDS and k != title_field]
    title = text_of(d.get(title_field)) or Path(rel).stem
    fields = [(f, text_of(d.get(f))) for f in content_fields if d.get(f) not in (None, "", [])]
    meta = {k: v for k, v in d.items() if k not in ARTEFACT_FIELDS and k not in content_fields and k != title_field}
    source = infer_source(rel, set(d))
    doc = SourceDoc(dsid=d.get("dataset_doc_uuid"), source=source, rel=rel, title=title[:500], fields=fields, meta=meta)
    # people
    seen = set()
    for f, role in PEOPLE_FIELDS.items():
        for item in as_list(meta.get(f)):
            n = person_name(item)
            if n and n.lower() not in seen:
                seen.add(n.lower())
                doc.people.append((n, role))
    # companies
    for f in ORG_FIELDS:
        n = org_name(meta.get(f))
        if n and n not in doc.orgs:
            doc.orgs.append(n)
    if meta.get("crm_account_id") and not doc.orgs:
        n = org_name(meta["crm_account_id"])
        if n:
            doc.orgs.append(n)
    # project
    if source in PROJECT_SOURCES:
        for f in PROJECT_FIELDS:
            if meta.get(f):
                doc.project = str(meta[f])[:120]
    # dates
    doc.created = next((w for w in (parse_when(meta.get(k)) for k in DATE_CREATED) if w), None)
    doc.updated = next((w for w in (parse_when(meta.get(k)) for k in DATE_UPDATED) if w), None)
    # identifiers and references
    doc.keys = own_keys(source, rel, meta)
    own = set(doc.keys)
    refs: dict[str, str] = {}
    for f, kind in REF_FIELDS.items():
        if f in meta:
            for k in reference_keys(f, meta[f]):
                if k not in own:
                    refs.setdefault(k, kind)
    # ticket keys cited in the body are references too (weaker, resolved the same way)
    for k in TICKET_RE.findall(doc.body[:20000]):
        if k.upper() not in own:
            refs.setdefault(k.upper(), "mentions_key")
    doc.refs = list(refs.items())[:40]
    # tags
    tags: list[str] = []
    for f in TAG_LIST_FIELDS:
        tags += [t for t in (tag(x) for x in as_list(meta.get(f))) if t]
    for f in TAG_SCALAR_FIELDS:
        if meta.get(f) not in (None, "", []) and not isinstance(meta.get(f), list):
            t = tag(meta[f])
            if t:
                tags.append(t)
    tags.append(source)
    # the title field of some systems carries a role of its own: a CRM record's title is the company, a chat thread's is its channel
    if source == "hubspot":
        name = org_name(title)
        if name and name not in doc.orgs:
            doc.orgs.insert(0, name)
        if name:
            doc.keys.append(f"id:hubspot-company-{slug(name)}")
    if source == "slack":
        t = tag(title)
        if t:
            tags.insert(0, t)
    conf = str(meta.get("confidentiality") or meta.get("visibility") or "").lower()
    doc.sensitivity = 2 if conf in ("restricted", "confidential", "secret", "team-only") else 1
    doc.tags = list(dict.fromkeys(tags))[:30]
    return doc

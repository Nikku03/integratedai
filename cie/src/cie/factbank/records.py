"""Counts, filters, history, email and chat over the fact bank (the company brain, v16).

v15's routes read one document's fields, follow links between documents and quote passages. Four kinds of question fall
outside them: how many documents of a system hold given field values ("How many Jira tickets have priority P2?"), which
ones or whose they are ("Which Linear issues in cycle 2026-W10 have status Done? Give the keys."), what a document's own
history says (when it was opened, last updated, merged, moved to a status; who left the first comment), and what an email
or a chat thread says about itself (who sent the first email, who was copied, how many messages, which channel). ``Records``
answers them from the bank alone, never from the raw documents:

* the documents' fields are the bank's facts (one per value; a list field one per item, up to 40 items of 300 characters);
* a document's text is the bank's stored text (``entities_fts``: title, fields, then the content fields such as comments,
  timelines and Gmail messages, headers first), cut into units: lines, and the items of a list written as one line.

``Records(bank)`` gives four things. Each returns None when it does not apply, so the brain falls through to v15's routes:

1. ``start(question)``: the one document the question names: a ticket key, a pull request number, a quoted title (a
   Gmail subject with or without its "Re:"), or a quote of a document's words (a Slack thread's first words) that exactly one
   document's text holds.
2. ``table(question)``: counts and filters over one system's documents. The system is named ("Jira", "HubSpot", "email") or
   implied by an item noun (tickets, issues, accounts, pages, docs, meetings, threads, pull requests). The conditions are field
   values the question writes as whole words, matched against the values the system's documents hold in short fields with
   one value per document (not identifiers, not dates) or in person fields. A value written inside a longer matched value,
   or inside a field's name ("doc" in "doc type sheet"), does not count. The pointing words closest to a value (a field's cue
   or name words, ``FIELD_CUES``, the verbs that name a role; ``pointers``), leaving out a word closer to another value, say
   which field holds it: "owned by Maya Chen and with Arjun Patel as the solutions engineer". When they name only fields that
   do not hold it, the question is not one ``table`` can read ("high-priority Linear issues": high is a customer impact).
   With no such word, the whole question's words decide (``cue_score``). A short, numeric or generic value needs a word
   pointing to its field. Values that differ only in spaces or punctuation are one ("HeliosHealth", "Helios Health"), except
   a person's name ("Liam Oconnor" is not "Liam O'Connor"); accents count ("Martínez" is not "Martinez"). A "not" negates the
   value it comes before (within three words) and the values of the same field listed after it ("not Resolved or Closed",
   "not assigned to X", "not in cycle C"); a "not" before no value leaves the question to v15. "open" means a status other
   than the closed ones (Jira: Resolved, Closed; Linear: Done, Canceled), or other than the ones the question lists after
   "not"; for a system without closed statuses (HubSpot accounts) it means nothing ``table`` can count. Every other word of
   the question must be a question word, a filler, a system or item noun, or a word of (or pointing to) a matched or asked
   field; otherwise the question asks something more (an order, a date window, a deadline, a field no value names: "How
   many P1 tickets have an assignee?") and ``table`` leaves it to v15. A list question must ask for documents: say keys or
   titles, or have its "which" govern an item noun ("Which open Jira tickets…", not "Which team owns…"). Answers: the count
   ("12", the documents as evidence), the keys (or titles), or the people a person field holds over the matched documents
   ("Who is assigned issues in the Linear project P?").
3. ``derived(question, start)``: the history and messages of the one named document: its created or opened date, its last
   updated date, the days from opened to merged (a pull request), who left the first comment and when the latest comment was
   posted (dated entries "YYYY-MM-DD[ HH:MM][ -] Name[ (role)]: text"), the first recorded activity (a HubSpot timeline), the
   date it moved to a status ("moved to S", "changed status to S", "marking as S"), a Gmail thread's first sender, its To and
   Cc (or how many), message count, attachments (joined by "; ": file names hold commas), account and start date, and a
   Slack thread's channel and the person who started it. A question that follows a link from the named document ("When was
   the parent issue of ENG-1 created?", "the Linear issue behind PR #n": ``plans.LINK_WORDS`` and ``LINK_PHRASES``, but the
   words its own questions use, ``DERIVED_OWN``) asks about another document and is not one.
4. ``absent(question, start)``: the field the question asks for (``relevance``: the bank's cue weights, ``FactBank.wanted``,
   and ``FIELD_CUES``, at least ``MIN_ASK``, ahead of every other field) is one the system uses (held by ``min_held`` of its
   documents, ``MIN_HELD`` = 0.3 by default) with one short value per document (``askable``), but this document's is empty,
   missing, "TBD" or "N/A", and its text holds none of the field's values on a line of its own (``written_bare``): the reason
   ("the HubSpot account X has no CSM assigned"), and the brain answers "not found". A question that follows a link ("the
   parent issue of…", ``plans.LINK_WORDS``), counts, or asks for the document's history (``derived``'s kinds) is not one.

What the bank cannot show, ``Records`` cannot either: a field some documents write as a content field (its value in the text
with no field name) has no fact there. On the train draw those are list and text fields (a HubSpot next step and blockers,
a meeting's topics, next steps and action items), which ``absent`` never calls missing, and two Linear customer impacts
written as a bare line ("medium"), which ``written_bare`` finds; a value written inside a sentence still reads as missing.
"""

from __future__ import annotations

import ast
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from cie.factbank.engine import CUES, STOP, FactBank, stem, systems_in
from cie.factbank.plans import LINK_PHRASES, LINK_WORDS, QUOTED, unquoted

TICKET = re.compile(r"\b([A-Z][A-Z0-9]{1,9})-(\d{1,7})\b")
PR_NUMBER = re.compile(r"(?:(?<![\w&#])#|\b(?:PR|pull request)\s*[#-]?\s*)(\d{2,7})\b", re.I)
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EMPTY_VALUES = frozenset(("", "none", "null", "nil", "n/a", "na", "tbd", "tba", "unknown", "-", "--", "[]", "{}", "unassigned",
                          "not assigned", "not set", "no csm", "none assigned"))
# the item nouns that imply a system when none is named, and the systems a plain "tickets" or "issues" may mean
ITEM_SYSTEMS = {"ticket": ("jira", "linear"), "issue": ("linear", "jira"), "account": ("hubspot",), "page": ("confluence",),
                "doc": ("google_drive",), "document": ("google_drive",), "meeting": ("fireflies",), "call": ("fireflies",),
                "thread": ("gmail",), "email": ("gmail",), "pr": ("github",), "pull": ("github",)}
ITEM_WORDS = frozenset(("ticket", "tickets", "issue", "issues", "account", "accounts", "page", "pages", "doc", "docs", "document",
                        "documents", "meeting", "meetings", "call", "calls", "thread", "threads", "email", "emails", "mail", "mails",
                        "pr", "prs", "pull", "request", "requests", "record", "records", "item", "items", "deal", "deals",
                        "company", "companies", "mailbox", "inbox", "repository", "repo"))
SYSTEM_NAME_WORDS = frozenset(("jira", "linear", "hubspot", "confluence", "google", "drive", "fireflies", "github", "gmail", "slack"))
# words a count or list question may hold besides its conditions
FILLER = frozenset("""how many number count total what which who whom whose list give show tell name names me us please just only
    are is was were be been being there have has had does do did currently right now still exactly altogether overall in on of for to
    at by with from about under within into as and or the a an all every each any their them they its it this that these those s
    keys key ids id numbers identifiers titles people person persons everyone everybody someone anyone set marked listed labelled
    labeled tagged assigned owned own owns created reported authored written wrote opened filed raised handled sent belong belongs
    belonging held hold holds get gets so far today can could would you recorded side relate relates related concern concerns
    concerning""".split())
CLOSED = {"jira": frozenset(("resolved", "closed", "done", "cancelled", "canceled", "won't fix", "wontfix")),
          "linear": frozenset(("done", "canceled", "cancelled", "duplicate"))}
# words that point to a field beyond its own name (whole-word patterns, lower case); each adds CUE_WEIGHT to the field
FIELD_CUES = {
    "csm_assigned": (r"\bcsm\b", r"\bcustomer success(?: managers?)?\b"), "se_assigned": (r"\bse\b", r"\bsolutions? engineers?\b"),
    "forecast_close_month": (r"\bclos(?:e|es|ing)\b", r"\bforecast\w*\b"),
    "due_date": (r"\bdue\b", r"\bdeadlines?\b", r"\bby when\b"),
    "customer_impact": (r"\bimpact\b",), "release": (r"\breleases?\b",), "sla_due_at": (r"\bsla\b",),
    "first_response_due_at": (r"\bfirst response\b",), "crm_deal_id": (r"\bcrm\b", r"\bdeal\b"), "deal_id": (r"\bdeal\b",),
    "related_account": (r"\baccount\b",), "mailbox_owner": (r"\bmailbox\b", r"\binbox\b"), "thread_type": (r"\bkind\b", r"\btype\b"),
    "hq_region": (r"\bregion\b", r"\bheadquarter\w*\b", r"\bhq\b"), "employee_count_range": (r"\bemployees?\b", r"\bheadcount\b"),
    "account_tier": (r"\btier\b",), "customer_tier": (r"\btier\b",), "issue_type": (r"\btype\b",), "doc_type": (r"\btype\b",),
    "call_type": (r"\btype\b", r"\bkind\b"), "drive_area": (r"\barea\b",), "owner_team": (r"\bteam\b",), "repo": (r"\brepo\w*\b",),
    "cycle": (r"\bcycle\b", r"\bsprint\b"), "estimate": (r"\bestimate\w*\b", r"\bpoints?\b"), "redwood_owner": (r"\bown\w*\b",),
    "customer_company": (r"\bcustomer\b", r"\bcompany\b"), "assignee": (r"\bassign\w*\b",), "creator": (r"\bcreat\w*\b",),
    "reporter": (r"\breport\w*\b",), "author": (r"\bauthor\w*\b", r"\bwr[io]te\b", r"\bwritten\b"),
}
# the words of the field names and cues a count or list question may use around its values
FIELD_WORDS = frozenset("""status state priority type kind tier stage space team project cycle sprint release region hq headquartered
    headquarters range severity impact estimate estimated points area repository repo month close closes closing forecast forecasted
    customer customers company solutions solution engineer engineers manager success csm se owner owners assignee assignees creator
    creators reporter reporters author authors doc call employee employees headcount count impacting""".split())
CUE_WEIGHT = 2.0
NEAR = 4  # table: the words on each side of a value that say which field holds it
# table: the words that can point to a field next to a value (besides the field's cue and name words, the verbs of FILLER that
# name a role), and the words that make a value's condition its opposite
CUE_VERBS = frozenset(("assigned", "owned", "own", "owns", "created", "reported", "authored", "written", "wrote", "opened", "filed",
                       "raised"))
NEGATORS = frozenset(("not", "nor"))
NEGATED_VERB = re.compile(r"\b(do|does|did|is|are|was|were|have|has|had)n['’]t\b", re.I)
# table: the nouns a "which" or "list" question must govern to ask for documents (not for a field of them: "Which team owns…")
DOC_ITEMS = frozenset(("ticket", "tickets", "issue", "issues", "account", "accounts", "page", "pages", "doc", "docs", "document",
                       "documents", "meeting", "meetings", "call", "calls", "thread", "threads", "email", "emails", "pr", "prs", "pull",
                       "record", "records", "item", "items", "deal", "deals", "company", "companies"))
KEY_WORDS = frozenset(("key", "keys", "id", "ids", "identifiers", "titles", "numbers"))
MIN_HELD = 0.3  # absent: the share of the system's documents that hold the asked field (with a value that is not empty)
MIN_ASK = 1.0  # absent: how much the question must point to the field (a cue word, the whole field name, or one of its FIELD_CUES)
MAX_VALUE_CHARS = 60
SINGLE_SHARE = 0.9  # a table field: this share of its holders give it one value; absent: the same, for a field it may call missing
SHORT_SHARE = 0.9  # absent: this share of a field's values are at most MAX_VALUE_CHARS (not a text field)
ID_SHARE = 0.95  # a field whose values are this distinct over its holders is an identifier (not a person field)
PERSON_SHARE = 0.8
# history: the fields whose items are dated entries, the ways a status change is written, and the kinds of question
COMMENT_PARAMS = frozenset(("comments", "updates", "progress_updates", "activity", "activity_log", "timeline", "review_comments",
                            "recent_activities", "recent_activity", "work_log", "history", "status_history", "activities"))
ENTRY = re.compile(r"^\s*\[?(\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2}:\d{2})(?::\d{2})?(?:\.\d+)?\s*(?:Z|UTC|[A-Z]{2,4}|[+-]\d{2}:?\d{2})?)?\]?"
                   r"\s*(?:[-\u2013\u2014:|]\s*)?([A-Z][\w'.\u2019-]+(?: [A-Z][\w'.\u2019-]+){0,2})\s*(?:\([^)]*\))?\s*:(?:\s+(.*))?$", re.S)
DATE_LED = re.compile(r"^\s*\[?(\d{4}-\d{2}-\d{2})\b")
MOVE = (r"(?:\b(?:moving|moved|move)\s+(?:(?:the|this|it)\s+)?(?:(?:ticket|issue)\s+)?(?:back\s+)?(?:in)?to\s+|\bchang(?:ed|ing)\s+"
        r"(?:the\s+)?status\s+to\s+|\b(?:marking|marked)\s+(?:(?:this|the|it)\s+(?:(?:ticket|issue)\s+)?)?as\s+|\bstatus\s*(?:->|\u2192)\s*)"
        r"['\"\u2018\u201c]?")
WHEN = re.compile(r"\bwhen\b|\bwhat (?:date|day)\b|\bwhich (?:date|day)\b|\bon what\b|\bdate\b")
WHO = re.compile(r"\bwho\b|\bwhom\b|\bwhich (?:person|people|colleague|teammate|employee)\b|\bname of the person\b")
D_DAYS = re.compile(r"\bhow (?:many|long)\b.*\bdays?\b.*\bmerg|\bhow many days\b|\bdays?\b.*\b(?:to|until|till|before)\s+(?:being\s+|"
                    r"it\s+was\s+|getting\s+|it\s+got\s+)?merg|\bhow long\b.*\bmerg|\btime to merge\b")
D_FIRST_COMMENT = re.compile(r"\b(?:first|earliest|initial|opening)\s+(?:comment|commenter|reply|note)\b|\bcommented first\b|"
                             r"\bfirst (?:person |one )?to comment\b")
D_LAST_COMMENT = re.compile(r"\b(?:latest|last|most recent|newest|final|most recently posted)\s+(?:comment|reply|note)\b|"
                            r"\bcommented (?:last|most recently)\b")
D_FIRST_ACTIVITY = re.compile(r"\b(?:first|earliest|initial)\s+(?:recorded |logged |listed |dated |timeline )?(?:activity|activities|"
                              r"interaction|touchpoint|touch point|engagement|timeline (?:entry|event)|event|entry)\b|"
                              r"\btimeline\b.*\b(?:begin|begins|start|starts|open|opens)\b")
D_MOVE_VERB = re.compile(r"\b(?:move|moved|moving|go|goes|went|transition|transitioned|change|changed|switch|switched|set|put|mark|"
                         r"marked|enter|entered|get|got)\b")
D_CREATED = re.compile(r"\b(?:created|opened|filed|raised|submitted|logged|made|started)\b|\bcreation\b")
D_UPDATED = re.compile(r"\blast(?:[- ]| (?:been )?)(?:updated|modified|changed|edited|touched)\b|\b(?:most recent(?:ly)?|latest|last)\s+"
                       r"(?:update|updated|modification|modified|change|edit)\b|\bupdated (?:most recently|last)\b")
G_SENDER = re.compile(r"\bwho\s+(?:sent|wrote|started|initiated|kicked off|began|opened)\b|\bsender\b|\bfrom whom\b|\bwho (?:was|is) "
                      r"(?:the|it) (?:email|message|mail) from\b|\bwho\b.*\bfrom\b")
G_TO = re.compile(r"\b(?:sent|addressed|written|went)\s+to\b|\brecipients?\b|\bto whom\b|\bwho\b.*\b(?:receive|received|get|got)\b")
G_CC = re.compile(r"\bcc\b|\bcc'?d\b|\bcced\b|\bcopied\b|\bcarbon[- ]cop|\bon copy\b")
G_COUNT = re.compile(r"\bhow many\s+(?:\w+\s+)?(?:messages|emails|e-mails|replies|mails|notes)\b|\bnumber of (?:messages|emails|replies)\b|"
                     r"\bmessage count\b")
G_ATTACH = re.compile(r"\battach\w*\b|\bfiles?\b.*\b(?:shared|sent|included)\b")
G_ACCOUNT = re.compile(r"\b(?:account|customer|company|client)\b")
G_START = re.compile(r"\b(?:start|started|begin|began|kick(?:ed)? off|first email|first message|open|opened)\b")
S_CHANNEL = re.compile(r"\bchannel\b")
S_STARTER = re.compile(r"\bwho\s+(?:started|began|kicked off|opened|posted|wrote|sent|initiated)\b|\bstarted by\b|\bposted by\b|"
                       r"\bwho (?:posted|wrote) (?:it|the first)\b|\bfirst (?:message|post)\b.*\bwho\b|\bwho\b.*\bfirst (?:message|post)\b")
COUNT_ASK = re.compile(r"\bhow many\b|\bnumber of\b|\bcount of\b|\bwhat is the count\b|\btotal number\b|^\W*count\b|"
                       r"\bcount (?:the|all|up)\b")
PEOPLE_ASK = re.compile(r"^\W*(?:who|whom)\b|\b(?:which|what) (?:people|persons|colleagues|engineers|owners|assignees|authors|reporters|"
                        r"creators)\b|\blist (?:everyone|everybody|all the people|the people|the (?:assignees|owners|authors|reporters|"
                        r"creators))\b|\bname (?:everyone|everybody|the people)\b|\bwho (?:is|are|was|were)\b")
KEYS_ASK = re.compile(r"\bwhich\b|\blist\b|\bwhat are\b|\bgive\b|\bshow\b|\bname\b|\bkeys\b|\bids\b|\bidentifiers\b")
NAME_WORD = re.compile(r"[^\W_]+")
HEADER = re.compile(r"^(From|To|Cc|Date|Subject):[ \t]*(.*)$", re.I)
# absent: "Which CRM deal is the meeting X linked to?" links the named document itself to the field asked for; "the ticket
# linked to ENG-1" names another document, which may hold the field
SELF_LINK = re.compile(r"\b(?:linked|tied|associated|connected|related|attached)(?:\s+(?:to|with))?\s*(?=[?.!,;]|$)")
# derived: the link words its own questions use ("What files were attached in the thread…", "When did someone last comment on…")
DERIVED_OWN = frozenset(("attached", "its", "someone", "somebody"))


def squash(s: Any) -> str:
    """Lower case, accents dropped, letters and digits only, one space between words."""
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s).lower()) if not unicodedata.combining(c))
    return " ".join(NAME_WORD.findall(s.replace("&", " and ")))


def value_words(s: Any) -> str:
    """A field value or a question as the table matches them: lower case, letters (accents kept: "Martínez" is not "Martinez")
    and digits only, one space between words ("prod/us-east" -> "prod us east")."""
    return " ".join(NAME_WORD.findall(str(s).lower().replace("&", " and ")))


def is_empty(value: Any) -> bool:
    """A field value that says nothing: empty, "TBD", "N/A", "none", "unassigned"."""
    return str(value if value is not None else "").strip().strip(".").lower() in EMPTY_VALUES


def parse_when(s: str) -> datetime | None:
    """A message date ("Tue, 14 May 2029 09:34:12 -0700" or ISO), or None."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        return None


def display_name(addr: str) -> str:
    """The display name of an address ("Tanya Ramos <t@x.com>" -> "Tanya Ramos"), else the address itself."""
    from cie.ingest.sources import person_name

    a = addr.strip().strip('"').strip()
    if "<" in a:
        name = a.split("<")[0].strip().strip('"').strip()
        if name:
            return person_name(name) or name
        return a.split("<")[1].split(">")[0].strip()
    return person_name(a) if "@" not in a and person_name(a) else a


def addresses(header: str | None) -> list[str]:
    """The people of a To or Cc header, one each (commas inside <…> do not split)."""
    return [display_name(p) for p in re.split(r"[,;](?![^<]*>)", header or "") if p.strip()]


@dataclass
class Match:
    """A field value the question writes: its word span, the fields holding it and their documents."""
    start: int
    end: int
    words: tuple[str, ...]
    fields: dict[str, str] = field(default_factory=dict)  # field -> the value's words (``value_words``)


@dataclass
class FieldStats:
    values: dict[str, set[str]]  # the value's words (``value_words``) -> documents
    shown: dict[str, str]  # the value's words -> the value as written
    person: bool
    holders: int


class Records:
    """Counts, filters, history, email and chat over one bank (a ``FactBank``, normally the brain's ``BrainBank``). ``min_held``
    is the share of a system's documents that must hold a field for ``absent`` to call it missing on one of them."""

    def __init__(self, bank: FactBank, min_held: float = MIN_HELD):
        self.b = bank
        self.min_held = min_held
        self._doc_facts: dict[str, dict[str, list[tuple[str, str | None]]]] | None = None
        self._by_system: dict[str, list[str]] | None = None
        self._stats: dict[str, dict[str, FieldStats]] = {}
        self._held: dict[str, Counter] = {}
        self._titles: dict[str, list[str]] | None = None
        self._index: dict[str, dict[str, list[tuple[tuple[str, ...], str, str]]]] = {}
        self._units: dict[str, list[str]] = {}
        self._askable: dict[str, set[str]] = {}
        self._field_values: dict[tuple[str, str], set[str]] = {}

    # ------------------------------------------------------------------ the bank, read once
    def doc_facts(self) -> dict[str, dict[str, list[tuple[str, str | None]]]]:
        """Every document's fields: {doc: {parameter: [(value, value_entity)]}}, in the bank's order, without sentence facts."""
        if self._doc_facts is None:
            out: dict[str, dict[str, list[tuple[str, str | None]]]] = defaultdict(lambda: defaultdict(list))
            for e, p, v, ve in self.b.con.execute("SELECT entity, parameter, value, value_entity FROM facts WHERE entity LIKE 'doc:%' "
                                                  "AND parameter NOT LIKE 'text\\_%' ESCAPE '\\' ORDER BY rowid"):
                out[e][p].append((v, ve))
            self._doc_facts = {e: dict(fs) for e, fs in out.items()}
        return self._doc_facts

    def system_of(self, doc: str) -> str:
        return self.b.system.get(doc[4:], "") if doc.startswith("doc:") else ""

    def documents(self, system: str) -> list[str]:
        if self._by_system is None:
            by: dict[str, list[str]] = defaultdict(list)
            for e, k in self.b.kinds.items():
                if k == "document":
                    by[self.system_of(e)].append(e)
            self._by_system = {s: sorted(es) for s, es in by.items()}
        return self._by_system.get(system, [])

    def values(self, doc: str, param: str) -> list[str]:
        return [v for v, _ in self.doc_facts().get(doc, {}).get(param, [])]

    def value(self, doc: str, param: str) -> str | None:
        vs = [v for v in self.values(doc, param) if not is_empty(v)]
        return vs[0] if vs else None

    def label(self, doc: str) -> str:
        """A document as questions cite it: its key, its pull request number ("#4821"), else its title."""
        k = self.value(doc, "key")
        if k:
            return k
        n = self.value(doc, "pr_number")
        return f"#{n}" if n else self.b.names.get(doc, doc)

    def held(self, system: str) -> Counter:
        """How many of the system's documents hold each field with a value that is not empty."""
        if system not in self._held:
            c: Counter = Counter()
            for d in self.documents(system):
                for p, vs in self.doc_facts().get(d, {}).items():
                    if any(not is_empty(v) for v, _ in vs):
                        c[p] += 1
            self._held[system] = c
        return self._held[system]

    def stats(self, system: str) -> dict[str, FieldStats]:
        """The system's table fields: short values, one per document (``SINGLE_SHARE`` of holders), not identifiers and not dates
        (a forecast close month is a value), or person fields (``PERSON_SHARE`` of the values point to a person)."""
        if system in self._stats:
            return self._stats[system]
        from cie.factbank.bank import _is_date_field

        docs = self.documents(system)
        per: dict[str, list[tuple[str, list[tuple[str, str | None]]]]] = defaultdict(list)
        for d in docs:
            for p, vs in self.doc_facts().get(d, {}).items():
                per[p].append((d, vs))
        out: dict[str, FieldStats] = {}
        for p, rows in per.items():
            if p.endswith("_of") or p in ("key", "pr_number", "action_item", "referenced_by") or len(rows) < 2:
                continue
            vals = [v for _, vs in rows for v, _ in vs]
            person = sum(1 for _, vs in rows for _, ve in vs if (ve or "").startswith("person:")) >= PERSON_SHARE * len(vals)
            single = sum(1 for _, vs in rows if len(vs) == 1) >= SINGLE_SHARE * len(rows)
            if not person:
                if not single or (_is_date_field(p) and p != "forecast_close_month"):
                    continue
                if any(len(v) > MAX_VALUE_CHARS for v in vals if not is_empty(v)) and \
                        sum(len(v) > MAX_VALUE_CHARS for v in vals) > 0.1 * len(vals):
                    continue
                if len({value_words(v) for v in vals}) >= ID_SHARE * len(rows) and len(rows) >= 5:
                    continue
            values: dict[str, set[str]] = defaultdict(set)
            # "Helios Health" and "HeliosHealth" are one value; a person is one name ("Liam Oconnor" is not "Liam O'Connor")
            groups: dict[str, set[str]] = defaultdict(set)
            shown: dict[str, str] = {}
            for d, vs in rows:
                for v, _ in vs:
                    k = value_words(v)
                    if k and not is_empty(v) and len(v) <= MAX_VALUE_CHARS:
                        g = k if person else k.replace(" ", "")
                        groups[g].add(d)
                        values[k] = groups[g]
                        shown.setdefault(k, v)
            out[p] = FieldStats(dict(values), shown, person, len(rows))
        self._stats[system] = out
        return out

    def value_index(self, system: str) -> dict[str, list[tuple[tuple[str, ...], str, str]]]:
        """First word -> (the value's words, field, squashed value), for matching values as whole words."""
        if system not in self._index:
            idx: dict[str, list[tuple[tuple[str, ...], str, str]]] = defaultdict(list)
            for p, st in self.stats(system).items():
                for k in st.values:
                    ws = tuple(k.split())
                    if ws:
                        idx[ws[0]].append((ws, p, k))
            self._index[system] = dict(idx)
        return self._index[system]

    def titles(self) -> dict[str, list[str]]:
        """Squashed document title -> documents; a Gmail subject also without its "Re:" or "Fwd:"."""
        if self._titles is None:
            t: dict[str, list[str]] = defaultdict(list)
            for e, k in self.b.kinds.items():
                if k != "document":
                    continue
                s = squash(self.b.names.get(e, ""))
                if s:
                    t[s].append(e)
                    bare = re.sub(r"^(?:(?:re|fwd|fw)\s+)+", "", s)
                    if bare != s and bare:
                        t[bare].append(e)
            self._titles = {k: sorted(set(v)) for k, v in t.items()}
        return self._titles

    def text(self, doc: str) -> str:
        row = self.b.con.execute("SELECT text FROM entities_fts WHERE id = ?", (doc,)).fetchone()
        return row[0] if row else ""

    def units(self, doc: str) -> list[str]:
        """The document's stored text after its title, source and field lines, cut into units: lines without a leading "- ", and
        the items of a list written on one line ("['2026-03-10 Ana Ruiz: …', '…']")."""
        if doc in self._units:
            return self._units[doc]
        body = self.body_lines(self.text(doc).split("\n"), doc)
        out: list[str] = []
        for line in body:
            s = line.strip()
            if s.startswith("- "):
                s = s[2:].strip()
            if len(s) > 4 and s[0] == "[" and s[-1] == "]" and s[1] in "'\"":
                try:
                    items = ast.literal_eval(s)
                except (ValueError, SyntaxError, MemoryError, RecursionError):
                    items = None
                if isinstance(items, list):
                    out += [str(x).replace("\\n", "\n").strip() for x in items if str(x).strip()]
                    continue
            if s:
                out.append(s)
        if len(self._units) > 512:
            self._units.clear()
        self._units[doc] = out
        return out

    def body_lines(self, lines: list[str], doc: str) -> list[str]:
        """The text's lines after the title, the source line and one line per field value (a value may run over lines: the
        field lines are found in order, each by its "field: value" start)."""
        pos = 2
        for p, vs in self.doc_facts().get(doc, {}).items():
            if p.startswith("text_") or p == "action_item":
                continue
            for v, _ in vs:
                head = f"{p.replace('_', ' ')}: {v[:40]}".strip()
                for j in range(pos, min(len(lines), pos + 40)):
                    if lines[j].strip().startswith(head[:60]):
                        pos = j + 1 + v.count("\n")
                        break
        return lines[pos:]

    def entries(self, doc: str) -> list[str]:
        """The document's units and the items of its dated-entry fields (comments, updates, timeline…)."""
        out = list(self.units(doc))
        for p in COMMENT_PARAMS:
            out += [v for v in self.values(doc, p) if v]
        return out

    # ------------------------------------------------------------------ 1. the named document
    def named_docs(self, question: str, quotes: bool = True, text_quotes: bool = True) -> list[str]:
        """The documents the question names: by a ticket key, a pull request number, a quoted title, or a quote of words that
        exactly one document's text holds."""
        out: list[str] = []
        bare = QUOTED.sub(" ", question)
        for m in TICKET.finditer(bare):
            out += [e for e in self.b.aliases.get(m.group(0).lower(), ()) if self.b.kinds.get(e) == "document"]
        for m in PR_NUMBER.finditer(bare):
            out += [e for e in self.b.aliases.get(f"#{m.group(1)}", ()) if self.b.kinds.get(e) == "document"]
        if quotes:
            for m in QUOTED.finditer(question):
                inner = m.group(0)[1:-1].strip()
                if len(inner) < 3:
                    continue
                docs = self.titles().get(squash(inner)) or (self.quoted_in_text(inner) if text_quotes else [])
                if len(docs) == 1:
                    out += docs
        return list(dict.fromkeys(out))

    def quoted_in_text(self, quote: str) -> list[str]:
        """The documents whose stored text holds a quote of five or more words, as whole words (case, punctuation and accents
        aside): the index finds the phrase, the text confirms it."""
        want = squash(quote)
        words = NAME_WORD.findall("".join(c for c in unicodedata.normalize("NFKD", quote.lower()) if not unicodedata.combining(c)))
        if len(words) < 5:
            return []
        try:
            rows = self.b.con.execute("SELECT id, text FROM entities_fts WHERE entities_fts MATCH ? LIMIT 50", (f'"{" ".join(words)}"',)).fetchall()
        except sqlite3.OperationalError:
            return []
        return sorted({r[0] for r in rows if self.b.kinds.get(r[0]) == "document" and f" {want} " in f" {squash(r[1])} "})

    def start(self, question: str) -> str | None:
        """The one document the question names (``named_docs``), or None for none or several."""
        docs = self.named_docs(question)
        return docs[0] if len(docs) == 1 else None

    # ------------------------------------------------------------------ 2. counts and filters
    def intent(self, question: str) -> str | None:
        """What a count or list question asks for: "count", "people" or "keys"; None for anything else."""
        ql = question.lower()
        if COUNT_ASK.search(ql):
            return "count"
        uq = unquoted(ql)
        if PEOPLE_ASK.search(uq):
            return "people"
        if KEYS_ASK.search(uq):
            return "keys"
        return None

    def systems(self, question: str) -> list[str]:
        """The systems a count or list question is about: the ones it names, else the ones its item nouns imply."""
        named = [s for s in systems_in(question, whole_words=True) if s != "slack"]
        if named:
            return named
        ws = [w.rstrip("s") if w not in ("pages",) else "page" for w in re.findall(r"[a-z]+", unquoted(question.lower()))]
        out: list[str] = []
        for w in ws:
            out += ITEM_SYSTEMS.get(w, ())
        return list(dict.fromkeys(out))

    def table(self, question: str) -> dict[str, Any] | None:
        """A count, a list of keys or a list of people over one system's documents that hold the field values the question
        writes, or None (see the module docstring)."""
        question = NEGATED_VERB.sub(r"\1 not", question)  # "don't have" -> "do not have"
        kind = self.intent(question)
        if kind is None:
            return None
        bare = QUOTED.sub(" ", question)
        if TICKET.search(bare) or PR_NUMBER.search(bare):
            return None
        systems = self.systems(question)
        if not systems or (len(systems) > 1 and len(set(systems) - {"jira", "linear"}) > 0):
            return None
        titled = {self.system_of(d) for d in self.named_docs(question, text_quotes=False)}
        found = [r for r in (self.filter(question, s, kind) for s in systems if s not in titled) if r is not None]
        if len(found) != 1:
            return None
        return found[0]

    def matches(self, question: str, system: str) -> tuple[list[str], list[Match]]:
        """The question's words and the field values of the system it writes as whole words: a value inside a longer one, or
        inside a field's name written out ("doc" in "doc type sheet"), left out."""
        toks = value_words(question).split()
        idx = self.value_index(system)
        names = []
        for p in self.stats(system):
            ws = p.split("_")
            names += [(i, i + len(ws)) for i in range(len(toks) - len(ws) + 1) if toks[i:i + len(ws)] == ws]
        found: list[Match] = []
        for i, w in enumerate(toks):
            for ws, p, k in idx.get(w, ()):
                if tuple(toks[i:i + len(ws)]) == ws and not any(a <= i and i + len(ws) <= b for a, b in names):
                    m = next((x for x in found if x.start == i and x.end == i + len(ws)), None)
                    if m is None:
                        m = Match(i, i + len(ws), ws)
                        found.append(m)
                    m.fields[p] = k
        keep = [m for m in found if not any(o is not m and o.start <= m.start and m.end <= o.end and (o.end - o.start) > (m.end - m.start)
                                            for o in found)]
        return toks, keep

    @staticmethod
    def cue_score(p: str, words: list[str], text: str) -> float:
        """How much some words point to a field, as ``FactBank.wanted`` weighs a question (its cue words, and the field's name
        words: the share of them present), plus ``CUE_WEIGHT`` for each of the field's ``FIELD_CUES`` the text holds."""
        st = {stem(w) for w in words if w not in STOP}
        score = 0.0
        for cue, params in CUES.items():
            if p in params and any(w.startswith(cue) for w in st):
                score += 2.0 - 0.1 * params.index(p)
        toks = {stem(x) for x in p.split("_") if x}
        score += len(toks & st) / len(toks) if toks else 0.0
        return score + CUE_WEIGHT * sum(1 for pat in FIELD_CUES.get(p, ()) if re.search(pat, text))

    def weak(self, words: tuple[str, ...], st: FieldStats) -> bool:
        """A value too short, numeric, boolean or generic to count without a word pointing to its field."""
        k = " ".join(words)
        return (len(k) <= 2 or k.replace(" ", "").isdigit() or k in ("true", "false", "yes", "no")
                or all(w in STOP or w in FILLER or w in ITEM_WORDS or w in SYSTEM_NAME_WORDS for w in words)) and not st.person

    def pointers(self, system: str, toks: list[str], found: list[Match]) -> list[set[str]]:
        """For each word of the question, the system's fields it points to: by its cue and name words (``cue_score`` of the word
        alone) or a ``FIELD_CUES`` pattern that covers it ("solutions engineer"). Words of a matched value, question and filler
        words (except the verbs that name a role: ``CUE_VERBS``), system and item nouns, "open" and "not" point to none."""
        fields = [p for p in self.held(system) if not p.endswith("_of") and p not in ("key", "pr_number")]
        at, pos = [], 0
        for t in toks:
            at.append(pos)
            pos += len(t) + 1
        text = " ".join(toks)
        out: list[set[str]] = [set() for _ in toks]
        for p in fields:
            for pat in FIELD_CUES.get(p, ()):
                for mm in re.finditer(pat, text):
                    for j, s in enumerate(at):
                        if mm.start() <= s < mm.end():
                            out[j].add(p)
        inside = {j for m in found for j in range(m.start, m.end)}
        for j, t in enumerate(toks):
            if (j in inside or t in STOP or t in ITEM_WORDS or t in SYSTEM_NAME_WORDS or t in NEGATORS or t == "open"
                    or (t in FILLER and t not in CUE_VERBS)):
                out[j] = set()
            else:
                out[j] |= {p for p in fields if self.cue_score(p, [t], "") > 0}
        return out

    @staticmethod
    def nearest_fields(point: list[set[str]], m: Match, values: list[Match]) -> set[str] | None:
        """The fields named by the pointing words closest to a value (within ``NEAR`` words on either side), leaving out a word
        closer to another value ("pages of the platform team in review": "team" is the platform's, not the review's); None
        when no word next to the value points to a field."""
        def dist(j: int, x: Match) -> int:
            return x.start - j if j < x.start else j - x.end + 1

        best, got = NEAR + 1, set()
        for j in range(max(0, m.start - NEAR), min(len(point), m.end + NEAR)):
            if not point[j] or m.start <= j < m.end:
                continue
            d = dist(j, m)
            if d > best or any(dist(j, o) < d for o in values if o is not m and not o.start <= j < o.end):
                continue
            got = set(point[j]) if d < best else got | point[j]
            best = d
        return got or None

    @staticmethod
    def governs_item(toks: list[str], used: list[bool]) -> bool:
        """Whether a list question asks for documents: it says keys, ids or titles, or its "which" (what, list, give, show,
        name) governs an item noun ("Which open Jira tickets…", "List the dedicated-tier Jira tickets…"), not a field of
        them ("Which team owns…", "What are the statuses of…")."""
        if any(t in KEY_WORDS for t in toks):
            return True
        a = next((i for i, t in enumerate(toks) if t in ("which", "what", "list", "give", "show", "name")), None)
        if a is None:
            return False
        for k in range(a + 1, min(len(toks), a + 9)):
            t = toks[k]
            if t in DOC_ITEMS:
                return True
            if not (used[k] or t in STOP or t in SYSTEM_NAME_WORDS or t in ("me", "us", "please", "open", "each", "currently")
                    or (k > 0 and used[k - 1] and t in FIELD_WORDS)):  # "dedicated-tier": a field word after its value
                return False
        return False

    def filter(self, question: str, system: str, kind: str) -> dict[str, Any] | None:
        """``table`` for one system."""
        stats = self.stats(system)
        toks, found = self.matches(question, system)
        bare = value_words(unquoted(question)).split()
        rel = {p: self.cue_score(p, bare, " ".join(bare)) for p in stats}
        conds: dict[str, set[str]] = defaultdict(set)
        neg: dict[str, set[str]] = defaultdict(set)
        used = [False] * len(toks)
        status_field = "status" if "status" in stats else ("state" if "state" in stats else None)
        has_open = "open" in toks
        not_at = [i for i, t in enumerate(toks) if t in NEGATORS]
        live: list[tuple[Match, dict[str, str]]] = []
        for m in sorted(found, key=lambda m: m.start):
            if system in CLOSED and m.words == ("open",):
                continue  # "open" means a status that is not closed (below), not a status called "Open"
            fields = {p: k for p, k in m.fields.items() if not (self.weak(m.words, stats[p]) and rel.get(p, 0.0) <= 0)}
            if fields:
                live.append((m, fields))
        point = self.pointers(system, toks, found)
        chosen: list[tuple[Match, str, bool]] = []
        attached: set[int] = set()
        for m, fields in live:
            named = self.nearest_fields(point, m, [o for o, _ in live])
            if named is not None:
                fields = {p: k for p, k in fields.items() if p in named}
                if not fields:
                    return None  # the words next to the value name a field that does not hold it ("high-priority" Linear issues)
            near = toks[max(0, m.start - NEAR):m.start] + toks[m.end:m.end + NEAR]  # the words next to the value weigh first
            score = {p: (self.cue_score(p, near, " ".join(near)), rel.get(p, 0.0)) for p in fields}
            best = max(score.values())
            top = [p for p in fields if score[p] == best]
            if len(top) > 1:
                sets = {frozenset(stats[p].values[fields[p]]) for p in top}
                if len(sets) > 1:
                    return None  # the value is in several fields and no word says which
            p = sorted(top)[0]
            by = {j for j in not_at if 0 < m.start - j <= 3}
            prev = chosen[-1] if chosen else None
            # "not Resolved or Closed": a "not" negates the value it precedes and the values of the same field listed after it
            negated = bool(by) or (prev is not None and prev[2] and prev[1] == p and all(t in ("or", "nor", "and") for t in toks[prev[0].end:m.start]))
            attached |= by
            chosen.append((m, p, negated))
            (neg if negated else conds)[p].add(fields[p])
            for j in range(m.start, m.end):
                used[j] = True
        if set(not_at) - attached:
            return None  # a "not" before no value negates something table cannot ("not assigned", "not yet merged")
        if has_open and not any(m.words == ("open",) for m, _, _ in chosen):
            if system not in CLOSED or not status_field:
                return None  # "open" means nothing for this system's documents (a HubSpot account)
            if not neg.get(status_field):
                closed = {value_words(v) for v in CLOSED[system]}
                neg[status_field] |= {k for k in stats[status_field].values if k in closed}
                if not neg[status_field]:
                    return None
        if not conds and not neg:
            return None
        if kind == "keys" and not self.governs_item(toks, used):
            return None  # "Which team owns the space X?" asks for a field of the documents, not for them
        asked = None
        if kind == "people":
            persons = [p for p, st in stats.items() if st.person and p not in conds and p not in neg]
            scored = sorted(((rel.get(p, 0.0), p) for p in persons), reverse=True)
            if not scored or scored[0][0] <= 0 or (len(scored) > 1 and scored[1][0] == scored[0][0]):
                return None
            asked = scored[0][1]
        # every other word is a question or filler word, a system or item noun, or a word of (or pointing to) a matched or asked
        # field: "How many Jira tickets with priority P1 have an assignee?" also asks about the assignee, which table cannot
        targets = set(conds) | set(neg) | ({asked} if asked else set())
        explained = FILLER | ITEM_WORDS | SYSTEM_NAME_WORDS | STOP
        if has_open or not_at:
            explained = explained | {"open", "not", "nor"} | {w for v in CLOSED.get(system, ()) for w in value_words(v).split()}
        for p in targets:
            explained = explained | {stem(x) for x in p.split("_")} | set(p.split("_"))
        if any(not used[i] and t not in explained and stem(t) not in explained and not point[i] & targets for i, t in enumerate(toks)):
            return None  # a word that is not a condition: the question asks something more
        docs = set(self.documents(system))
        for p, ks in conds.items():
            docs &= set().union(*(stats[p].values.get(k, set()) for k in ks))
        for p, ks in neg.items():
            docs -= set().union(*(stats[p].values.get(k, set()) for k in ks))
        docs_l = sorted(docs, key=lambda d: (self.label(d), d))
        filters = [f"{p} = {' or '.join(stats[p].shown[k] for k in sorted(ks))}" for p, ks in sorted(conds.items())]
        filters += [f"{p} not {' or '.join(stats[p].shown.get(k, k) for k in sorted(ks))}" for p, ks in sorted(neg.items())]
        noun = {"jira": "Jira tickets", "linear": "Linear issues", "hubspot": "HubSpot accounts", "gmail": "email threads",
                "github": "pull requests", "confluence": "Confluence pages", "google_drive": "Drive documents",
                "fireflies": "meetings"}.get(system, f"{system} documents")
        where = "; ".join(filters)
        lines = [f"- {self.label(d)}: {self.b.names.get(d, d)[:120]}" + "".join(
            f"; {p}: {self.value(d, p) or ''}" for p in list(conds)[:3]) for d in docs_l[:60]]
        if kind == "count":
            return {"answer": str(len(docs_l)), "kind": "count", "system": system, "filters": filters, "docs": docs_l,
                    "reason": f"{len(docs_l)} {noun} where {where}", "evidence": "\n".join([f"{len(docs_l)} {noun} where {where}:", *lines])}
        if kind == "people":
            people = list(dict.fromkeys(v for d in docs_l for v in self.values(d, asked) if not is_empty(v)))
            if not people:
                return None
            return {"answer": ", ".join(people), "kind": "people", "system": system, "filters": filters, "docs": docs_l, "field": asked,
                    "reason": f"the {asked.replace('_', ' ')} of {len(docs_l)} {noun} where {where}",
                    "evidence": "\n".join([f"{asked.replace('_', ' ')} of {len(docs_l)} {noun} where {where}:", *(
                        f"- {self.label(d)}: {', '.join(self.values(d, asked))}" for d in docs_l[:60])])}
        if not docs_l:
            return {"answer": "none", "kind": "keys", "system": system, "filters": filters, "docs": [],
                    "reason": f"no {noun} where {where}", "evidence": f"no {noun} where {where}"}
        return {"answer": ", ".join(self.label(d) for d in docs_l), "kind": "keys", "system": system, "filters": filters, "docs": docs_l,
                "reason": f"{len(docs_l)} {noun} where {where}", "evidence": "\n".join([f"{len(docs_l)} {noun} where {where}:", *lines])}

    # ------------------------------------------------------------------ 3. history and messages
    def comments(self, doc: str) -> list[tuple[str, str, str, str]]:
        """The document's dated entries with an author ("2026-03-10 05:12 - Ana Ruiz (Support): text"): (date, time, author, text),
        in the order written. The author is a person's name when it reads as one, else as written ("SRE Team", "Asha")."""
        from cie.ingest.sources import person_name

        out = []
        for u in self.entries(doc):
            m = ENTRY.match(u)
            if m:
                out.append((m.group(1), m.group(2) or "", person_name(m.group(3)) or m.group(3), (m.group(4) or "").strip()))
        return out

    def messages(self, doc: str) -> list[dict[str, Any]]:
        """A Gmail thread's messages from its stored text: the headers (From, To, Cc, Date, Subject) of each, in order."""
        out: list[dict[str, Any]] = []
        cur: dict[str, Any] | None = None
        lines = self.body_lines(self.text(doc).split("\n"), doc)
        listed = any(HEADER.match(x[2:]) for x in lines if x.startswith("- "))  # one list item per message
        for line in lines:
            item = line.startswith("- ") and bool(HEADER.match(line[2:]))
            m = HEADER.match(line[2:] if item else line)
            if m is None:
                continue
            name = m.group(1).capitalize()
            if item or (not listed and name == "From"):
                cur = {}
                out.append(cur)
            if cur is not None and name not in cur:
                cur[name] = m.group(2).strip()
        for i, msg in enumerate(out):
            msg["when"] = parse_when(msg.get("Date", ""))
            msg["i"] = i
        return out

    def first_message(self, doc: str) -> dict[str, Any] | None:
        ms = self.messages(doc)
        if not ms:
            return None
        dated = [m for m in ms if m["when"] is not None and m["when"].tzinfo is not None]
        if len(dated) == len(ms):
            return min(ms, key=lambda m: (m["when"], m["i"]))
        return ms[0]

    def status_values(self, system: str) -> list[str]:
        st = self.stats(system)
        p = "status" if "status" in st else "state" if "state" in st else None
        return sorted(st[p].shown.values(), key=len, reverse=True) if p else []

    def derived(self, question: str, start: str | None) -> dict[str, Any] | None:
        """A fact of the named document's history or messages (see the module docstring), or None."""
        if not start or self.b.kinds.get(start) != "document":
            return None
        system = self.system_of(start)
        ql = unquoted(question.lower())
        if self.follows_link(ql, DERIVED_OWN, derived=True):
            return None  # "When was the parent issue of ENG-1 created?" asks about another document
        lab = self.label(start)
        title = self.b.names.get(start, start)

        def out(answer: str, kind: str, reason: str, lines: list[str]) -> dict[str, Any]:
            return {"answer": answer, "kind": kind, "doc": start, "reason": reason,
                    "evidence": "\n".join([f"[{system}] {lab}: {title[:160]}", *lines])}

        if system == "github" and D_DAYS.search(ql):
            c, m = self.value(start, "created_at"), self.value(start, "merged_at")
            if c and m and ISO_DATE.match(c[:10]) and ISO_DATE.match(m[:10]):
                n = (date.fromisoformat(m[:10]) - date.fromisoformat(c[:10])).days
                if n >= 0:
                    return out(str(n), "days_to_merge", f"opened {c[:10]}, merged {m[:10]}", [f"created at: {c}", f"merged at: {m}"])
            return None
        first_c, last_c = D_FIRST_COMMENT.search(ql), D_LAST_COMMENT.search(ql)
        if first_c or last_c:
            cs = self.comments(start)
            if not cs:
                return None
            order = sorted(range(len(cs)), key=lambda i: (cs[i][0], cs[i][1]))
            i = order[0] if first_c else order[-1]
            j = order[1] if first_c and len(order) > 1 else order[-2] if len(order) > 1 else None
            entry = cs[i]
            line = f"{entry[0]} {entry[1]} {entry[2]}: {entry[3][:200]}".replace("  ", " ")
            which = "first" if first_c else "latest"
            when = WHEN.search(ql.replace("who", ""))
            if WHO.search(ql):
                if j is not None and (cs[j][0], cs[j][1]) == (entry[0], entry[1]) and cs[j][2] != entry[2]:
                    return None  # two people at the same time
                if len(entry[2].split()) < 2:
                    return None  # a first name or a label ("Update"), not who
                if when:  # "Who left the latest comment, and when?"
                    return out(f"{entry[2]}, {entry[0]}", f"{which}_comment", f"the {which} dated comment", [line])
                return out(entry[2], f"{which}_commenter", f"the {which} dated comment", [line])
            if when:
                return out(entry[0], f"{which}_comment_date", f"the {which} dated comment", [line])
            return None
        if D_FIRST_ACTIVITY.search(ql) and WHEN.search(ql):
            ds = sorted({m.group(1) for u in self.entries(start) if (m := DATE_LED.match(u))})
            if ds:
                first = next(u for u in self.entries(start) if u.lstrip("[ ").startswith(ds[0]))
                return out(ds[0], "first_activity", "the earliest dated entry", [first[:240]])
            return None
        if system in ("jira", "linear", "hubspot", "github", "confluence", "google_drive") and WHEN.search(ql) and D_MOVE_VERB.search(ql):
            sts = self.status_values(system)
            target = next((s for s in sts if re.search(r"\b(?:to|as|into|in)\s+(?:the\s+)?(?:status\s+)?['\"\u201c\u2018]?"
                                                         + re.escape(s.lower()) + r"\b", question.lower())), None)
            if target:
                hits = sorted({m.group(1) for u in self.entries(start) if (m := DATE_LED.match(u))
                               and re.search(MOVE + re.escape(target) + r"\b", u, re.I)})
                if len(hits) == 1:
                    line = next(u for u in self.entries(start) if u.lstrip("[ ").startswith(hits[0]) and re.search(MOVE + re.escape(target), u, re.I))
                    return out(hits[0], "moved_to_status", f"the dated entry that moves it to {target}", [line[:240]])
                return None
        if system == "gmail":
            r = self.gmail(question, ql, start, out)
            if r is not False:
                return r
        if system == "slack":
            if S_CHANNEL.search(ql) and not (WHO.search(ql) and S_STARTER.search(ql)):  # "Who started the thread in the channel…"
                ch = self.value(start, "channel") or title
                return out(ch, "slack_channel", "the thread's channel", [f"channel: {ch}"])
            if S_STARTER.search(ql):
                first = next((u for u in self.units(start) if re.match(r"^[^:\n]{1,40}:\s+\S", u)), None)
                if first:
                    from cie.ingest.sources import person_name

                    who = first.split(":", 1)[0].strip()
                    return out(person_name(who) or who, "slack_starter", "the speaker of the thread's first message", [first[:240]])
            return None
        if WHEN.search(ql) and D_UPDATED.search(ql):
            for p in ("updated_at", "last_updated", "last_modified", "last_email_at"):
                v = self.value(start, p)
                if v:
                    return out(v[:10], "last_updated", f"the {p.replace('_', ' ')} field", [f"{p.replace('_', ' ')}: {v}"])
            return None
        if WHEN.search(ql) and D_CREATED.search(ql) and not re.search(r"\b(?:merged|closed|resolved|due|recorded)\b", ql):
            for p in ("created_at", "created", "first_email_at"):
                v = self.value(start, p)
                if v:
                    return out(v[:10], "created_on", f"the {p.replace('_', ' ')} field", [f"{p.replace('_', ' ')}: {v}"])
        return None

    def gmail(self, question: str, ql: str, start: str, out) -> dict[str, Any] | None | bool:
        """``derived`` for a Gmail thread; False when the question asks none of its kinds."""
        if G_COUNT.search(ql):
            n = self.value(start, "message_count")
            if n and n.strip().isdigit():
                return out(str(int(n)), "email_count", "the thread's message count", [f"message count: {n}"])
            ms = self.messages(start)
            return out(str(len(ms)), "email_count", "the messages in the thread", [f"{len(ms)} messages"]) if ms else None
        first = re.search(r"\b(?:last|latest|final|most recent)\s+(?:email|message|reply|mail)\b", ql) is None
        which = "first" if first else "last"
        counting = COUNT_ASK.search(ql) is not None  # "How many people were copied…": the number, not the names
        if G_CC.search(ql):
            m = self.first_message(start) if first else (self.messages(start) or [None])[-1]
            if m is None:
                return None
            cc = addresses(m.get("Cc"))
            if counting:
                return out(str(len(cc)), "email_cc_count", f"the Cc line of the {which} message", [f"Cc: {m.get('Cc', '')}"]) if cc else None
            return out(", ".join(cc), "email_cc", f"the Cc line of the {which} message", [f"Cc: {m.get('Cc', '')}"]) if cc else None
        if G_ATTACH.search(ql):
            att = [v for v in self.values(start, "attachments") if not is_empty(v)]
            if counting:
                return out(str(len(att)), "email_attachment_count", "the thread's attachments", [f"attachments: {a}" for a in att])
            # file names may hold commas ("x.pdf (PDF, 312KB)"): joined by "; "
            return out("; ".join(att), "email_attachments", "the thread's attachments", [f"attachments: {a}" for a in att]) if att else None
        if G_TO.search(ql) and not G_SENDER.search(re.sub(r"\bsent to\b", " ", ql)):
            m = self.first_message(start) if first else (self.messages(start) or [None])[-1]
            if m is None:
                return None
            to = addresses(m.get("To"))
            if counting:
                return out(str(len(to)), "email_to_count", f"the To line of the {which} message", [f"To: {m.get('To', '')}"]) if to else None
            return out(", ".join(to), "email_to", f"the To line of the {which} message", [f"To: {m.get('To', '')}"]) if to else None
        asks_who = WHO.search(ql) or re.search(r"\b(?:what|which) (?:is|was) the (?:name of the )?sender\b", ql)
        if asks_who and (G_SENDER.search(ql) or re.search(r"\b(?:first|start|started|began|kick)", ql)):
            ms = self.messages(start)
            m = self.first_message(start) if first else (max(ms, key=lambda x: (x["when"] or datetime.min, x["i"])) if ms and all(
                x["when"] for x in ms) else (ms[-1] if ms else None))
            if m is None or not m.get("From"):
                return None
            return out(display_name(m["From"]), "email_sender", f"the From line of the {which} message",
                       [f"From: {m['From']}", f"Date: {m.get('Date', '')}"])
        if WHEN.search(ql) and (G_START.search(ql) or D_CREATED.search(ql)):
            v = self.value(start, "first_email_at")
            return out(v[:10], "email_date", "the thread's first email date", [f"first email at: {v}"]) if v else None
        if G_ACCOUNT.search(ql) and re.search(r"\b(?:which|what)\b", ql):
            v = self.value(start, "related_account")
            return out(v, "email_account", "the thread's related account", [f"related account: {v}"]) if v else None
        return False

    # ------------------------------------------------------------------ 4. a field the document leaves empty
    @staticmethod
    def follows_link(ql: str, own: frozenset[str] = frozenset(), derived: bool = False) -> bool:
        """Whether a question (lower case, without its quoted titles) asks about a document reached from the named one: a link
        word (``plans.LINK_WORDS``, but ``own``, and "linked to" closing a clause, which links the named document itself) or a
        link phrase (``plans.LINK_PHRASES``; for ``derived``, "went to" asks who an email went to)."""
        if set(re.findall(r"[a-z]+", SELF_LINK.sub(" ", ql))) & (LINK_WORDS - own):
            return True
        return LINK_PHRASES.search(re.sub(r"\bwent to\b", " ", ql) if derived else ql) is not None

    def askable(self, system: str) -> set[str]:
        """The fields ``absent`` may call missing on a document of the system: held by ``min_held`` of its documents, with one
        short value each (``SINGLE_SHARE`` of the holders give one value, ``SHORT_SHARE`` of the values are at most
        ``MAX_VALUE_CHARS``). A list or text field (a HubSpot next step or blockers, a meeting's topics or next steps) is one that
        documents also write as a content field, its value in the text with no field name, which the bank cannot tell from
        missing."""
        if system not in self._askable:
            docs = self.documents(system)
            held = self.held(system)
            out = set()
            for p, n in held.items():
                if p.endswith("_of") or p in ("key", "pr_number") or n < self.min_held * len(docs):
                    continue
                rows = [vs for d in docs if (vs := [v for v in self.values(d, p) if not is_empty(v)])]
                vals = [v for vs in rows for v in vs]
                if (rows and sum(len(vs) == 1 for vs in rows) >= SINGLE_SHARE * len(rows)
                        and sum(len(v) <= MAX_VALUE_CHARS for v in vals) >= SHORT_SHARE * len(vals)):
                    out.add(p)
            self._askable[system] = out
        return self._askable[system]

    def field_values(self, system: str, field: str) -> set[str]:
        """The values (``value_words``) the system's documents hold in a field."""
        key = (system, field)
        if key not in self._field_values:
            self._field_values[key] = {w for d in self.documents(system) for v in self.values(d, field)
                                       if not is_empty(v) and (w := value_words(v))}
        return self._field_values[key]

    def written_bare(self, doc: str, field: str) -> bool:
        """Whether the document's text (after its field lines) holds a line that is one of the values the system's documents
        hold in the field: the field written as a content field ("medium" for a Linear issue's customer impact)."""
        vals = self.field_values(self.system_of(doc), field)
        return any(value_words(u) in vals for u in self.units(doc))

    def relevance(self, question: str, fields: Iterable[str]) -> dict[str, float]:
        """How much the question's words point to each field: the bank's cue weights (``wanted``) on the question without its
        quoted titles and the words that name the document itself (system names, item nouns: "the Linear issue" does not ask for
        ``parent_issue``), plus ``CUE_WEIGHT`` for each of the field's ``FIELD_CUES`` the question holds."""
        ql = unquoted(question.lower())
        want = self.b.wanted(" ".join(w for w in re.findall(r"[\w'-]+", ql) if w not in ITEM_WORDS and w not in SYSTEM_NAME_WORDS))
        out = {}
        for f in fields:
            out[f] = want.get(f, 0.0) + CUE_WEIGHT * sum(1 for pat in FIELD_CUES.get(f, ()) if re.search(pat, ql))
        return out

    def absent(self, question: str, start: str | None) -> str | None:
        """Why the answer is not found when the asked field (``relevance``) is one ``min_held`` of the system's documents hold, with
        one short value each (``askable``), but the named document leaves empty and its text does not hold one of the field's
        values on a line of its own (``written_bare``); None when the document holds it, the question follows a link, counts or
        asks for history, or no field stands out."""
        if not start or self.b.kinds.get(start) != "document":
            return None
        ql = unquoted(question.lower())
        if self.follows_link(ql) or COUNT_ASK.search(question.lower()):
            return None
        if any(r.search(ql) for r in (D_DAYS, D_FIRST_COMMENT, D_LAST_COMMENT, D_FIRST_ACTIVITY, D_UPDATED)):
            return None  # history (``derived``), not a field
        system = self.system_of(start)
        docs = self.documents(system)
        held = self.held(system)
        fields = [p for p in held if not p.endswith("_of") and p not in ("key", "pr_number")]
        known = {p for p, vs in self.doc_facts().get(start, {}).items() if not p.startswith("text_")}
        rel = self.relevance(question, set(fields) | known)
        ranked = sorted(((w, p) for p, w in rel.items() if w > 0), reverse=True)
        if not ranked:
            return None
        best_w, best = ranked[0]
        if best_w < MIN_ASK or (len(ranked) > 1 and ranked[1][0] == best_w):
            return None
        if held[best] < self.min_held * len(docs) or self.value(start, best) is not None:
            return None
        if best not in self.askable(system) or self.written_bare(start, best):
            return None  # a list or text field, or the value written in the text: the bank cannot tell it from missing
        if any(p in known and self.value(start, p) is not None and w >= best_w - 0.5 for w, p in ranked[1:]):
            return None
        noun = {"jira": "Jira ticket", "linear": "Linear issue", "hubspot": "HubSpot account", "gmail": "email thread", "github": "pull request",
                "confluence": "Confluence page", "google_drive": "Drive document", "fireflies": "meeting"}.get(system, "document")
        said = [v for v in self.values(start, best) if v.strip()]
        what = {"csm_assigned": "CSM assigned", "se_assigned": "solutions engineer assigned"}.get(best, best.replace("_", " "))
        return f"the {noun} {self.label(start)} has no {what}" + (f' (the field says "{said[0]}")' if said else "")

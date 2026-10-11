"""The new kinds of question for the company brain v16, with expected answers from the documents' raw fields, and their scorer.

v15's questions (``brain_questions``) asked for one field of one named document, a list or a link, and invented names that
no document holds. v16 adds what those never asked (S/brain2/survey.txt, kinds lens):

* **counts:** how many documents of one system hold one or two field values (``count1_<source>``, ``count2_<source>``), how
  many email threads of a type are in one person's mailbox or are about one account (``count_gmail``), and the keys of a
  filtered set of Jira or Linear items (``filter_list``, ten keys at most). "Open" is always spelled out: a Jira ticket whose
  status is not Resolved or Closed, a Linear issue whose status is not Done or Canceled;
* **history:** when a document was created or last updated, how many days a pull request took to merge, the date a ticket
  moved to its present status, who left the first comment and when the latest comment was posted, and the first recorded
  activity with a HubSpot account. No field records earlier values, so there are no questions about a previous assignee
  or status;
* **email_chat:** an email thread named by its subject: who sent the first email, when the thread started, who the first
  email went to and who was copied, how many messages it holds, its attachments and its account (a customer account: a
  hiring thread's account field names candidates, recruiters and employers, and labels such as 'Candidate: Alex Romero' or
  'Internal - Monthly QBR prep' are not asked); a Slack thread named by a quote of its first ten words: its channel and,
  when that is a full name, who started it;
* **multi:** two documents joined: the project, creator or team of the Linear issue a pull request links
  (``pr_issue_project``, ``pr_issue_creator``, ``pr_issue_team``), and joins on a person's full name inside the haystack:
  the Linear issues assigned to a pull request's author or to a Jira ticket's reporter, the HubSpot accounts owned by a
  meeting's Redwood owner (``author_issues``, ``reporter_issues``, ``owner_accounts``). A join rests on the same name
  string, not on a confirmed same person. These are written as ``factbank_multi`` writes its questions (a value, a date or
  keys, with pieces), so the plan lessons can learn from them;
* **unanswerable:** a field that most documents of a system hold is empty, missing, TBD or N/A on the named one
  (``field_absent``); the right answer is "not found". "none" is a value, not an empty field, where the field's scale has
  that level (Linear customer_impact: none, low, medium, high);
* **single, group embedded:** the field questions of ``brain_questions.FIELDS`` asked after a verb of knowing or telling
  ("Do you know when…", "Can you remind me who…"), with the same expected answers.

Every expected answer is computed from the raw document fields. A question with more than one right answer in the haystack
is set aside, as ``brain_questions`` does: a name on two documents, a value written inside another value, an entry that is
not a person, a tie for first or latest, a document whose own fields disagree (a thread's first message that is not its
earliest, a history entry dated before the document was created), an answer written in the question itself, and the reasons
of ``factbank_5k.why_unclear``. ``generate`` counts what it sets aside, by kind and reason.

``kinds()`` is the catalogue, ``generate`` makes every question the documents allow, ``draw_questions`` draws a seeded sample
in a mix (the kinds of ``brain_questions`` may join it), ``score`` scores one answer (``brain_questions.score`` for the old
kinds) and ``family`` gives a question's family.

    python -m cie.eval.brain2_questions generate --work W | --docs DOCS.pkl --out Q.jsonl --report R.json [--seed 16]
"""

from __future__ import annotations

import argparse
import itertools
import json
import pickle
import random
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import asdict
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from functools import cached_property, partial
from pathlib import Path
from typing import Any

from cie.eval import brain_questions as B
from cie.eval.brain_questions import (
    ADDRESS,
    EMPTY,
    FIELDS,
    Kind,
    _address,
    _expected,
    _names,
    _nested,
    _person,
    _squash,
    _written,
)
from cie.eval.factbank_5k import _key, _refs, why_unclear
from cie.eval.factbank_multi import KEY, own_score, units
from cie.eval.factbank_test import direct
from cie.eval.memory_test import _norm, final_answer

SEED = 16
LO, HI = 2, 15  # counts asked about
FILTER_MAX = 10  # keys in a filter list
JOIN_MAX = 5  # documents a person's join reaches
VALUE_MAX = 60  # characters of a value filtered on
QUOTE_WORDS, QUOTE_MIN = 10, 8  # a Slack thread is named by its first ten words (eight when it is shorter)
USUAL = 0.5  # a field "most documents hold": more than this share of the system's documents in the haystack
NONE = EMPTY | {"", "unassigned", "not assigned"}
ROLE_WORDS = frozenset((
    "manager", "engineer", "engineering", "lead", "director", "head", "analyst", "owner", "admin", "administrator", "architect",
    "designer", "scientist", "specialist", "officer", "counsel", "legal", "sales", "product", "marketing", "security", "finance",
    "recruiting", "recruiter", "people", "ops", "operations", "success", "solutions", "solution", "account", "accounts",
    "executive", "partner", "partners", "consultant", "coordinator", "intern", "contractor", "vendor", "customer", "client",
    "review", "reviewer", "board", "program", "project", "team", "support", "service", "services", "desk", "office", "platform",
    "infra", "infrastructure", "data", "research", "bot", "system", "automation", "notifications", "alerts", "procurement",
    "billing", "compliance", "council", "committee", "group", "squad", "channel", "digest", "update", "updates", "announcements",
    "release", "releases", "incident", "oncall", "rotation", "assistant", "noreply", "mailer", "daemon", "redwood", "health",
    "analytics", "labs", "systems", "technologies", "cloud", "capital", "bank", "holdings", "portal", "desk", "helpdesk", "inc",
    "llc", "corp", "ltd", "user", "reply", "corporation", "company", "financial", "talent", "events", "marketplace", "payments",
    "payroll", "treasury", "contracts", "purchasing", "accounting", "logistics", "consulting", "advisory", "ventures", "studio",
    "studios", "media", "digital", "software", "global", "international", "foundation", "institute", "university", "hospital",
    "clinic", "pharma", "biotech", "insurance", "energy", "motors", "airlines", "retail", "foods", "industries", "tech", "network",
    "networks", "networking", "staffing", "store", "trust", "privacy", "partnerships", "engagement", "enablement", "intake",
    "renewals", "onboarding", "devops", "infosec", "secops", "sec", "it", "hr", "pm", "eng", "travel", "concierge", "distro",
    "compensation", "benefits", "list", "alias", "leadership", "acme"))
# A name's word: capitalised, with an inner capital only after a surname prefix ("McDonald", "O'Connor", "DeVries"), so that
# "CloudStage" or "AcuityMed" is not a person.
NAME_TOKEN = re.compile(r"(?:(?:O'|D'|Mc|Mac|De|Di|Da|Le|La|Van|Von)?[A-Z][a-z]+)(?:-(?:O'|Mc|Mac)?[A-Z][a-z]+)*")

# ------------------------------------------------------------------ counts and filters
COUNT_FIELDS: dict[str, dict[str, str]] = {  # source: {field: "value", "person" or "open"} (the survey's countgen.py)
    "jira": {"status": "value", "priority": "value", "issue_type": "value", "severity": "value", "customer_tier": "value",
             "project": "value", "open": "open"},
    "linear": {"status": "value", "team": "value", "cycle": "value", "release": "value", "estimate": "value",
               "customer_impact": "value", "priority": "value", "open": "open"},
    "hubspot": {"stage": "value", "account_tier": "value", "hq_region": "value", "forecast_close_month": "value",
                "employee_count_range": "value", "owner": "person", "se_assigned": "person"},
    "google_drive": {"status": "value", "doc_type": "value", "team": "value", "drive_area": "value", "owner": "person"},
    "confluence": {"space": "value", "status": "value", "owner_team": "value", "author": "person"},
    "fireflies": {"call_type": "value", "redwood_owner": "person"},
    "github": {"repo": "value"},
    "gmail": {"thread_type": "value"},
}
COUNT2_SOURCES = tuple(s for s, fs in COUNT_FIELDS.items() if len(fs) >= 2)
CLOSED = {"jira": frozenset({"resolved", "closed"}), "linear": frozenset({"done", "canceled", "cancelled"})}
OPEN_NOTE = {"jira": "status not Resolved or Closed", "linear": "status not Done or Canceled"}
NOUNS = {"jira": ("Jira tickets", "tickets in Jira"), "linear": ("Linear issues", "issues in Linear"),
         "hubspot": ("HubSpot accounts", "accounts in HubSpot"), "google_drive": ("Google Drive documents", "documents in Google Drive"),
         "confluence": ("Confluence pages", "pages in Confluence"), "fireflies": ("Fireflies meetings", "meetings recorded in Fireflies"),
         "github": ("GitHub pull requests", "pull requests on GitHub"), "gmail": ("email threads", "Gmail threads")}
COND = {  # source: {field: the condition after the noun}
    "jira": {"status": "with status {v}", "priority": "with priority {v}", "issue_type": "of type {v}", "severity": "with severity {v}",
             "customer_tier": "for {v}-tier customers", "project": "in the project {v}"},
    "linear": {"status": "with status {v}", "team": "for the {v} team", "cycle": "in cycle {v}", "release": "in release {v}",
               "estimate": "with an estimate of {v}", "customer_impact": "with {v} customer impact", "priority": "with priority {v}"},
    "hubspot": {"stage": "in the {v} stage", "account_tier": "in the {v} tier", "hq_region": "with HQ region {v}",
                "forecast_close_month": "forecast to close in {v}", "employee_count_range": "with an employee count range of {v}",
                "owner": "owned by {v}", "se_assigned": "with {v} as the solutions engineer"},
    "google_drive": {"status": "with status {v}", "doc_type": "of doc type {v}", "team": "from the {v} team",
                     "drive_area": "in the {v} drive area", "owner": "owned by {v}"},
    "confluence": {"space": "in the space {v}", "status": "with status {v}", "owner_team": "owned by the {v} team",
                   "author": "written by {v}"},
    "fireflies": {"call_type": "with call type {v}", "redwood_owner": "owned on the Redwood side by {v}"},
    "github": {"repo": "in the repository {v}"},
    "gmail": {"thread_type": "of type {v}"},
}
COUNT_WORDINGS = ("How many {noun} are there {cond}?", "How many {noun} {cond} are there?", "What is the number of {noun} {cond}?",
                  "Count the {noun} {cond}.", "Can you count the {noun} {cond}?")
COUNT1_SPECIAL = {("jira", "priority"): "How many Jira tickets have priority {v}?",
                  ("jira", "status"): "How many Jira tickets have the status {v}?",
                  ("linear", "cycle"): "How many Linear issues are in cycle {v}?",
                  ("linear", "status"): "How many Linear issues have the status {v}?",
                  ("hubspot", "stage"): "How many HubSpot accounts are in the {v} stage?",
                  ("hubspot", "owner"): "How many HubSpot accounts does {v} own?",
                  ("google_drive", "owner"): "How many Google Drive documents does {v} own?",
                  ("confluence", "space"): "How many Confluence pages are in the space {v}?",
                  ("confluence", "author"): "How many Confluence pages has {v} written?",
                  ("fireflies", "call_type"): "How many {v} meetings are there in Fireflies?",
                  ("fireflies", "redwood_owner"): "How many Fireflies meetings did {v} own for Redwood?",
                  ("github", "repo"): "How many pull requests are there in the GitHub repository {v}?",
                  ("gmail", "thread_type"): "How many email threads are of type {v}?"}
COUNT2_SPECIAL = {("jira", "issue_type", "severity"): "How many Jira tickets of type {v} have severity {w}?",
                  ("jira", "customer_tier", "open"): "How many open Jira tickets (status not Resolved or Closed) are for {v}-tier customers?",
                  ("hubspot", "account_tier", "owner"): "How many {v} HubSpot accounts does {w} own?",
                  ("hubspot", "stage", "owner"): "How many HubSpot accounts in the {v} stage does {w} own?",
                  ("linear", "release", "status"): "How many Linear issues in release {v} have status {w}?",
                  ("linear", "cycle", "status"): "How many Linear issues in cycle {v} have status {w}?",
                  ("linear", "team", "status"): "How many {v} Linear issues have status {w}?"}
LIST_WORDINGS = ("Which {noun} are there {cond}? Give the keys.", "List the {noun} {cond}. Give their keys.",
                 "Give the keys of the {noun} {cond}.", "Which {noun} {cond} are there? List the keys.")
LIST_SPECIAL = {("jira", "priority"): "Which Jira tickets have priority {v}? Give the keys.",
                ("linear", "cycle", "status"): "Which Linear issues in cycle {v} have status {w}? Give the keys.",
                ("linear", "release", "status"): "Which Linear issues in release {v} have status {w}? Give the keys."}
GMAIL_OWNER = ("How many {t} email threads are in {p}'s mailbox?", "How many {t} threads does {p} have in their mailbox?",
               "Count the {t} email threads in the mailbox of {p}.", "In {p}'s mailbox, how many email threads are of type {t}?")
GMAIL_ACCOUNT = ("How many email threads are about the account {a}?", "How many email threads relate to the account {a}?",
                 "Count the email threads whose account is {a}.")

# ------------------------------------------------------------------ history
HISTORY_FIELDS = ("comments", "updates", "progress_updates", "activity", "activity_log", "timeline", "recent_activities",
                  "recent_activity", "activity_timeline", "activities", "work_log", "review_comments")
ACTIVITY_FIELDS = ("recent_activities", "recent_activity", "activity_timeline", "activities", "activity_log")
SYSTEM = {"linear": "Linear issue", "jira": "Jira ticket"}
CREATED = {"linear": ("When was the Linear issue {k} created?", "On what date was Linear issue {k} created?",
                      "What is the creation date of the Linear issue {k}?"),
           "jira": ("When was Jira ticket {k} opened?", "When was the Jira ticket {k} created?", "On what date was Jira ticket {k} opened?"),
           "hubspot": ('When was the HubSpot account "{t}" created?', 'On what date was the HubSpot account "{t}" created?',
                       'What is the creation date of the HubSpot account "{t}"?'),
           "github": ("When was PR #{n} opened?", "On what date was pull request #{n} opened?", "When was the GitHub pull request #{n} created?")}
UPDATED = {"linear": ("When was {k} last updated?", "When was the Linear issue {k} last updated?",
                      "What is the last-updated date of Linear issue {k}?"),
           "jira": ("When was the Jira ticket {k} last updated?", "When did Jira ticket {k} last change?",
                    "What is the last-updated date of the Jira ticket {k}?"),
           "hubspot": ('When was the HubSpot account "{t}" last updated?', 'What is the last-updated date of the HubSpot account "{t}"?',
                       'When did the HubSpot account "{t}" last change?')}
DAYS_WORDINGS = ("How many days after it was opened was PR #{n} merged?", "How long did pull request #{n} take to get merged, in days?",
                 "How many days passed between PR #{n} being opened and being merged?")
MOVED_WORDINGS = ("On what date did {k} move to {s}?", "When was {k} moved to {s}?", "When did the {sys} {k} change to {s}?")
FIRST_COMMENT = ("Who left the first comment on the {sys} {k}?", "Who commented first on {sys} {k}?",
                 "Who wrote the earliest comment on the {sys} {k}?")
LAST_COMMENT = ("When was the latest comment on {sys} {k} posted?", "What is the date of the most recent comment on the {sys} {k}?",
                "When did someone last comment on the {sys} {k}?")
FIRST_ACTIVITY = ('When was the first recorded activity with the HubSpot account "{t}"?',
                  'What is the date of the earliest timeline entry for the HubSpot account "{t}"?',
                  'When does the activity timeline of the HubSpot account "{t}" begin?')
DATE_LED = re.compile(r"^\s*\[?(\d{4}-\d{2}-\d{2})\b")
ENTRY = re.compile(r"^\s*\[?(\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2}:\d{2})(?::\d{2})?\s*(?:Z|UTC|[A-Z]{2,4}|[+-]\d{2}:?\d{2})?)?\]?\s*"
                   r"(?:[-–—:|]\s*)?([A-Z][\w'.-]+(?: [A-Z][\w'.-]+){1,2})\s*(?:\(([^)]*)\))?\s*:\s+(.+)$", re.S)
MOVE = (r"(?:\b(?:moving|moved)\s+(?:(?:the|this)\s+)?(?:(?:ticket|issue)\s+)?to\s+|\bchanged\s+(?:the\s+)?status\s+to\s+"
        r"|\bmarking\s+(?:(?:this|the)\s+)?(?:(?:ticket|issue)\s+)?as\s+)['\"‘“]?")
MOVE_LOOSE = (r"\b(?:mov(?:ed|ing)|transition(?:ed|ing)|chang(?:ed|ing)|set|mark(?:ed|ing)|flipp(?:ed|ing)|switch(?:ed|ing))\b"
              r"[^.\n;]{0,35}?\b(?:to|as)\s+['\"‘“]?")
MOVE_FIELDS = ("comments", "updates", "activity", "activity_log", "timeline")

# ------------------------------------------------------------------ email and chat
SENDER = ('Who sent the first email in the thread "{s}"?', 'Who started the email thread "{s}"?',
          'Who wrote the opening message of the email thread "{s}"?')
STARTED = ('When did the email thread "{s}" start?', 'On what date was the first email of the thread "{s}" sent?',
           'What date does the email thread "{s}" begin on?')
TO = ('Who was the first email in the thread "{s}" sent to?', 'Who received the opening email of the thread "{s}"?',
      'To whom was the first message in the email thread "{s}" addressed?')
CC = ('Who was copied on the first email in "{s}"?', 'Who was cc\'d on the opening message of the email thread "{s}"?',
      'Which people were on the Cc line of the first email in the thread "{s}"?')
MESSAGES = ('How many messages are in the email thread "{s}"?', 'How many emails does the thread "{s}" contain?',
            'What is the number of messages in the email thread "{s}"?')
ATTACHED = ('What files were attached in the email thread "{s}"?', 'Which attachments came with the email thread "{s}"?',
            'List the attachments of the email thread "{s}".')
ACCOUNT = ('Which account is the email thread "{s}" about?', 'What customer account does the email thread "{s}" relate to?',
           'Which account is the thread "{s}" tied to?')
CHANNEL = ('In which Slack channel was the thread starting "{q}" posted?', 'Which Slack channel had the thread that begins "{q}"?',
           'Where on Slack was the thread that opens with "{q}" posted? Name the channel.')
STARTER = ('Who started the Slack thread that begins "{q}"?', 'Who posted the first message of the Slack thread starting "{q}"?',
           'Who kicked off the Slack thread that opens with "{q}"?')
SPEAKER = re.compile(r"^\s*([A-Za-z][\w .'()-]{0,39}?)\s*:\s+(.*)$")
# What a thread's related_account holds when it is no customer account: on a hiring thread, a candidate, a recruiter or the
# candidate's employer; elsewhere a label of a candidate, an internal matter or a team ('Candidate: Alex Romero',
# 'candidate:kaiya-sundar', 'Internal - Monthly QBR prep', 'Runtime Team hiring').
HIRING = frozenset({"hiring", "recruiting", "recruitment"})
LABEL = re.compile(r"\b(?:candidates?|internal|hiring|team)\b", re.I)

# ------------------------------------------------------------------ two documents
LINK = {  # kind: (field of the Linear issue, value type, training-style wordings)
    "pr_issue_project": ("project", "value", ("Which Linear project is the issue linked from pull request #{n} part of?",
                                              "Pull request #{n} links a Linear issue. What project does that issue belong to?",
                                              "What project is the Linear ticket referenced by PR #{n} in?")),
    "pr_issue_creator": ("creator", "person", ("Who created the Linear issue that pull request #{n} is linked to?",
                                               "PR #{n} references a Linear ticket. Who created it?",
                                               "Who is the creator of the Linear issue tied to pull request #{n}?")),
    "pr_issue_team": ("team", "value", ("Which Linear team does the issue linked from PR #{n} belong to?",
                                        "Pull request #{n} references a Linear issue. Which team is that issue on?",
                                        "What is the team of the Linear ticket tied to pull request #{n}?")),
}
JOIN = {  # kind: (source, its person field, how the question names it)
    "author_issues": ("github", "author", ("Which Linear issues are assigned to the author of pull request #{n}? Give the keys.",
                                           "Pull request #{n} was opened by someone. List the Linear issues assigned to that person. "
                                           "Give the keys.",
                                           "Give the keys of the Linear issues assigned to whoever authored PR #{n}.")),
    "reporter_issues": ("jira", "reporter", ("Which Linear issues are assigned to the person who reported Jira ticket {k}? Give the keys.",
                                             "Jira ticket {k} was reported by someone. Which Linear issues are assigned to them? "
                                             "Give the keys.",
                                             "List the keys of the Linear issues assigned to the reporter of Jira ticket {k}.")),
}
OWNER_COUNT = ('How many HubSpot accounts does the Redwood owner of the meeting "{t}" own?',
               'The meeting "{t}" had a Redwood owner. How many HubSpot accounts are owned by that person?',
               'Count the HubSpot accounts owned by whoever owned the meeting "{t}" on the Redwood side.')
OWNER_NAME = ('Which HubSpot account is owned by the Redwood owner of the meeting "{t}"?',
              'The Redwood owner of the meeting "{t}" owns one HubSpot account. Which one?',
              'What HubSpot account belongs to the person who owned the meeting "{t}" for Redwood?')

# ------------------------------------------------------------------ field absent
ABSENT: dict[tuple[str, str], tuple[str, tuple[str, ...]]] = {  # (source, field): (other fields mentioning it, wordings)
    ("hubspot", "csm_assigned"): (r"\bcsm\b|customer success manager",
                                  ('Who is the customer success manager assigned to the HubSpot account "{t}"?',
                                   'Who is the CSM for the HubSpot account "{t}"?', 'Which CSM covers the HubSpot account "{t}"?')),
    ("hubspot", "forecast_close_month"): (r"close (?:date|month)|forecast",
                                          ('What is the forecast close month of the HubSpot account "{t}"?',
                                           'In which month is the HubSpot account "{t}" forecast to close?')),
    ("linear", "due_date"): (r"\bdue\b|deadline", ("When is the Linear issue {k} due?", "What is the due date of the Linear issue {k}?",
                                                   "By when does Linear issue {k} need to be done?")),
    ("linear", "customer_impact"): (r"customer impact", ("What is the customer impact of the Linear issue {k}?",
                                                         "How much customer impact does Linear issue {k} have?")),
    ("linear", "release"): (r"\brelease\b", ("Which release is the Linear issue {k} in?", "What release is Linear issue {k} targeted for?")),
    ("jira", "sla_due_at"): (r"\bSLA\b", ("When is the SLA due for Jira ticket {k}?", "What is the SLA due date of the Jira ticket {k}?")),
    ("jira", "first_response_due_at"): (r"first response", ("When is the first response due for Jira ticket {k}?",
                                                            "By when must the first response on Jira ticket {k} go out?")),
    ("fireflies", "crm_deal_id"): (r"CRM-|\bdeal", ('What is the CRM deal ID of the meeting "{t}"?',
                                                    'Which CRM deal is the meeting "{t}" linked to? Give the deal ID.')),
    ("gmail", "related_account"): (r"\baccount\b", ('Which account is the email thread "{s}" about?',
                                                    'What customer account does the email thread "{s}" relate to?')),
}
# Fields whose scale has a level "none" (Linear customer_impact: none, low, medium, high): there "none" is the answer (no
# customer impact), not an empty field.
NONE_LEVEL = frozenset({("linear", "customer_impact")})

# ------------------------------------------------------------------ embedded question words (the FIELDS kinds reworded)
EMBEDDED: dict[str, tuple[str, ...]] = {
    "drive_owner": ('Do you know who owns the Google Drive document "{t}"?', 'Can you remind me who the owner of the Drive doc "{t}" is?',
                    'Any idea whose Google Drive document "{t}" is?'),
    "drive_status": ('Do you know what the status of the Google Drive document "{t}" is?',
                     'Could you tell me what state the Drive doc "{t}" is in?',
                     'Can you remind me where the Google Drive document "{t}" stands? I need its status.'),
    "drive_created": ('Do you know when the Google Drive document "{t}" was created?', 'Can you remind me when the Drive doc "{t}" was created?',
                      'Could you tell me when the Google Drive document "{t}" was first created?'),
    "confluence_author": ('Do you know who wrote the Confluence page "{t}"?', 'Can you remind me who authored the Confluence page "{t}"?',
                          'Any idea who the author of the Confluence page "{t}" is?'),
    "confluence_space": ('Do you know which Confluence space the page "{t}" is in?',
                         'Could you tell me which Confluence space holds the page "{t}"?',
                         'Can you remind me what Confluence space the page "{t}" lives in?'),
    "confluence_updated": ('Do you know when the Confluence page "{t}" was last updated?',
                           'Can you remind me when the Confluence page "{t}" was last updated?',
                           'Any idea when the Confluence page "{t}" was last updated?'),
    "hubspot_owner": ('Do you know who owns the HubSpot account "{t}"?', 'Can you remind me who the account owner of the HubSpot account "{t}" is?',
                      'Any idea who owns the HubSpot account "{t}"?'),
    "hubspot_stage": ('Do you know what stage the HubSpot account "{t}" is in?', 'Could you tell me which deal stage the HubSpot account "{t}" is in?',
                      'Can you remind me what stage the HubSpot account "{t}" has reached?'),
    "hubspot_close": ('Do you know which month the HubSpot account "{t}" is forecast to close in?',
                      'Can you remind me what the forecast close month of the HubSpot account "{t}" is?',
                      'Could you tell me which month the HubSpot account "{t}" is expected to close in?'),
    "hubspot_se": ('Do you know who the solutions engineer on the HubSpot account "{t}" is?',
                   'Can you remind me which solutions engineer is assigned to the HubSpot account "{t}"?',
                   'Any idea who the assigned solutions engineer for the HubSpot account "{t}" is?'),
    "jira_status": ("Do you know what the status of the Jira ticket {k} is?", "Could you tell me what state Jira ticket {k} is in?",
                    "Can you remind me where the Jira ticket {k} stands? Give its status."),
    "jira_priority": ("Do you know what priority the Jira ticket {k} has?", "Could you tell me what the priority of Jira ticket {k} is?",
                      "Can you remind me which priority Jira ticket {k} was given?"),
    "jira_sla": ("Do you know when the SLA is due for Jira ticket {k}?", "Can you remind me when the SLA on the Jira ticket {k} is due?",
                 "Could you tell me when the SLA of Jira ticket {k} falls due?"),
    "jira_reporter": ("Do you know who reported the Jira ticket {k}?", "Can you remind me who the reporter of Jira ticket {k} is?",
                      "Any idea who reported Jira ticket {k}?"),
    "jira_ticket_assignee": ("Do you know who is assigned to the Jira ticket {k}?", "Can you remind me who the assignee of Jira ticket {k} is?",
                             "Could you tell me who Jira ticket {k} is assigned to?"),
    "jira_customer": ("Do you know which customer the Jira ticket {k} is for?",
                      "Could you tell me which customer company raised Jira ticket {k}?",
                      "Can you remind me what customer Jira ticket {k} belongs to?"),
    "linear_issue_status": ("Do you know what the status of the Linear issue {k} is?", "Could you tell me what state Linear issue {k} is in?",
                            "Can you remind me where Linear issue {k} stands? Give its status."),
    "linear_issue_priority": ("Do you know what priority the Linear issue {k} has?",
                              "Could you tell me what the priority of Linear issue {k} is?",
                              "Can you remind me which priority Linear issue {k} has?"),
    "linear_issue_assignee": ("Do you know who is assigned to the Linear issue {k}?",
                              "Can you remind me who the assignee of Linear issue {k} is?",
                              "Any idea who Linear issue {k} is assigned to?"),
    "linear_issue_project": ("Do you know which Linear project the issue {k} is part of?",
                             "Could you tell me what project the Linear issue {k} belongs to?",
                             "Can you remind me which project Linear issue {k} sits in?"),
    "linear_issue_creator": ("Do you know who created the Linear issue {k}?", "Can you remind me who the creator of Linear issue {k} is?",
                             "Any idea who created Linear issue {k}?"),
    "pr_author": ("Do you know who authored pull request #{n}?", "Can you remind me who opened PR #{n}?",
                  "Any idea who the author of the GitHub pull request #{n} is?"),
    "pr_repo": ("Do you know which repository pull request #{n} is in?", "Could you tell me which GitHub repository PR #{n} was opened in?",
                "Can you remind me what repo pull request #{n} belongs to?"),
    "pr_merged": ("Do you know when pull request #{n} was merged?", "Can you remind me when PR #{n} was merged?",
                  "Could you tell me when the GitHub pull request #{n} got merged?"),
    "meeting_owner": ('Do you know who the Redwood owner of the meeting "{t}" was?', 'Can you remind me which Redwood person owned the meeting "{t}"?',
                      'Any idea who owned the meeting "{t}" on the Redwood side?'),
    "meeting_customer": ('Do you know which customer the meeting "{t}" was with?',
                         'Could you tell me what customer company was in the meeting "{t}"?',
                         'Can you remind me which customer joined the meeting "{t}"?'),
    "meeting_date": ('Do you know when the meeting "{t}" was recorded?', 'Can you remind me when the meeting "{t}" took place?',
                     'Could you tell me when the meeting "{t}" happened?'),
}
PLACEHOLDER = {"title": "t", "key": "k", "pr": "n"}

# ------------------------------------------------------------------ the catalogue
_COUNT_SCORE = "count_hit: the first number in the answer line equals n"
CATALOGUE: dict[str, Kind] = {
    **{f"count1_{s}": Kind(f"count1_{s}", "counts", "count", _COUNT_SCORE, f"{s}: documents holding one field value")
       for s in COUNT_FIELDS},
    **{f"count2_{s}": Kind(f"count2_{s}", "counts", "count", _COUNT_SCORE, f"{s}: documents holding two field values")
       for s in COUNT2_SOURCES},
    "count_gmail": Kind("count_gmail", "counts", "count", _COUNT_SCORE, "gmail: threads of a type in one mailbox, or about one account"),
    "filter_list": Kind("filter_list", "counts", "filter", "key list, F1 (factbank_test.direct)", "jira, linear: the keys of a filtered set"),
    **{k: Kind(k, "history", "history", s, w) for k, s, w in (
        ("created_on", "date, exact", "linear, jira, hubspot, github: created_at"),
        ("last_updated", "date, exact", "linear, jira, hubspot: updated_at"),
        ("pr_days_to_merge", _COUNT_SCORE, "github: merged_at - created_at in days"),
        ("moved_to_status", "date, exact", "linear, jira: the dated entry moving the ticket to its present status"),
        ("first_commenter", "value in the answer (value_hit)", "linear, jira: the author of the earliest dated comment"),
        ("last_comment_date", "date, exact", "linear, jira: the date of the latest dated comment"),
        ("hubspot_first_activity", "date, exact", "hubspot: the earliest timeline date"))},
    **{k: Kind(k, "email_chat", g, s, w) for k, g, s, w in (
        ("email_sender", "email", "value in the answer (value_hit)", "gmail: the first message's From display name"),
        ("email_date", "email", "date, exact", "gmail: first_email_at, the earliest message's date"),
        ("email_to", "email", "person names, F1 (name_f1)", "gmail: the first message's To"),
        ("email_cc", "email", "person names, F1 (name_f1)", "gmail: the first message's Cc"),
        ("email_count", "email", _COUNT_SCORE, "gmail: message_count, equal to the messages written"),
        ("email_attachments", "email", "file names, F1 (files_f1)", "gmail: attachments"),
        ("email_account", "email", "value in the answer (value_hit)", "gmail: related_account"),
        ("slack_channel", "chat", "value in the answer (value_hit)", "slack: the channel of a thread quoted by its first words"),
        ("slack_starter", "chat", "value in the answer (value_hit)", "slack: the first speaker, a full name"))},
    **{k: Kind(k, "multi", "link", "value in the answer (factbank_multi.own_score)", f"github -> linear: the linked issue's {f}")
       for k, (f, _, _) in LINK.items()},
    **{k: Kind(k, "multi", "combine", "key list, F1 (factbank_multi.own_score)", f"{s}.{f} -> linear issues assigned to the same name")
       for k, (s, f, _) in JOIN.items()},
    "owner_accounts": Kind("owner_accounts", "multi", "combine", "value in the answer (factbank_multi.own_score)",
                           "fireflies.redwood_owner -> hubspot accounts owned by the same name: how many, or which one"),
    "field_absent": Kind("field_absent", "unanswerable", "absent", "1 if the answer says not found, else 0",
                         "a usually-present field empty, missing, TBD or N/A on the named document"),
    **{f"embedded_{k}": Kind(f"embedded_{k}", "single", "embedded", f"as {k} (brain_questions.score)",
                             f"{k} asked after a verb of knowing or telling") for k in EMBEDDED},
}
COUNT_KINDS = frozenset(k for k in CATALOGUE if k.startswith(("count1_", "count2_")) or k in ("count_gmail", "pr_days_to_merge", "email_count"))
DEFAULT_MIX = {"count": 16, "filter": 6, "history": 16, "email": 14, "chat": 6, **{k: 2 for k in (*LINK, *JOIN, "owner_accounts")},
               "absent": 12, "embedded": 12}


def kinds() -> list[dict[str, str]]:
    """The catalogue: each new kind's name, family, group, how it is scored and where its questions come from."""
    return [asdict(k) for k in CATALOGUE.values()]


def family(q: dict[str, Any]) -> str:
    """The question's family: its own, its kind's, or ``brain_questions.family``."""
    if q.get("family"):
        return q["family"]
    if q.get("kind") in CATALOGUE:
        return CATALOGUE[q["kind"]].family
    return B.family(q)


# ------------------------------------------------------------------ helpers
def _note(aside: Counter | None, why: str) -> None:
    if aside is not None:
        aside[why] += 1


def _none(v: Any) -> bool:
    """An empty field: missing, null, an empty list or text, or 'TBD', 'N/A', 'none', 'unassigned' and the like."""
    if v is None or v == [] or v == {}:
        return True
    return isinstance(v, str | int | float | bool) and str(v).strip().lower() in NONE


def _items(v: Any) -> list[str] | None:
    """A list field's entries, or a text field's lines (a literal backslash-n counts as a line break); None when an entry is
    not text."""
    if isinstance(v, list):
        return [x for x in v if isinstance(x, str) and x.strip()] if all(isinstance(x, str) for x in v) else None
    if isinstance(v, str):
        return [x for x in v.replace("\\n", "\n").split("\n") if x.strip()]
    return [] if v is None else None


def _valid(d: str) -> bool:
    try:
        date.fromisoformat(d)
    except ValueError:
        return False
    return True


def _when(s: Any) -> datetime | None:
    """A timestamp, ISO or as an email header writes it ('Sat, 05 Dec 2026 09:12:00 -0800'), or None."""
    s = str(s or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(re.sub(r"([+-]\d{2}):(\d{2})$", r"\1\2", s))  # '-08:00' as '-0800'
    except (TypeError, ValueError, IndexError):
        return None


def _day(t: datetime | None) -> str | None:
    """The date of a timestamp with a time zone, when its local date is also its UTC date (one reading), else None."""
    if t is None or t.tzinfo is None or t.astimezone(UTC).date() != t.date():
        return None
    return t.date().isoformat()


def _full_name(raw: Any) -> str | None:
    """A person written as a first and last name ('Maya Chen', "Liam O'Connor"), or None: one word, an initial ('Carla R',
    'J. Rivera'), a role, a team, a bot or a company ('Product Review', 'Portal Support')."""
    p = _person(raw)
    if p is None:
        return None
    toks = p.split()
    if not 2 <= len(toks) <= 3 or not all(NAME_TOKEN.fullmatch(t) for t in toks) or any(t.lower() in ROLE_WORDS for t in toks):
        return None
    return p


def _in(name: str, text: str) -> bool:
    """Whether the name is written in the text as whole words, whatever the case."""
    return bool(re.search(r"(?<![\w-])" + re.escape(_norm(name)) + r"(?![\w-])", _norm(text)))


def _says(sq: str, text: str) -> bool:
    """Whether a run of the text's words, squashed (``brain_questions._squash``), is the squashed name ``sq``: 'Nexa Health'
    writes 'NexaHealth'."""
    w = re.findall(r"[^\W_]+", str(text).lower())
    return any("".join(w[i:j]) == sq for i in range(len(w)) for j in range(i + 1, min(len(w), i + 8) + 1))


def _answers(e: dict[str, Any]) -> list[str]:
    return [str(v) for v in ([e["value"]] if "value" in e else []) + ([e["date"]] if "date" in e else [])
            + list(e.get("names") or []) + list(e.get("files") or []) + list(e.get("ids") or [])]


def _leaks(c: dict[str, Any]) -> bool:
    """Whether a wording of the candidate writes its answer (or a part of it) in the question, whatever the spaces and hyphens
    ('Helios Health' for 'HeliosHealth')."""
    return any(_in(a, q) or (_squash(a) and _says(_squash(a), q))
               for q in (w.format(**c["fmt"]) for w in c["wordings"]) for a in _answers(c["expected"]))


def _emit(kind: str, cands: list[dict[str, Any]], rng: random.Random, cap: int | None,
          aside: Counter | None = None) -> list[dict[str, Any]]:
    """Up to ``cap`` candidates (all when None) as questions, each in one of its wordings drawn by ``rng``, as
    ``brain_questions._emit`` writes them (that one reads the old catalogue). A candidate whose answer is written in the
    question is set aside first."""
    kept = []
    for c in cands:
        if _leaks(c):
            _note(aside, "answer in the question")
        else:
            kept.append(c)
    if cap is not None and cap < len(kept):
        kept = rng.sample(kept, cap)
    k = CATALOGUE[kind]
    out = []
    for i, c in enumerate(kept, 1):
        w = rng.choice(c["wordings"])
        out.append({"id": f"{kind}-{i:03d}", "group": k.group, "kind": kind, "family": k.family,
                    **({"field": c["field"]} if c.get("field") is not None else {}), "question": w.format(**c["fmt"]),
                    "expected": c["expected"], "gold_docs": sorted(set(c["gold"])), "pieces": [str(p) for p in c["pieces"]],
                    "generated": True, **c.get("extra", {})})
    return out


class Haystack:
    """The documents, with what several generators read worked out once: the names that address documents, the written
    text and its words, each source's documents, the Slack quotes and the count candidates."""

    def __init__(self, docs: list[dict[str, Any]]):
        self.docs = docs

    @cached_property
    def names(self) -> dict[str, Counter]:
        return _names(self.docs)

    @cached_property
    def by_source(self) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict]] = defaultdict(list)
        for d in sorted(self.docs, key=lambda d: d["dsid"]):
            out[d["source"]].append(d)
        return out

    def of(self, source: str) -> list[dict[str, Any]]:
        return self.by_source.get(source, [])

    @cached_property
    def texts(self) -> list[str]:
        """Each document's written text in lower case, as ``brain_questions._written`` writes it."""
        return [_written([d]) for d in self.docs]

    @cached_property
    def word_docs(self) -> dict[str, list[int]]:
        """The documents (indexes) whose written text holds each run of letters and digits."""
        out: dict[str, list[int]] = defaultdict(list)
        for i, t in enumerate(self.texts):
            for w in set(re.findall(r"[a-z0-9]+", t)):
                out[w].append(i)
        return out

    def holders(self, s: str) -> list[int]:
        """The indexes of the documents whose written text holds ``s`` (lower case). Only documents holding every run of
        letters and digits strictly inside its first and last space are read: in any text that holds ``s`` those runs stand
        alone, while its first and last words may be parts of longer ones."""
        inner = s[s.find(" ") + 1: s.rfind(" ")] if s.count(" ") >= 2 else ""
        runs = sorted(set(re.findall(r"[a-z0-9]+", inner)), key=lambda w: len(self.word_docs.get(w, ())))
        if not runs:
            return [i for i, t in enumerate(self.texts) if s in t]
        cands = set(self.word_docs.get(runs[0], ()))
        for w in runs[1:3]:
            cands &= set(self.word_docs.get(w, ()))
        return sorted(i for i in cands if s in self.texts[i])

    @cached_property
    def slack_quotes(self) -> dict[str, tuple[str, str] | str]:
        """Each Slack thread's quote of its first message's first ten words and its first speaker, or why it has none."""
        index = {d["dsid"]: i for i, d in enumerate(self.docs)}
        out: dict[str, tuple[str, str] | str] = {}
        for d in self.of("slack"):
            first = _first_line(d["raw"])
            if first is None:
                out[d["dsid"]] = "first line unparsed"
                continue
            spk, text = first
            words = text.split()
            quote = " ".join(words[:QUOTE_WORDS]).strip()
            if len(words) < QUOTE_MIN:
                out[d["dsid"]] = "first message too short"
            elif re.search(r"[\"\\“”]", quote):
                out[d["dsid"]] = "quote unusable"
            elif self.holders(quote.lower()) != [index[d["dsid"]]]:
                out[d["dsid"]] = "quote not unique"
            else:
                out[d["dsid"]] = (quote, spk)
        return out

    def address(self, d: dict[str, Any]) -> tuple[dict[str, str] | None, str]:
        """How a question names the document (``brain_questions._address``; an email thread by its subject)."""
        if d["source"] != "gmail":
            return _address(d, self.names)
        t = str(d["title"] or "").strip()
        if len(t) < 6 or '"' in t:
            return None, "title unusable"
        if self.names["titles"][_norm(t)] != 1 or self.subjects[_subject(t)] != 1:
            return None, "named twice"
        return {"s": t}, t

    @cached_property
    def subjects(self) -> Counter:
        return Counter(_subject(d["title"]) for d in self.of("gmail"))

    @cached_property
    def counts(self) -> _Counts:
        return _Counts(self)


def _subject(t: Any) -> str:
    return re.sub(r"^(?:(?:re|fwd?|fw)\s*:\s*)+", "", _norm(t))


# ------------------------------------------------------------------ counts and filters
def _count_value(d: dict[str, Any], field: str, typ: str) -> str | None:
    """The value a document holds for a count's field: its status read as open or closed, a person with a full name, or a
    short plain value; None when it holds none of these."""
    raw = d["raw"]
    if typ == "open":
        s = str(raw.get("status") or "").strip().lower()
        return None if not s else "open" if s not in CLOSED[d["source"]] else "closed"
    v = raw.get(field)
    if isinstance(v, list | dict):
        return None
    if typ == "person":
        p = _person(v)
        return p if p and len(p.split()) >= 2 else None
    s = str(v if v is not None else "").strip()
    return None if not s or s.lower() in EMPTY or len(s) > VALUE_MAX else s


def _listed(ds: list[dict[str, Any]], field: str) -> set[str]:
    """The squashed entries of the field where a document holds it as a list or a mapping: a value there would count too."""
    out: set[str] = set()
    for d in ds:
        v = d["raw"].get(field)
        if isinstance(v, list | dict):
            out |= {_squash(x) for x in (v.values() if isinstance(v, dict) else v) if isinstance(x, str)}
    return out


def _phrase(source: str, filters: list[tuple[str, str]]) -> tuple[str, str]:
    """The noun ('open Jira tickets (status not Resolved or Closed)') and the condition ('with priority P2 of type Bug')."""
    opened = any(f == "open" for f, _ in filters)
    conds = [COND[source][f].format(v=v) for f, v in filters if f != "open"]
    trailing = ("with", "owned", "written")
    conds.sort(key=lambda c: c.startswith(trailing))
    cond = conds[0] if conds else ""
    if len(conds) == 2:
        cond += (" " if conds[1].startswith(trailing) and not conds[0].startswith(trailing) else " and ") + conds[1]
    return ("open " if opened else "") + "{noun}" + (f" ({OPEN_NOTE[source]})" if opened else ""), cond


def _count_wordings(source: str, filters: list[tuple[str, str]], listing: bool) -> tuple[str, ...]:
    noun_t, cond = _phrase(source, filters)
    if not cond:  # "open" alone is never asked
        return ()
    base = LIST_WORDINGS if listing else COUNT_WORDINGS
    out = [w.format(noun=noun_t.format(noun=n), cond=cond) for w in base for n in NOUNS[source][: 1 if listing else 2]]
    fields = tuple(f for f, _ in filters)
    vals = [v for _, v in filters]
    special = LIST_SPECIAL if listing else {**COUNT1_SPECIAL, **COUNT2_SPECIAL}
    for order in ((0, 1), (1, 0)) if len(filters) == 2 else ((0,),):
        key = (source, *(fields[i] for i in order))
        if key in special:
            out.append(special[key].format(v=vals[order[0]], **({"w": vals[order[1]]} if len(order) == 2 else {})))
    return tuple(dict.fromkeys(_literal(w) for w in out))


def _literal(w: str) -> str:
    """A wording already filled in, kept as it is when ``_emit`` formats it."""
    return w.replace("{", "{{").replace("}", "}}")


class _Counts:
    """Every count and filter candidate of the haystack, worked out once for all the count kinds: one or two fields of one
    source, values grouped as one name ('In Progress', 'in-progress'), counts of 2 to 15."""

    def __init__(self, hay: Haystack):
        self.cands: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.aside: dict[str, Counter] = defaultdict(Counter)
        for src, spec in COUNT_FIELDS.items():
            self._source(hay, src, spec)

    def _source(self, hay: Haystack, src: str, spec: dict[str, str]) -> None:
        ds = hay.of(src)
        keys = {d["dsid"]: _key(d) for d in ds}
        groups: dict[tuple[str, str], tuple[frozenset[str], str]] = {}
        bad: dict[tuple[str, str], str] = {}
        for f, typ in spec.items():
            members: dict[str, set[str]] = defaultdict(set)
            shown: dict[str, Counter] = defaultdict(Counter)
            for d in ds:
                v = _count_value(d, f, typ)
                if v and _squash(v):
                    members[_squash(v)].add(d["dsid"])
                    shown[_squash(v)][v] += 1
            if typ == "open":
                if "open" in members:
                    groups[(f, "open")] = (frozenset(members["open"]), "open")
                continue
            names = {v for c in shown.values() for v in c}
            inner, listed = _nested(names), _listed(ds, f)
            for sq, dsids in members.items():
                groups[(f, sq)] = (frozenset(dsids), shown[sq].most_common(1)[0][0])
                if sq in inner:
                    bad[(f, sq)] = "named inside another"
                elif sq in listed:
                    bad[(f, sq)] = "value also in a list"
        seen: set[frozenset[str]] = set()

        def add(kind: str, picked: list[tuple[str, str]], s: frozenset[str]) -> None:
            why = next((bad[g] for g in picked if g in bad), None)
            if why is None and s in seen:
                why = "same set as another filter"
            if why:
                self.aside[kind][why] += 1
                return
            seen.add(s)
            filters = [(f, groups[(f, sq)][1]) for f, sq in picked]
            gold = sorted(s)
            ks = sorted(k for g in gold if (k := keys.get(g)))
            n = len(s)
            cand = {"source": src, "filters": filters, "n": n, "gold": gold}
            ws = _count_wordings(src, filters, False)
            if not ws:
                return
            self.cands[kind].append({**cand, "fmt": {}, "expected": {"value": str(n)}, "wordings": ws,
                                     "pieces": [v for _, v in filters if v != "open"] + [str(n)] + ks,
                                     "extra": {"filters": [list(x) for x in filters]}})
            if src in ("jira", "linear") and n <= FILTER_MAX:
                if any(not k or not KEY.fullmatch(k) or hay.names["keys"][k] != 1 for k in (keys.get(g) for g in gold)):
                    self.aside["filter_list"]["named twice"] += 1
                else:
                    self.cands["filter_list"].append({"fmt": {}, "expected": {"ids": ks, "id_kind": "key"}, "gold": gold,
                                                      "wordings": _count_wordings(src, filters, True),
                                                      "pieces": [v for _, v in filters if v != "open"] + ks,
                                                      "extra": {"filters": [list(x) for x in filters]}})
            elif src in ("jira", "linear"):
                self.aside["filter_list"]["too many"] += 1

        for (f, sq), (s, _) in sorted(groups.items()):
            if f == "open":
                continue
            if not LO <= len(s) <= HI:
                self.aside[f"count1_{src}"]["count outside 2-15"] += 1
                continue
            add(f"count1_{src}", [(f, sq)], s)
        if src not in COUNT2_SOURCES:
            return
        for g1, g2 in itertools.combinations(sorted(groups), 2):
            if g1[0] == g2[0]:
                continue
            a, b = groups[g1][0], groups[g2][0]
            s = a & b
            if len(s) < LO or s == a or s == b:  # both conditions must narrow the set
                continue
            if len(s) > HI:
                self.aside[f"count2_{src}"]["count outside 2-15"] += 1
                continue
            add(f"count2_{src}", [g1, g2], s)


def count_questions(kind: str, hay: Haystack, rng: random.Random, cap: int | None = None,
                    aside: Counter | None = None) -> list[dict[str, Any]]:
    """How many documents of one source hold one field value (count1) or two (count2), and the keys of such a set of Jira
    or Linear items (filter_list, at most ``FILTER_MAX``). A value written inside another value of the field, a value some
    document holds inside a list, a set already asked about, and a count outside 2 to 15 are set aside."""
    if aside is not None:
        aside.update(hay.counts.aside.get(kind, Counter()))
    return _emit(kind, hay.counts.cands.get(kind, []), rng, cap, aside)


def gmail_counts(hay: Haystack, rng: random.Random, cap: int | None = None, aside: Counter | None = None) -> list[dict[str, Any]]:
    """How many email threads of one type are in one person's mailbox, and how many are about one account (2 to 15).
    A mailbox owner who is not a person, a type written inside another type of the same mailbox (or holding one: 'sales'
    beside 'pre-sales'), 'Acme*' accounts, an account written inside another, an account some thread holds in a list or
    whose name another thread's subject writes, and an account that is no customer account (``_not_account``, on any of
    its threads) are set aside. Types are compared within the one mailbox counted: a 'pre-sales' thread elsewhere leaves
    'sales' in this mailbox one reading."""
    g = hay.of("gmail")
    cands = []
    owned: dict[tuple[str, str], list[dict]] = defaultdict(list)
    handles: dict[str, Counter] = defaultdict(Counter)
    mine: dict[str, set[str]] = defaultdict(set)  # each owner's thread types, as written
    for d in g:
        p, t = _full_name(d["raw"].get("mailbox_owner")), str(d["raw"].get("thread_type") or "").strip()
        if p and t and t.lower() not in EMPTY:
            owned[(p, _squash(t))].append(d)
            handles[p][str(d["raw"]["mailbox_owner"]).strip()] += 1
            mine[p].add(t)
    nested = {p: _nested(ts) for p, ts in mine.items()}
    for (p, sq), ds in sorted(owned.items()):
        if not LO <= len(ds) <= HI:
            _note(aside, "count outside 2-15")
            continue
        if sq in nested[p]:
            _note(aside, "named inside another")
            continue
        t = Counter(str(d["raw"]["thread_type"]).strip() for d in ds).most_common(1)[0][0]
        h = handles[p].most_common(1)[0][0]
        ws = tuple(dict.fromkeys(_literal(w.format(t=tt, p=pp)) for w in GMAIL_OWNER for tt, pp in ((t, p), (t.replace("_", " "), p), (t, h))))
        cands.append({"fmt": {}, "expected": {"value": str(len(ds))}, "gold": [d["dsid"] for d in ds], "wordings": ws,
                      "pieces": [p, t, str(len(ds))], "extra": {"filters": [["mailbox_owner", p], ["thread_type", t]]}})
    accounts: dict[str, list[dict]] = defaultdict(list)
    shown: dict[str, Counter] = defaultdict(Counter)
    for d in g:
        a = d["raw"].get("related_account")
        if isinstance(a, str) and not _none(a) and _squash(a):
            accounts[_squash(a)].append(d)
            shown[_squash(a)][a.strip()] += 1
    inner = _nested({a for c in shown.values() for a in c})
    listed = _listed(g, "related_account")
    for sq, ds in sorted(accounts.items()):
        a = shown[sq].most_common(1)[0][0]
        if not LO <= len(ds) <= HI:
            _note(aside, "count outside 2-15")
        elif sq.startswith("acme"):
            _note(aside, "generic account name")
        elif sq in inner:
            _note(aside, "named inside another")
        elif sq in listed:
            _note(aside, "value also in a list")
        elif any(_says(sq, d["title"]) for d in g if d not in ds):
            _note(aside, "another thread's subject names it")
        elif why := next((r for d in ds if (r := _not_account(d["raw"], a))), ""):
            _note(aside, why)
        else:
            cands.append({"fmt": {"a": a}, "expected": {"value": str(len(ds))}, "gold": [d["dsid"] for d in ds],
                          "wordings": GMAIL_ACCOUNT, "pieces": [a, str(len(ds))], "extra": {"filters": [["related_account", a]]}})
    return _emit("count_gmail", cands, rng, cap, aside)


# ------------------------------------------------------------------ history
def _history_dates(raw: dict[str, Any]) -> list[str]:
    txt = json.dumps({f: raw.get(f) for f in HISTORY_FIELDS if raw.get(f)}, ensure_ascii=False, default=str)
    return sorted(d for d in set(re.findall(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)", txt)) if _valid(d))


def created_on(hay: Haystack, rng: random.Random, cap: int | None = None, aside: Counter | None = None) -> list[dict[str, Any]]:
    """When a Linear issue, Jira ticket, HubSpot account or pull request was created (created_at). Set aside when a dated
    history entry falls before it."""
    cands = []
    for src in CREATED:
        for d in hay.of(src):
            fmt, name = hay.address(d)
            exp, why = _expected(d["raw"].get("created_at"), "date") if fmt else (None, name)
            if exp is not None and (hist := _history_dates(d["raw"])) and hist[0] < exp["date"]:
                exp, why = None, "history dated before it"
            if exp is None:
                _note(aside, why)
                continue
            cands.append({"fmt": fmt, "expected": exp, "gold": [d["dsid"]], "pieces": [name, exp["date"]], "wordings": CREATED[src],
                          "field": "created_at"})
    return _emit("created_on", cands, rng, cap, aside)


def last_updated(hay: Haystack, rng: random.Random, cap: int | None = None, aside: Counter | None = None) -> list[dict[str, Any]]:
    """When a Linear issue, Jira ticket or HubSpot account was last updated (updated_at). Set aside when a dated history
    entry falls after it, or it falls before created_at."""
    cands = []
    for src in UPDATED:
        for d in hay.of(src):
            fmt, name = hay.address(d)
            exp, why = _expected(d["raw"].get("updated_at"), "date") if fmt else (None, name)
            if exp is not None:
                made = _expected(d["raw"].get("created_at"), "date")[0]
                if (hist := _history_dates(d["raw"])) and hist[-1] > exp["date"]:
                    exp, why = None, "history dated after it"
                elif made and made["date"] > exp["date"]:
                    exp, why = None, "updated before created"
            if exp is None:
                _note(aside, why)
                continue
            cands.append({"fmt": fmt, "expected": exp, "gold": [d["dsid"]], "pieces": [name, exp["date"]], "wordings": UPDATED[src],
                          "field": "updated_at"})
    return _emit("last_updated", cands, rng, cap, aside)


def days_to_merge(hay: Haystack, rng: random.Random, cap: int | None = None, aside: Counter | None = None) -> list[dict[str, Any]]:
    """How many days a merged pull request took from created_at to merged_at, both read as dates."""
    cands = []
    for d in hay.of("github"):
        fmt, name = hay.address(d)
        if fmt is None:
            _note(aside, name)
            continue
        if str(d["raw"].get("state") or "").strip().lower() != "merged":
            _note(aside, "not merged")
            continue
        a, b = _expected(d["raw"].get("created_at"), "date")[0], _expected(d["raw"].get("merged_at"), "date")[0]
        if not a or not b:
            _note(aside, "no value")
            continue
        n = (date.fromisoformat(b["date"]) - date.fromisoformat(a["date"])).days
        if n < 0:
            _note(aside, "merged before created")
            continue
        cands.append({"fmt": fmt, "expected": {"value": str(n)}, "gold": [d["dsid"]], "pieces": [name, a["date"], b["date"]],
                      "wordings": DAYS_WORDINGS})
    return _emit("pr_days_to_merge", cands, rng, cap, aside)


def moved_to_status(hay: Haystack, rng: random.Random, cap: int | None = None, aside: Counter | None = None) -> list[dict[str, Any]]:
    """The date a Linear issue or Jira ticket moved to its present status S: the one date of the date-led entries (comments,
    updates, activity, timeline) saying 'moved (the ticket) to S', 'changed status to S' or 'marking (this ticket) as S'.
    Set aside when another noun is moved or marked as S ('marking pipeline as Done'), or two dates say so."""
    cands = []
    for src in ("linear", "jira"):
        for d in hay.of(src):
            fmt, name = hay.address(d)
            st = str(d["raw"].get("status") or "").strip()
            if fmt is None or not st:
                _note(aside, name if fmt is None else "no value")
                continue
            strict, undated, loose = set(), 0, 0
            for f in MOVE_FIELDS:
                for it in _items(d["raw"].get(f)) or []:
                    m = DATE_LED.match(it)
                    if re.search(MOVE + re.escape(st) + r"\b", it, re.I):
                        if m and _valid(m.group(1)):
                            strict.add(m.group(1))
                        else:
                            undated += 1
                    elif re.search(MOVE_LOOSE + re.escape(st) + r"\b", it, re.I):
                        loose += 1
            if undated:
                _note(aside, "move entry not dated")
            elif loose:
                _note(aside, "another noun moved to the status")
            elif not strict:
                _note(aside, "no move entry")
            elif len(strict) > 1:
                _note(aside, "moved on two dates")
            else:
                when = next(iter(strict))
                cands.append({"fmt": {**fmt, "s": st, "sys": SYSTEM[src]}, "expected": {"date": when}, "gold": [d["dsid"]],
                              "pieces": [name, st, when], "wordings": MOVED_WORDINGS})
    return _emit("moved_to_status", cands, rng, cap, aside)


def _comments(raw: dict[str, Any]) -> tuple[list[tuple[str, str, str, str]] | None, str]:
    """A ticket's comments as (date, time, author, parenthesis), each 'YYYY-MM-DD[ HH:MM][ -] Name[ (role)]: text'; None and
    why when there are none or one is written otherwise."""
    its = _items(raw.get("comments"))
    if its is None:
        return None, "comment unparseable"
    if not its:
        return None, "no value"
    out = []
    for x in its:
        m = ENTRY.match(x)
        if not m or not _valid(m.group(1)):
            return None, "comment unparseable"
        out.append((m.group(1), m.group(2) or "", m.group(3), m.group(4) or ""))
    return out, ""


def _tied(a: tuple[str, str], b: tuple[str, str]) -> bool:
    """Two entries whose order is not known: the same date, and the same time or a time missing."""
    return a[0] == b[0] and (a[1] == b[1] or not a[1] or not b[1])


def comment_questions(kind: str, hay: Haystack, rng: random.Random, cap: int | None = None,
                      aside: Counter | None = None) -> list[dict[str, Any]]:
    """Who left the first comment on a Linear issue or Jira ticket (first_commenter), or the date of its latest comment
    (last_comment_date), every comment dated and signed. Set aside on a tie for the first comment, and when its author is not
    a full name or is a role whose parenthesis names the person ('Product Review (Liam Chen)')."""
    cands = []
    for src in ("linear", "jira"):
        for d in hay.of(src):
            fmt, name = hay.address(d)
            cs, why = _comments(d["raw"]) if fmt else (None, name)
            if cs is None:
                _note(aside, why)
                continue
            order = sorted(cs)
            if kind == "last_comment_date":
                exp: dict[str, Any] = {"date": order[-1][0]}
                ws = LAST_COMMENT
            else:
                first = order[0]
                if any(_tied(first[:2], c[:2]) for c in order[1:]):
                    _note(aside, "tie for the first comment")
                    continue
                if _full_name(first[3]):
                    _note(aside, "a role before the name")
                    continue
                p = _full_name(first[2])
                if p is None:
                    _note(aside, "not a person")
                    continue
                exp, ws = {"value": p}, FIRST_COMMENT
            cands.append({"fmt": {**fmt, "sys": SYSTEM[src]}, "expected": exp, "gold": [d["dsid"]],
                          "pieces": [name, exp.get("value") or exp["date"]], "wordings": ws, "field": "comments"})
    return _emit(kind, cands, rng, cap, aside)


def first_activity(hay: Haystack, rng: random.Random, cap: int | None = None, aside: Counter | None = None) -> list[dict[str, Any]]:
    """The earliest date of a HubSpot account's timeline, every entry date-led. Set aside when another activity field holds
    an earlier date."""
    cands = []
    for d in hay.of("hubspot"):
        fmt, name = hay.address(d)
        its = _items(d["raw"].get("timeline")) if fmt else None
        if fmt is None:
            _note(aside, name)
            continue
        if not its:
            _note(aside, "no value")
            continue
        ms = [DATE_LED.match(x) for x in its]
        if not all(m and _valid(m.group(1)) for m in ms):
            _note(aside, "entry not dated")
            continue
        first = min(m.group(1) for m in ms if m)
        other = [m.group(1) for f in ACTIVITY_FIELDS for x in _items(d["raw"].get(f)) or [] if (m := DATE_LED.match(x))]
        if any(o < first for o in other):
            _note(aside, "earlier date in another activity field")
            continue
        cands.append({"fmt": fmt, "expected": {"date": first}, "gold": [d["dsid"]], "pieces": [name, first], "wordings": FIRST_ACTIVITY,
                      "field": "timeline"})
    return _emit("hubspot_first_activity", cands, rng, cap, aside)


# ------------------------------------------------------------------ email and chat
def messages(raw: dict[str, Any]) -> list[dict[str, str]] | None:
    """A thread's messages as their headers (From, To, Cc, Date, Subject): a list of message texts, or one text split before
    each 'From:' line; a literal backslash-n is a line break. None when a message is not text."""
    m = raw.get("messages")
    if isinstance(m, str):
        m = re.split(r"(?=^From:)", m.replace("\\n", "\n"), flags=re.M)
    if not isinstance(m, list):
        return []
    out = []
    for x in m:
        if not isinstance(x, str):
            return None
        if not x.strip():
            continue
        x = x.replace("\\n", "\n")
        h = {}
        for name in ("From", "To", "Cc", "Date", "Subject"):
            mm = re.search(rf"(?im)^{name}:[ \t]*(.*)$", x)
            if mm:
                h[name] = mm.group(1).strip()
        out.append(h)
    return out


def _not_account(raw: dict[str, Any], a: str) -> str:
    """Why a thread's related_account ``a`` is no customer account to ask about, or '': the thread is a hiring thread (its
    account field names candidates, recruiters and employers), the value labels a candidate, an internal matter or a team
    (``LABEL``), it holds several names ('NimbusCloud; Stratus; Aurora Analytics', 'Acme Cloud / EdgeOps'), or it carries a
    note in brackets ('Acme AI (candidate source)'). Nobody would answer with the label or the note, and the scorer wants the
    whole value."""
    if str(raw.get("thread_type") or "").strip().lower() in HIRING:
        return "a hiring thread"
    if LABEL.search(a):
        return "a label, not an account"
    if re.search(r";|\s/\s", a):
        return "several names in the value"
    if re.search(r"[()\[\]]", a):
        return "a note in the value"
    return ""


def _addressed(field: str | None) -> list[str]:
    return [p.strip() for p in re.split(r"[,;](?![^<]*>)", field or "") if p.strip()]


def _named(entry: str) -> str | None:
    """The person of an address written with a display name ('Rachel Lim <rachel.lim@x.com>'), or None (a bare address, a
    group, a bot)."""
    m = re.fullmatch(r"\s*\"?([^\"<>]+?)\"?\s*<[^<>@\s]+@[^<>\s]+>\s*", entry)
    return _full_name(m.group(1)) if m else None


class _Thread:
    """What a thread's raw fields say, checked against each other."""

    def __init__(self, raw: dict[str, Any]):
        self.msgs = messages(raw)
        self.first_at = _when(raw.get("first_email_at"))
        self.last_at = _when(raw.get("last_email_at"))
        dates = [_when(m.get("Date")) for m in self.msgs or []]
        self.dated = bool(self.msgs) and all(t is not None and t.tzinfo is not None for t in dates)
        self.dates = dates if self.dated else []

    def first_ok(self) -> str:
        """'' when the first message is the earliest, alone at its time, and is first_email_at; else why not."""
        if self.msgs is None:
            return "messages unparseable"
        if not self.msgs:
            return "no messages"
        if not self.dated:
            return "message not dated"
        if self.first_at is None or self.first_at.tzinfo is None or abs((self.dates[0] - self.first_at).total_seconds()) >= 60:
            return "first message is not first_email_at"
        if any(t <= self.dates[0] for t in self.dates[1:]):
            return "first message is not the earliest"
        return ""


def email_questions(kind: str, hay: Haystack, rng: random.Random, cap: int | None = None,
                    aside: Counter | None = None) -> list[dict[str, Any]]:
    """One fact of an email thread named by its subject: the first email's sender, recipients or Cc (every entry a person
    with a display name), the thread's start date (first_email_at, which must be the earliest message's and read the same in
    UTC), its message count (equal to the messages written), its attachments (one to ten files) or its account (not written
    inside another account's name, and a customer account by ``_not_account``: not on a hiring thread, not a label of a
    candidate, an internal matter or a team, one name, no note in brackets)."""
    cands = []
    accounts = [a.strip() for d in hay.of("gmail") if isinstance(a := d["raw"].get("related_account"), str) and not _none(a)]
    inner = _nested(set(accounts), outer=False)
    for d in hay.of("gmail"):
        fmt, name = hay.address(d)
        if fmt is None:
            _note(aside, name)
            continue
        raw, th = d["raw"], _Thread(d["raw"])
        exp: dict[str, Any] | None = None
        why = ""
        if kind in ("email_sender", "email_to", "email_cc"):
            why = th.first_ok()
            if not why:
                h = th.msgs[0]
                if kind == "email_sender":
                    p = _named(h.get("From", ""))
                    exp, why = ({"value": p}, "") if p else (None, "sender not a named person")
                else:
                    entries = _addressed(h.get("To" if kind == "email_to" else "Cc"))
                    ps = [_named(x) for x in entries]
                    if not entries:
                        why = "no value"
                    elif not all(ps):
                        why = "an entry not a named person"
                    elif len(set(ps)) > B.LIST_MAX:
                        why = "too many"
                    else:
                        exp = {"names": list(dict.fromkeys(ps))}
        elif kind == "email_date":
            day = _day(th.first_at)
            if th.first_at is None:
                why = "no value"
            elif day is None:
                why = "several values"
            elif not th.dated:
                why = "message not dated" if th.msgs else "no messages"
            elif abs((min(th.dates) - th.first_at).total_seconds()) >= 60:
                why = "first_email_at is not the earliest message"
            elif th.last_at is not None and th.last_at.tzinfo is not None and th.last_at < th.first_at:
                why = "last before first"
            else:
                exp = {"date": day}
        elif kind == "email_count":
            try:
                mc = int(str(raw.get("message_count")).strip())
            except ValueError:
                mc = None
            if mc is None or not th.msgs:
                why = "no value" if mc is None else "no messages"
            elif mc != len(th.msgs):
                why = "count is not the messages written"
            else:
                exp = {"value": str(mc)}
        elif kind == "email_attachments":
            att = raw.get("attachments")
            has = str(raw.get("has_attachments", "")).strip().lower()
            if not isinstance(att, list) or not att:
                why = "no value"
            elif not all(isinstance(a, str) and a.strip() for a in att) or len(att) > B.LIST_MAX:
                why = "unusable list"
            elif has in ("false", "no", "0"):
                why = "has_attachments says none"
            elif len({_file(a) for a in att}) < len(att):
                why = "a file listed twice"
            else:
                exp = {"files": [a.strip() for a in att]}
        else:  # email_account
            a = raw.get("related_account")
            if not isinstance(a, str) or _none(a):
                why = "no value" if not isinstance(a, list) else "several values"
            elif _squash(a) in inner:
                why = "named inside another"
            elif not (why := _not_account(raw, a)):
                exp = {"value": a.strip()}
        if exp is None:
            _note(aside, why)
            continue
        cands.append({"fmt": fmt, "expected": exp, "gold": [d["dsid"]], "pieces": [name, *_answers(exp)],
                      "wordings": {"email_sender": SENDER, "email_date": STARTED, "email_to": TO, "email_cc": CC, "email_count": MESSAGES,
                                   "email_attachments": ATTACHED, "email_account": ACCOUNT}[kind]})
    return _emit(kind, cands, rng, cap, aside)


def _first_line(raw: dict[str, Any]) -> tuple[str, str] | None:
    """A Slack thread's first speaker and the text of the first message, or None."""
    body = raw.get("messages") or raw.get("text") or raw.get("thread") or raw.get("transcript") or raw.get("content") or ""
    if isinstance(body, list):
        body = "\n".join(map(str, body))
    lines = [x for x in str(body).replace("\\n", "\n").split("\n") if x.strip()]
    m = SPEAKER.match(lines[0]) if lines else None
    return (m.group(1).strip(), m.group(2)) if m else None


def slack_questions(kind: str, hay: Haystack, rng: random.Random, cap: int | None = None,
                    aside: Counter | None = None) -> list[dict[str, Any]]:
    """A Slack thread named by a quote of its first message's first ten words, found in no other document's text: its channel
    (slack_channel) or, when the first speaker is a 'First Last' name, who started it (slack_starter)."""
    cands = []
    for d in hay.of("slack"):
        got = hay.slack_quotes[d["dsid"]]
        if isinstance(got, str):
            _note(aside, got)
            continue
        quote, spk = got
        if kind == "slack_channel":
            ch = str(d["raw"].get("channel") or "").strip().lstrip("#")
            exp, why = ({"value": ch}, "") if ch and len(ch) <= VALUE_MAX else (None, "no value")
        else:
            p = _full_name(spk) if re.fullmatch(r"[A-Z][\w'-]+ [A-Z][\w'-]+", spk) else None
            exp, why = ({"value": p}, "") if p else (None, "starter not a full name")
        if exp is None:
            _note(aside, why)
            continue
        cands.append({"fmt": {"q": quote}, "expected": exp, "gold": [d["dsid"]], "pieces": [quote, exp["value"]],
                      "wordings": CHANNEL if kind == "slack_channel" else STARTER})
    return _emit(kind, cands, rng, cap, aside)


# ------------------------------------------------------------------ two documents
def _other_value(d: dict[str, Any], field: str) -> str | None:
    v = d["raw"].get(field)
    return None if _none(v) or isinstance(v, list | dict) else (_person(v) if field == "creator" else str(v).strip())


def link_questions(kind: str, hay: Haystack, rng: random.Random, cap: int | None = None,
                   aside: Counter | None = None) -> list[dict[str, Any]]:
    """The project, creator or team of the Linear issue a pull request links (the planted pairs of the draw:
    ``factbank_multi.units``). Set aside by ``factbank_5k.why_unclear``, when the value is written inside another value of
    the field, and when another ticket the pull request references holds another value there (the bank follows links)."""
    field, typ, wordings = LINK[kind]
    by_id = {d["dsid"]: d for d in hay.docs}
    lin = hay.of("linear")
    inner = _nested({e["value"] for d in lin if (e := _expected(d["raw"].get(field), typ)[0]) and "value" in e}, outer=False)
    trackers = {k: d for d in hay.docs if d["source"] in ("linear", "jira") and (k := _key(d))}
    cands = []
    for u in units(hay.docs):
        if u["kind"] != "pr":
            continue
        pr, iss = by_id[u["pr"]], by_id[u["issue"]]
        n, key = str(pr["raw"]["pr_number"]), _key(iss) or ""
        exp, why = _expected(iss["raw"].get(field), typ)
        if exp is not None and _squash(exp["value"]) in inner:
            exp, why = None, "named inside another"
        if exp is not None and any(k != key and k in trackers and _other_value(trackers[k], field) not in (None, exp["value"])
                                   for k in _refs(pr)):
            exp, why = None, "linked"
        if exp is not None:
            q = {"kind": kind, "question": wordings[0].format(n=n), "expected": exp, "pieces": [key, exp["value"]], "gold_docs": u["docs"]}
            why = why_unclear(q, hay.docs) or ""
            exp = None if why else exp
        if exp is None:
            _note(aside, why)
            continue
        cands.append({"fmt": {"n": n}, "expected": exp, "gold": u["docs"], "pieces": [key, exp["value"]], "wordings": wordings,
                      "field": field})
    return _emit(kind, cands, rng, cap, aside)


def _assigned(hay: Haystack, source: str, field: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for d in hay.of(source):
        if p := _person(d["raw"].get(field)):
            out[p].append(d)
    return out


def _join_target(hay: Haystack, p: str, source: str, field: str, by: dict[str, list[dict]]) -> tuple[list[dict] | None, str]:
    """The documents of ``source`` whose ``field`` is the person ``p`` (one to ``JOIN_MAX``), or None and why not: none, too
    many, or the name written in that field of another document in another form ('Dr. Priya Nair', 'Priya Nair, Ava Lee')."""
    ds = by.get(p, [])
    if not ds:
        return None, "no documents to join"
    if len(ds) > JOIN_MAX:
        return None, "too many"
    others = [d for d in hay.of(source) if d not in ds and _in(p, json.dumps(d["raw"].get(field), ensure_ascii=False, default=str))]
    if others:
        return None, "the name in another form"
    return ds, ""


def join_questions(kind: str, hay: Haystack, rng: random.Random, cap: int | None = None,
                   aside: Counter | None = None) -> list[dict[str, Any]]:
    """The keys of the Linear issues assigned to the same full name as a pull request's author (author_issues) or a Jira
    ticket's reporter (reporter_issues): one to ``JOIN_MAX`` issues, every key on one document."""
    src, field, wordings = JOIN[kind]
    by = _assigned(hay, "linear", "assignee")
    cands = []
    for d in hay.of(src):
        fmt, name = hay.address(d)
        p = _full_name(d["raw"].get(field)) if fmt else None
        if fmt is None or p is None:
            _note(aside, name if fmt is None else "not a person")
            continue
        ds, why = _join_target(hay, p, "linear", "assignee", by)
        if ds is not None:
            keys = sorted(_key(x) or "" for x in ds)
            if any(not k or not KEY.fullmatch(k) or hay.names["keys"][k] != 1 for k in keys):
                ds, why = None, "named twice"
        if ds is None:
            _note(aside, why)
            continue
        q = {"kind": kind, "question": wordings[0].format(**fmt), "pieces": [p, *keys], "expected": {"ids": keys, "id_kind": "key"}}
        if why := why_unclear(q, hay.docs):
            _note(aside, why)
            continue
        cands.append({"fmt": fmt, "expected": {"ids": keys, "id_kind": "key"}, "gold": [d["dsid"], *(x["dsid"] for x in ds)],
                      "pieces": [p, *keys], "wordings": wordings, "field": field})
    return _emit(kind, cands, rng, cap, aside)


def owner_accounts(hay: Haystack, rng: random.Random, cap: int | None = None, aside: Counter | None = None) -> list[dict[str, Any]]:
    """The HubSpot accounts owned by the same full name as a meeting's Redwood owner: how many (one to ``JOIN_MAX``), or,
    when there is one, which (drawn at random), its title on one document and inside no other account's."""
    by = _assigned(hay, "hubspot", "owner")
    titles = [str(d["title"]).strip() for d in hay.of("hubspot")]
    inner = _nested(set(titles), outer=False)
    cands = []
    for d in hay.of("fireflies"):
        fmt, name = hay.address(d)
        p = _full_name(d["raw"].get("redwood_owner")) if fmt else None
        if fmt is None or p is None:
            _note(aside, name if fmt is None else "not a person")
            continue
        ds, why = _join_target(hay, p, "hubspot", "owner", by)
        if ds is None:
            _note(aside, why)
            continue
        accts = sorted(str(x["title"]).strip() for x in ds)
        one = accts[0]
        if len(ds) == 1 and rng.random() < 0.5:
            if hay.names["titles"][_norm(one)] != 1 or _squash(one) in inner:
                _note(aside, "named twice" if hay.names["titles"][_norm(one)] != 1 else "named inside another")
                continue
            cands.append({"fmt": fmt, "expected": {"value": one}, "gold": [d["dsid"], ds[0]["dsid"]], "pieces": [p, one],
                          "wordings": OWNER_NAME, "field": "name"})
        else:
            cands.append({"fmt": fmt, "expected": {"value": str(len(ds))}, "gold": [d["dsid"], *(x["dsid"] for x in ds)],
                          "pieces": [p, *accts], "wordings": OWNER_COUNT, "field": "count"})
    return _emit("owner_accounts", cands, rng, cap, aside)


# ------------------------------------------------------------------ field absent
def _known_accounts(hay: Haystack) -> re.Pattern | None:
    """Every account or customer name the haystack writes in an account field (four letters or more), as one pattern; a
    label of a candidate, an internal matter or a team (``LABEL``: 'internal', 'Candidate: Alex Romero') names no account."""
    names: set[str] = set()
    for d in hay.docs:
        for f in ("related_account", "customer_company", "company_name"):
            v = d["raw"].get(f)
            if (isinstance(v, str) and not _none(v) and len(_squash(v)) >= 4 and not v.lower().startswith("redwood")
                    and not LABEL.search(v)):
                names.add(_norm(v))
    if not names:
        return None
    return re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r")(?![\w-])")


def _absent(src: str, field: str, v: Any) -> bool:
    """Whether a field_absent field is empty on a document (``_none``): missing, null, empty, 'TBD', 'N/A', 'unassigned' and
    the like, and 'none' except where it is a level of the field's scale (``NONE_LEVEL``: no customer impact)."""
    return _none(v) and not ((src, field) in NONE_LEVEL and isinstance(v, str) and v.strip().lower() == "none")


def field_absent(hay: Haystack, rng: random.Random, cap: int | None = None, aside: Counter | None = None) -> list[dict[str, Any]]:
    """A field that most documents of a system hold (``USUAL``) but that is empty, missing, TBD or N/A on the named one
    (``_absent``: "none" is a value where the field's scale has that level), and that the document's other fields never
    mention; for an email thread with no account, no account name written in the thread either. Expected: not found."""
    cands = []
    accounts = None
    for (src, field), (mention, wordings) in ABSENT.items():
        ds = hay.of(src)
        if not ds:
            continue
        share = sum(1 for d in ds if not _absent(src, field, d["raw"].get(field))) / len(ds)
        for d in ds:
            v = d["raw"].get(field, "<absent>")
            if not _absent(src, field, d["raw"].get(field)):
                if _none(d["raw"].get(field)):
                    _note(aside, "'none' is a level of the field")
                continue
            if share <= USUAL:
                _note(aside, "field usually empty")
                continue
            fmt, name = hay.address(d)
            if fmt is None:
                _note(aside, name)
                continue
            rest = json.dumps({k: x for k, x in d["raw"].items() if k != field}, ensure_ascii=False, default=str)
            if re.search(mention, rest, re.I):
                _note(aside, "another field mentions it")
                continue
            if src == "gmail":
                accounts = accounts if accounts is not None else _known_accounts(hay)
                if accounts is not None and accounts.search(_norm(str(d["title"]) + " " + rest)):
                    _note(aside, "the thread names an account")
                    continue
            cands.append({"fmt": fmt, "expected": {"not_found": True}, "gold": [d["dsid"]], "pieces": [name], "wordings": wordings,
                          "field": field, "extra": {"absent_value": "<absent>" if v == "<absent>" else str(v)[:20]}})
    return _emit("field_absent", cands, rng, cap, aside)


# ------------------------------------------------------------------ embedded question words
def embedded_questions(base: str, hay: Haystack, rng: random.Random, cap: int | None = None,
                       aside: Counter | None = None) -> list[dict[str, Any]]:
    """``brain_questions.field_questions`` for one FIELDS kind, every candidate kept with the same expected answer and pieces,
    reworded after a verb of knowing or telling (``EMBEDDED``)."""
    src = FIELDS[base][0]
    ph = PLACEHOLDER[ADDRESS[src]]
    cands = [{"fmt": {ph: q["pieces"][0]}, "expected": q["expected"], "gold": q["gold_docs"], "pieces": q["pieces"],
              "wordings": EMBEDDED[base], "field": q.get("field")}
             for q in B.field_questions(base, hay.docs, random.Random(0), None, aside)]
    return _emit(f"embedded_{base}", cands, rng, cap, aside)


GENERATORS: dict[str, Callable[..., list[dict[str, Any]]]] = {
    **{k: partial(count_questions, k) for k in CATALOGUE if k.startswith(("count1_", "count2_")) or k == "filter_list"},
    "count_gmail": gmail_counts, "created_on": created_on, "last_updated": last_updated, "pr_days_to_merge": days_to_merge,
    "moved_to_status": moved_to_status, "first_commenter": partial(comment_questions, "first_commenter"),
    "last_comment_date": partial(comment_questions, "last_comment_date"), "hubspot_first_activity": first_activity,
    **{k: partial(email_questions, k) for k in ("email_sender", "email_date", "email_to", "email_cc", "email_count", "email_attachments",
                                                "email_account")},
    **{k: partial(slack_questions, k) for k in ("slack_channel", "slack_starter")},
    **{k: partial(link_questions, k) for k in LINK}, **{k: partial(join_questions, k) for k in JOIN}, "owner_accounts": owner_accounts,
    "field_absent": field_absent, **{f"embedded_{k}": partial(embedded_questions, k) for k in EMBEDDED},
}


# ------------------------------------------------------------------ every question, and a draw
def generate(docs: list[dict[str, Any]], seed: int = SEED, kinds: Iterable[str] | None = None, cap: int | None = None
             ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Every question of the new kinds (all by default) the documents allow, at most ``cap`` per kind, and a report as
    ``brain_questions.generate`` gives it: questions per kind ("by_kind") and what was set aside, by kind and reason
    ("aside")."""
    want = set(kinds) if kinds is not None else set(CATALOGUE)
    unknown = want - set(CATALOGUE)
    if unknown:
        raise ValueError(f"unknown kind(s) {sorted(unknown)}")
    hay = Haystack(docs)
    out: list[dict[str, Any]] = []
    aside: dict[str, Counter] = defaultdict(Counter)
    for k in sorted(want):
        out += GENERATORS[k](hay, random.Random(f"{seed}/{k}"), cap, aside=aside[k])
    by_kind = Counter(q["kind"] for q in out)
    return out, {"by_kind": {k: by_kind[k] for k in CATALOGUE if k in want},
                 "aside": {k: dict(sorted(v.items())) for k, v in sorted(aside.items()) if v}}


def resolve(key: str) -> set[str]:
    """The kinds a mix key names: a kind, a group or a family, of the new catalogue and of ``brain_questions``'s."""
    out = {key} if key in CATALOGUE else {k.name for k in CATALOGUE.values() if key in (k.group, k.family)}
    try:
        out |= B.resolve(key)
    except ValueError:
        pass
    if not out:
        raise ValueError(f"{key!r} is not a kind, group or family")
    return out


def quotas(mix: dict[str, int], available: Counter, seed: int = SEED) -> dict[str, int]:
    """``brain_questions.quotas`` over both catalogues."""
    quota: Counter = Counter()
    for key, n in mix.items():
        ks = sorted(k for k in resolve(key) if available[k] > quota[k])
        random.Random(f"{seed}/{key}").shuffle(ks)
        while n > 0 and ks:
            for k in list(ks):
                if n == 0:
                    break
                quota[k] += 1
                n -= 1
                if quota[k] >= available[k]:
                    ks.remove(k)
    return dict(quota)


def draw_questions(docs: list[dict[str, Any]], seed: int = SEED, mix: dict[str, int] | None = None,
                   prose: list[dict[str, Any]] | None = None, multi_wordings: dict | None = None) -> list[dict[str, Any]]:
    """A seeded sample in a mix of {kind, group or family: number} (``DEFAULT_MIX``), picked as ``brain_questions.pick``
    picks; a key may name the old kinds too ('multi' is both catalogues' multi-document kinds), whose questions come from
    ``brain_questions.generate`` (prose from ``prose``)."""
    mix = dict(DEFAULT_MIX if mix is None else mix)
    wanted = set().union(*(resolve(k) for k in mix)) if mix else set()
    new = wanted & set(CATALOGUE)
    pool = generate(docs, seed, kinds=new)[0] if new else []
    old = wanted - new - {"prose", "metadata"}
    if old:
        pool += B.generate(docs, seed, kinds=old, multi_wordings=multi_wordings)[0]
    if "prose" in wanted:
        pool += [q for q in prose or [] if B.checkable(q)]
    return B.pick(pool, docs, quotas(mix, Counter(q["kind"] for q in pool), seed), seed)


# ------------------------------------------------------------------ scoring
NUMBER_WORDS = {w: i for i, w in enumerate(("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
                                            "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
                                            "eighteen", "nineteen", "twenty"))}
NUMBER_RE = re.compile(r"(?<![\w.\-/#:])(\d+)(?![\w\-/:%]|[.,]\d)|\b(" + "|".join(NUMBER_WORDS) + r")\b", re.I)


def count_hit(n: int, answer: str) -> float:
    """1 if the first number in the answer's first line (``final_answer``) is n, else 0. A number is a figure standing alone
    (not part of a key, a date, a time, a cycle such as 2026-W10 or a pull request number) or a word from zero to twenty."""
    lines = final_answer(answer or "").strip().splitlines()
    m = NUMBER_RE.search(lines[0]) if lines else None
    if m is None:
        return 0.0
    got = int(m.group(1)) if m.group(1) else NUMBER_WORDS[m.group(2).lower()]
    return float(got == n)


def _file(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def files_f1(files: list[str], answer: str) -> float:
    """F1 of the file names in the answer line: a file is found when its name (letters and digits) is written there; a part
    of the line between commas, semicolons or line breaks is right when it holds an expected file."""
    want = {f for f in (_file(x) for x in files) if f}
    line = final_answer(answer or "")
    parts = [p for p in (_file(x) for x in re.split(r"[,;\n]", line)) if p]
    if not want or not parts:
        return 0.0

    def holds(part: str, f: str) -> bool:
        return bool(re.search(r"(?<![a-z0-9])" + re.escape(f) + r"(?![a-z0-9])", part))

    p = sum(1 for x in parts if any(holds(x, f) for f in want)) / len(parts)
    r = sum(1 for f in want if holds(_file(line), f)) / len(want)
    return round(2 * p * r / (p + r), 3) if p and r else 0.0


def score(q: dict[str, Any], row: dict[str, Any] | str) -> float | None:
    """One answer's score in [0, 1]. ``row`` is the brain's row ({"answer", "route"?}) or the answer itself. A question of an
    old kind is scored by ``brain_questions.score``.

    - unanswerable: 1 if the answer says not found, else 0; for every other kind an answer of not found scores 0;
    - counts, days to merge and message counts: ``count_hit``;
    - embedded: as the field kind it rewords;
    - file lists: ``files_f1``; person lists: ``brain_questions.name_f1``;
    - multi: ``factbank_multi.own_score``;
    - keys and dates: ``factbank_test.direct`` (a timestamp read as its date); values: ``brain_questions.value_hit``."""
    kind = q.get("kind")
    if kind not in CATALOGUE:
        return B.score(q, row)
    if kind.startswith("embedded_"):
        return B.score({**q, "kind": kind[len("embedded_"):], "family": "single"}, row)
    answer, route = (row, None) if isinstance(row, str) else (str(row.get("answer") or ""), row.get("route"))
    answer = re.sub(r"\b(\d{4}-\d{2}-\d{2})T(?=\d)", r"\1 ", answer)
    nf = B.says_not_found(answer, route)
    fam = family(q)
    if fam == "unanswerable":
        return float(nf)
    if nf:
        return 0.0
    e = q.get("expected") or {}
    if kind in COUNT_KINDS:
        return count_hit(int(e["value"]), answer)
    if "files" in e:
        return files_f1(e["files"], answer)
    if "names" in e:
        return B.name_f1(e["names"], answer)
    if fam == "multi":
        return own_score(q, answer)
    if "value" in e:
        return B.value_hit(e, answer)
    return direct(q, answer)


# ------------------------------------------------------------------ command line
def load(path: Path) -> list[dict[str, Any]]:
    """Documents ({dsid, source, title, raw}) from a work folder (``brain_test.load_docs``), a JSON list or a pickle of one."""
    if path.is_dir():
        from cie.eval.brain_test import load_docs

        return load_docs(path)
    if path.suffix == ".pkl":
        with path.open("rb") as fh:
            return pickle.load(fh)  # the caller's own saved documents
    return json.loads(path.read_text())


def main(argv: list[str] | None = None) -> dict[str, Any]:
    ap = argparse.ArgumentParser(prog="python -m cie.eval.brain2_questions")
    ap.add_argument("cmd", choices=["generate", "kinds"])
    ap.add_argument("--work", type=Path, help="a work folder (haystack.json, index.json)")
    ap.add_argument("--docs", type=Path, help="the documents as a JSON list or a pickle")
    ap.add_argument("--out", type=Path, help="questions.jsonl to write")
    ap.add_argument("--report", type=Path, help="the report (questions and set-aside reasons per kind) to write")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--kinds", nargs="*")
    ap.add_argument("--cap", type=int)
    a = ap.parse_args(argv)
    if a.cmd == "kinds":
        print(json.dumps(kinds(), indent=1))
        return {"kinds": len(CATALOGUE)}
    if (a.work is None) == (a.docs is None):
        ap.error("give --work or --docs")
    docs = load(a.work or a.docs)
    qs, rep = generate(docs, a.seed, a.kinds, a.cap)
    rep = {"documents": len(docs), "seed": a.seed, "questions": len(qs), "by_family": dict(sorted(Counter(map(family, qs)).items())), **rep}
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text("".join(json.dumps(q, ensure_ascii=False) + "\n" for q in qs))
    if a.report:
        a.report.write_text(json.dumps(rep, indent=1))
    print(json.dumps({k: rep[k] for k in ("documents", "questions", "by_family")}))
    return rep


if __name__ == "__main__":
    main()

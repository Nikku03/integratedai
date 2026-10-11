"""Counts, filters, history, email and chat over the fact bank (the company brain v16, ``cie.factbank.records``): the named
document, the table of counts and filters, the derived history and message facts, and the field-empty abstention, on a tiny
bank built here. Every question a function does not handle gets None, so the brain falls through to v15's routes."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cie.factbank import bank as B
from cie.factbank import records as R
from cie.factbank.engine import FactBank
from cie.ingest.sources import SourceDoc

WHEN = datetime(2026, 3, 1, tzinfo=UTC)


def _doc(dsid, source, title, meta, body="", keys=()):
    return SourceDoc(dsid=dsid, source=source, rel=f"{source}/{dsid}.json", title=title, fields=[("body", body)] if body else [],
                     meta=meta, updated=WHEN, keys=list(keys))


COMMENTS = ("- 2026-03-10 Ava Chen: Initial sketch complete.\n"
            "- 2026-03-11 09:20 - Diego Martinez (Eng): We need the timeline to tie into the rollout history.\n"
            "- 2026-03-12 Ava Chen: Consolidated feedback; moving ticket to In Review.\n"
            "- 2026-03-14 — SRE Team: Scheduled the staging canary.")
MESSAGES = ("- From: Tanya Ramos <tanya.ramos@atlashealth.ai>\nTo: Soojin Lee <soojin_lee@redwood.ai>\n"
            "Cc: Pete Lawson <p.lawson@atlashealth.ai>, marissa_cole@redwood.ai\nDate: Sun, 5 Apr 2026 09:12:00 -0700\n"
            "Subject: QuickStart POC extension\n\nHi Soojin,\nTwo options:\n- A 14-day extension\n- A usage credit\nThanks, Tanya\n"
            "- From: Soojin Lee <soojin_lee@redwood.ai>\nTo: Tanya Ramos <tanya.ramos@atlashealth.ai>\nDate: Mon, 6 Apr 2026 08:35:00 -0700\n"
            "Subject: Re: QuickStart POC extension\n\nLooping in Marissa.")
DOCS = [
    (_doc("j1", "jira", "Soft 429s during batch import", {"key": "SUP-101", "status": "In Progress", "priority": "P1", "issue_type": "Bug",
                                                          "customer_tier": "dedicated", "assignee": "Marco Nguyen"}, keys=["SUP-101"]), {}),
    (_doc("j2", "jira", "Negative invoice after consolidation", {"key": "SUP-102", "status": "Resolved", "priority": "P1",
                                                                 "issue_type": "Incident", "customer_tier": "dedicated", "assignee": "Marco Nguyen"},
          keys=["SUP-102"]), {}),
    (_doc("j3", "jira", "Webhook retries stall", {"key": "SUP-103", "status": "Triage", "priority": "P2", "issue_type": "Major Incident",
                                                  "customer_tier": "enterprise", "assignee": "Liam Chen"}, keys=["SUP-103"]), {}),
    (_doc("l1", "linear", "Traffic Inspector prototype", {"key": "DES-1", "status": "In Review", "priority": "P1", "project": "Badge Revamp",
                                                          "assignee": "Priya Nair", "creator": "Ava Chen", "cycle": "2026-W07",
                                                          "customer_impact": "high", "created_at": "2026-03-09", "updated_at": "2026-03-15",
                                                          "due_date": "2026-04-02", "release": "console-2026.03"}, COMMENTS, ["DES-1"]), {}),
    (_doc("l2", "linear", "Rotate office wifi keys", {"key": "ENG-12", "status": "Done", "priority": "P2", "project": "Badge Revamp",
                                                      "assignee": "Omar Singh", "creator": "Ava Chen", "cycle": "2026-W07", "customer_impact": "low",
                                                      "due_date": "2026-04-03", "parent_issue": "DES-1"}, keys=["ENG-12"]), {}),
    (_doc("l3", "linear", "Replace the badge printer", {"key": "ENG-13", "status": "In Progress", "priority": "P2", "project": "Lobby Refresh",
                                                        "assignee": "Omar Singh", "creator": "Liam Chen", "cycle": "2026-W08",
                                                        "customer_impact": "TBD"}, keys=["ENG-13"]), {}),
    # the customer impact written in the text, as a content field: the bank holds no fact for it
    (_doc("l4", "linear", "Rotate the lobby kiosk certificates", {"key": "ENG-14", "status": "Planned", "priority": "P1",
                                                                  "project": "Lobby Refresh", "assignee": "Priya Nair", "creator": "Liam Chen",
                                                                  "cycle": "2026-W09", "due_date": "2026-04-09"},
          "Rotate the kiosk certificates before they expire.\nlow\nSee the runbook.", ["ENG-14"]), {}),
    (_doc("h1", "hubspot", "Emeris Skyline Platform", {"stage": "procurement", "owner": "Jordan Reyes", "se_assigned": "Maya Chen",
                                                       "csm_assigned": "Oliver Park", "account_tier": "enterprise", "created_at": "2025-11-03",
                                                       "next_step": "Finalize the Dedicated SOW and commit the ramp schedule with procurement",
                                                       "blockers": ["Security review pending", "Budget approval for Q3"]},
          "- 2025-11-10 discovery call (CTO + eng lead)\n- 2025-12-05 hosted API POC kickoff"), {}),
    (_doc("h2", "hubspot", "Bluestone MLOps", {"stage": "evaluation", "owner": "Maya Chen", "se_assigned": "Jordan Reyes", "csm_assigned": "TBD",
                                               "account_tier": "enterprise"}), {}),
    (_doc("h3", "hubspot", "Cobalt Retail", {"stage": "evaluation", "owner": "Jordan Reyes", "se_assigned": "Derek Huang",
                                             "csm_assigned": "Aaliyah Gomez", "account_tier": "smb",
                                             "next_step": "Send the usage-based pricing proposal and book the security review call",
                                             "blockers": ["Legal redlines"]}), {}),
    (_doc("g1", "github", "Add retry to badge sync", {"pr_number": "4821", "author": "Maya Chen", "created_at": "2026-02-18",
                                                      "merged_at": "2026-02-24", "state": "merged", "repo": "incident-bot"}), {}),
    (_doc("m1", "gmail", "Re: QuickStart POC extension", {"thread_id": "t-1", "mailbox_owner": "hannah_schmitt", "thread_type": "sales",
                                                          "message_count": "2", "first_email_at": "2026-04-05T09:12:00-07:00",
                                                          "related_account": "Atlas Health AI", "attachments": ["usage_report.csv", "terms-v2.docx"]},
          MESSAGES), {}),
    (_doc("m2", "gmail", "Renewal pricing follow-up", {"thread_id": "t-2", "mailbox_owner": "hannah_schmitt", "thread_type": "sales",
                                                       "message_count": "1", "related_account": "Cobalt Retail"},
          "- From: Hannah Schmitt <h@redwood.ai>\nTo: Ana Ruiz <ana@cobalt.com>\nDate: Tue, 7 Apr 2026 10:00:00 -0700\n\nHello"), {}),
    (_doc("m3", "gmail", "Security questionnaire", {"thread_id": "t-3", "mailbox_owner": "ben_carter", "thread_type": "security_compliance",
                                                    "message_count": "1"}), {}),
    (_doc("f1", "fireflies", "Atlas Health pilot kickoff", {"meeting_id": "ff-1", "redwood_owner": "Jordan Kim", "call_type": "demo",
                                                            "crm_deal_id": "CRM-ATLAS-1"}), {}),
    (_doc("f2", "fireflies", "Cobalt Retail discovery call", {"meeting_id": "ff-2", "redwood_owner": "Jordan Kim", "call_type": "discovery",
                                                              "crm_deal_id": "CRM-COBALT-7"}), {}),
    (_doc("f3", "fireflies", "Bluestone security review", {"meeting_id": "ff-3", "redwood_owner": "Maya Chen", "call_type": "demo"}), {}),
    (_doc("s1", "slack", "design", {"channel": "design", "participants": ["maya", "chris"]},
          "Maya Patel: Quick sketch attached for the latency toolbar with presets and a sampling toggle\nchris: I like consolidating controls."), {}),
]


@pytest.fixture(scope="module")
def rec(tmp_path_factory):
    path = tmp_path_factory.mktemp("records") / "factbank_v2.sqlite"
    B.build(path, DOCS, text_facts=True)
    return R.Records(FactBank(path))


def test_helpers():
    assert R.value_words("prod/us-east") == "prod us east"
    assert R.value_words("Diego Martínez") != R.value_words("Diego Martinez")
    assert R.is_empty("TBD") and R.is_empty(" n/a ") and R.is_empty(None) and not R.is_empty("Oliver Park")
    assert R.addresses("Pete Lawson <p@x.ai>, marissa_cole@redwood.ai; \"Ana Ruiz\" <a@c.com>") == ["Pete Lawson", "marissa_cole@redwood.ai",
                                                                                                      "Ana Ruiz"]


@pytest.mark.parametrize("question, dsid", [
    ("When was Jira ticket SUP-102 opened?", "j2"),
    ("How many days after it was opened was PR #4821 merged?", "g1"),
    ('When was the HubSpot account "Emeris Skyline Platform" created?', "h1"),
    ('Who sent the first email in the thread "QuickStart POC extension"?', "m1"),  # a subject without its "Re:"
    ('In which Slack channel was the thread starting "Quick sketch attached for the latency toolbar with presets" posted?', "s1"),
])
def test_start_names_one_document(rec, question, dsid):
    assert rec.start(question) == f"doc:{dsid}"


@pytest.mark.parametrize("question", [
    "Which needs finishing earlier: ENG-12 or ENG-13?",  # two documents
    'Which Linear issues have the status "Planned"?',  # a quoted value, not a title, and in no text
    "How many Jira tickets have priority P1?",
])
def test_start_none(rec, question):
    assert rec.start(question) is None


@pytest.mark.parametrize("question, answer", [
    ("How many Jira tickets have priority P1?", "2"),
    ("How many Linear issues are in cycle 2026-W07?", "2"),
    ("How many Linear issues in the project Badge Revamp have status Done?", "1"),
    ("How many open Jira tickets (status not Resolved or Closed) are for dedicated-tier customers?", "1"),
    ("How many open Linear issues are assigned to Omar Singh?", "1"),  # "open" without a list: not Done or Canceled
    ("How many enterprise HubSpot accounts does Jordan Reyes own?", "1"),
    ("How many sales email threads are in hannah_schmitt's mailbox?", "2"),
    ("Count the HubSpot accounts in the evaluation stage.", "2"),
    ("Can you count the issues in Linear in cycle 2026-W07?", "2"),
    ("How many email threads relate to the account Atlas Health AI?", "1"),
    ("How many meetings recorded in Fireflies are there with call type demo and owned on the Redwood side by Jordan Kim?", "1"),
])
def test_table_counts(rec, question, answer):
    got = rec.table(question)
    assert got is not None and got["kind"] == "count" and got["answer"] == answer
    assert len(got["docs"]) == int(answer) and got["evidence"].startswith(answer)


def test_table_a_value_inside_a_longer_one_does_not_count(rec):
    got = rec.table("How many Jira tickets of type Major Incident are there?")
    assert got["answer"] == "1" and got["filters"] == ["issue_type = Major Incident"]
    assert rec.table("How many Jira tickets of type Incident are there?")["answer"] == "1"


def test_table_keys_and_people(rec):
    got = rec.table("Which Jira tickets have priority P1? Give the keys.")
    assert got["kind"] == "keys" and got["answer"] == "SUP-101, SUP-102"
    got = rec.table('Who is assigned issues in the Linear project "Badge Revamp"?')
    assert got["kind"] == "people" and set(got["answer"].split(", ")) == {"Priya Nair", "Omar Singh"} and got["field"] == "assignee"
    assert rec.table("Which HubSpot accounts are in the evaluation stage?")["answer"] == "Bluestone MLOps, Cobalt Retail"


def test_table_reads_the_words_next_to_each_value(rec):
    """Jordan Reyes and Maya Chen are both owners and solutions engineers: the words next to each name say which."""
    got = rec.table("How many HubSpot accounts are there owned by Jordan Reyes and with Maya Chen as the solutions engineer?")
    assert got["answer"] == "1" and got["docs"] == ["doc:h1"]
    got = rec.table("How many HubSpot accounts are there owned by Maya Chen and with Jordan Reyes as the solutions engineer?")
    assert got["docs"] == ["doc:h2"]


@pytest.mark.parametrize("question, answer, filters", [
    ("How many Jira tickets do not have priority P1?", "1", ["priority not P1"]),
    ("How many Jira tickets don't have priority P1?", "1", ["priority not P1"]),
    ("How many HubSpot accounts are not in the evaluation stage?", "1", ["stage not evaluation"]),
    ("How many Linear issues are not assigned to Omar Singh?", "2", ["assignee not Omar Singh"]),
    ("How many Linear issues not in cycle 2026-W07 have status In Progress?", "1", ["status = In Progress", "cycle not 2026-W07"]),
    ("How many open Jira tickets (status not Resolved or Closed) are for dedicated-tier customers?", "1",
     ["customer_tier = dedicated", "status not Resolved"]),
])
def test_table_not_negates_the_value_it_precedes(rec, question, answer, filters):
    got = rec.table(question)
    assert got is not None and got["answer"] == answer and got["filters"] == filters, got


def test_table_not_in_a_list_question(rec):
    got = rec.table("Which HubSpot accounts owned by Jordan Reyes are not in the evaluation stage?")
    assert got["kind"] == "keys" and got["answer"] == "Emeris Skyline Platform"


def test_table_words_next_to_a_value_name_its_field(rec):
    """Pointing words claimed by the nearest value: "stage" is the evaluation's, "own" is Maya Chen's."""
    got = rec.table("How many enterprise HubSpot accounts in the evaluation stage does Maya Chen own?")
    assert got["answer"] == "1" and got["docs"] == ["doc:h2"]


@pytest.mark.parametrize("question", [
    "Which Linear issue assigned to Omar Singh is due soonest? Give the key.",  # an order
    "Which Linear issues are due between 2026-04-01 and 2026-04-05? Give the issue keys.",  # a date window
    "What is the status of the Linear issue ENG-12?",  # one named document
    'List the attendees of the meeting "Emeris Skyline Platform".',
    "How many Jira tickets have priority P7?",  # a value no ticket holds
    "How many Linear tickets does Omar Singh have on their plate?",  # a word that is not a condition
    "Who owns the infra sheet tracking the GPU reservation defaults across regions?",
    "How do I rotate the office wifi keys?",
    # a field of the documents, not the documents
    "Which priority do the Jira tickets of type Bug have?",
    "What are the statuses of the Linear issues in the project Badge Revamp?",
    "Which tier are the HubSpot accounts owned by Jordan Reyes in?",
    "Which repo do the pull requests authored by Maya Chen belong to?",
    # the words next to a value name a field that does not hold it, or a field the question names is not a condition
    "How many high-priority Linear issues are in cycle 2026-W07?",  # "high" is a customer impact, not a priority
    "How many HubSpot accounts owned by Jordan Reyes have a CSM assigned?",
    "How many Jira tickets with priority P1 have an assignee?",
    "How many open HubSpot accounts are in the evaluation stage?",  # accounts are not open or closed
    "How many Jira tickets with priority P1 are not assigned?",  # "not" before no value
])
def test_table_falls_through(rec, question):
    assert rec.table(question) is None


@pytest.mark.parametrize("question, kind, answer", [
    ("When was the Linear issue DES-1 created?", "created_on", "2026-03-09"),
    ("When was DES-1 last updated?", "last_updated", "2026-03-15"),
    ("How many days after it was opened was PR #4821 merged?", "days_to_merge", "6"),
    ("Who left the first comment on the Linear issue DES-1?", "first_commenter", "Ava Chen"),
    ("When was the latest comment on the Linear issue DES-1 posted?", "latest_comment_date", "2026-03-14"),  # by a team, still dated
    ("On what date did DES-1 move to In Review?", "moved_to_status", "2026-03-12"),
    ('When was the first recorded activity with the HubSpot account "Emeris Skyline Platform"?', "first_activity", "2025-11-10"),
    ('When does the activity timeline of the HubSpot account "Emeris Skyline Platform" begin?', "first_activity", "2025-11-10"),
    ('Who sent the first email in the thread "Re: QuickStart POC extension"?', "email_sender", "Tanya Ramos"),
    ('Who was the first email in the thread "Re: QuickStart POC extension" sent to?', "email_to", "Soojin Lee"),
    ('Who was copied on the first email in "Re: QuickStart POC extension"?', "email_cc", "Pete Lawson, marissa_cole@redwood.ai"),
    ('How many messages are in the email thread "Re: QuickStart POC extension"?', "email_count", "2"),
    ('What files were attached in the email thread "Re: QuickStart POC extension"?', "email_attachments", "usage_report.csv; terms-v2.docx"),
    ('Which account is the email thread "Re: QuickStart POC extension" about?', "email_account", "Atlas Health AI"),
    ('When did the email thread "Re: QuickStart POC extension" start?', "email_date", "2026-04-05"),
    ('In which Slack channel was the thread starting "Quick sketch attached for the latency toolbar" posted?', "slack_channel", "design"),
    ('Who started the Slack thread that begins "Quick sketch attached for the latency toolbar"?', "slack_starter", "Maya Patel"),
    ('Who started the thread in the Slack channel that begins "Quick sketch attached for the latency toolbar"?', "slack_starter",
     "Maya Patel"),
    ("When did someone last comment on the Linear issue DES-1?", "latest_comment_date", "2026-03-14"),
    ("Who left the first comment on the Linear issue DES-1, and when?", "first_comment", "Ava Chen, 2026-03-10"),
    ('How many people were copied on the first email in "Re: QuickStart POC extension"?', "email_cc_count", "2"),
    ('How many recipients did the first email in "Re: QuickStart POC extension" have?', "email_to_count", "1"),
    ('How many attachments does the email thread "Re: QuickStart POC extension" have?', "email_attachment_count", "2"),
])
def test_derived(rec, question, kind, answer):
    got = rec.derived(question, rec.start(question))
    assert got is not None and got["kind"] == kind and got["answer"] == answer, got
    assert got["doc"] == rec.start(question) and got["evidence"]


def test_message_bullets_are_not_messages(rec):
    assert [m.get("From") for m in rec.messages("doc:m1")] == ["Tanya Ramos <tanya.ramos@atlashealth.ai>", "Soojin Lee <soojin_lee@redwood.ai>"]


@pytest.mark.parametrize("question", [
    "What is the status of the Linear issue DES-1?",  # a field, v15's
    "Who created the Linear issue DES-1?",  # who, not when
    "When was pull request #4821 merged?",  # the merge date is a field
    "When is the Linear issue ENG-12 due?",
    "On what date did ENG-12 move to In Review?",  # no entry says so
    "Who left the first comment on the Linear issue ENG-12?",  # no comments
    "When was the parent issue of DES-1 created?",  # another document: its own date is not the answer
    "When was the parent issue of DES-1 last updated?",
    "When was the Linear issue behind PR #4821 created?",
])
def test_derived_falls_through(rec, question):
    assert rec.derived(question, rec.start(question)) is None
    assert rec.derived(question, None) is None


@pytest.mark.parametrize("question, reason", [
    ("What is the customer impact of the Linear issue ENG-13?", 'the Linear issue ENG-13 has no customer impact (the field says "TBD")'),
    ('Who is the customer success manager assigned to the HubSpot account "Bluestone MLOps"?',
     'the HubSpot account Bluestone MLOps has no CSM assigned (the field says "TBD")'),
    ("When is the Linear issue ENG-13 due?", "the Linear issue ENG-13 has no due date"),
    ("By when does Linear issue ENG-13 need to be done?", "the Linear issue ENG-13 has no due date"),
    ('Which CRM deal is the meeting "Bluestone security review" linked to? Give the deal ID.',  # linked to the field asked for
     "the meeting Bluestone security review has no crm deal id"),
    ('Which account is the email thread "Security questionnaire" about?', "the email thread Security questionnaire has no related account"),
])
def test_absent(rec, question, reason):
    assert rec.absent(question, rec.start(question)) == reason


@pytest.mark.parametrize("question", [
    "What is the customer impact of the Linear issue DES-1?",  # held
    'Who is the customer success manager assigned to the HubSpot account "Emeris Skyline Platform"?',
    'Who is the solutions engineer assigned to the HubSpot account "Bluestone MLOps"?',  # the SE is there; the CSM is not asked
    "What is the status of the parent issue of ENG-13?",  # a link to follow
    "Who is the parent issue of ENG-13 assigned to?",
    "When is the ticket linked to ENG-13 due?",  # another document, which may hold the field
    "Who left the first comment on the Linear issue ENG-13?",  # history, not a field
    "How many Linear issues does ENG-13 block?",
    "What date is on the Linear issue ENG-13?",  # "date" alone is half of "due date": no field stands out (``MIN_ASK``)
    # a text field and a list field, which documents may write as content fields: never called missing
    'What is the next step for the HubSpot account "Bluestone MLOps"?',
    'What are the blockers on the HubSpot account "Bluestone MLOps"?',
    "What is the customer impact of the Linear issue ENG-14?",  # "low" on a line of its own in the text
])
def test_absent_falls_through(rec, question):
    assert rec.absent(question, rec.start(question)) is None


def test_absent_needs_a_usually_held_field(rec):
    """Only one Linear issue in four has a release: below ``MIN_HELD`` (0.3) it is not a usual field, and ENG-12 lacking one
    says nothing. ``min_held`` sets the share."""
    question = "Which release is the Linear issue ENG-12 in?"
    assert rec.absent(question, "doc:l2") is None
    assert R.Records(rec.b, min_held=0.25).absent(question, "doc:l2") == "the Linear issue ENG-12 has no release"
    assert R.Records(rec.b, min_held=0.9).absent("What is the customer impact of the Linear issue ENG-13?", "doc:l3") is None


def test_absent_fields(rec):
    """``askable``: usual fields with one short value per document (not the HubSpot next step, a text, or its blockers, a list);
    ``written_bare``: a field's value on a line of its own in the text."""
    assert {"csm_assigned", "se_assigned", "stage"} <= rec.askable("hubspot") and not {"next_step", "blockers"} & rec.askable("hubspot")
    assert rec.written_bare("doc:l4", "customer_impact") and not rec.written_bare("doc:l3", "customer_impact")

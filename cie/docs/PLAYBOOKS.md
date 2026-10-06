# Playbooks: company rules that decide yes, no or unknown

**Status (2026-10-06): built and tested with code checks. Not yet measured on real policies.** The test on the
benchmark's policy documents (drafted rules against a model reading the policy each time) is still to be set up and
pre-registered.

## What it does

A playbook turns a written policy (an approval matrix, a runbook) into rules that a program evaluates:

```
needs_finance: amount_usd > 250
may_pay: "manager" in approvals and (not needs_finance or "finance" in approvals) unless vendor_blocked
```

- **Three answers.** A fact that is not known is *unknown*, never false. The answer is yes or no only when the known
  facts settle it whatever the unknown ones turn out to be (strong Kleene logic).
- **What is missing.** For an unknown answer, each unknown fact the decision depends on is tried at the values the
  rules test it against. The answer names the fact and which value gives yes or no ("needs amount_usd: up to 250 yes,
  251 and above no").
- **A proof for every decision.** Every step is recorded. `verify` checks the proof against the approved rules and the
  recorded facts without running the evaluator, and rejects a changed value, a skipped part or a step from another
  version.
- **Only what the decision needs is read.** Evaluation stops as soon as a part is settled; unrelated rules are never
  touched. Nothing carries over from one decision to the next.

## In the company

- **Drafts and approval.** A model drafts the rules from a policy document, using only the facts the company's
  systems know (`cie.playbooks.draft`). Code checks every name, type and allowed value, and looks up each rule's
  quote in the document. A draft with problems goes back to the model once. A person approves the draft
  (`POST /approvals/{id}/decide`, kind `playbook`); only an approved version decides, and approving one retires the
  version before.
- **Facts from the live state.** A fact can be bound to a record:
  `"from": {"entity": "supplier", "key": "{supplier}", "field": "certified"}`. It is read under the requester's
  permissions; a value the request supplies for it is ignored; a field with an open conflict between sources is
  unknown.
- **Deciding again.** When a record a decision read changes, or a new version is approved, the decision is made again
  and supersedes the old one.
- **Actions.** `CIE_ACTIONS_PLAYBOOKS` maps an action kind to a playbook. No refuses the action; unknown asks a
  person, naming the facts that would settle it; yes lets it go on. If the decision turns to no before the action is
  executed, the action is stale and not executed.

## Use

- API: `POST /api/playbooks`, `POST /api/playbooks/draft`, `POST /api/playbooks/{key}/decide`,
  `GET /api/playbooks/decisions/{id}`, `POST /api/playbooks/decisions/{id}/verify`.
- Command line, no database: `cie playbook check spec.json`, `cie playbook decide spec.json --facts '{...}'`.
- Tables: `playbooks` (versions) and `playbook_decisions` (migration `b0c1d2e3f4a5`).

## Limits

- Facts are yes/no, numbers, dates, text or lists. There is no arithmetic (sums, days between dates) and no currency
  conversion: the request supplies such values.
- The missing-fact search tries one fact at a time.
- The hard part is turning documents into correct rules. Until the test on real policies has run, how often a draft is
  right is unknown, which is why a person approves every draft.
- The idea of three-valued rules with checkable proofs and a missing-fact search came from the Reasoning Engine v2
  prototype. Its neural parts and Blue Brain data (non-commercial licence) are not used.

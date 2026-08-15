"""Trial and regulatory catalyst detail, from ClinicalTrials.gov and openFDA.

`RESULT_LLM_PILOT.md` located the gap precisely. Regex over 8-K text tested at
−0.333pp on ranking because it recovered *what kind* of filing a document was,
which the panel already knew from the item codes. What it never reached was the
substance: effect sizes, endpoints, patient counts, trial phase, and the dates a
readout is actually due.

Both registries publish that without a credential.

**ClinicalTrials.gov API v2** — 598,690 studies, no key, no observed rate limit.
Sponsor, phase, enrollment, status and primary completion date are all queryable
fields, which is what turns "this company has a trial" into "this company has a
Phase 3 with 300 patients whose primary completion is in November".

**openFDA** — `drug/drugsfda` carries application numbers, submission types
(NDA/BLA/ANDA) and submission status dates, so an approval can be dated and
attached to a sponsor.

The point-in-time problem, which is not solved here
---------------------------------------------------
Both registries serve the record **as it stands today**, not as it stood on the
date you are backtesting. A trial record edited after a failure — status flipped
to terminated, completion date moved, enrolment revised down — will show the
edited values against a historical row, and the model will appear to have known
the outcome in advance. That is the single most dangerous look-ahead available
in this data.

ClinicalTrials.gov does version its records, and any historical feature built
from it **must** go through :func:`study_history` and take the version current
as of the feature date. openFDA does not version, so its fields are only safe
where they are inherently dated — an approval's submission status date is a
fact about a past event, whereas a label's current text is not.

Nothing in this module writes features. It is deliberately a thin, honest client
so that the point-in-time discipline lives in the feature builder where it can
be seen.
"""

from __future__ import annotations

import pandas as pd

CTG = "https://clinicaltrials.gov/api/v2/studies"
FDA = "https://api.fda.gov"

#: The fields worth pulling by default. `PrimaryCompletionDate` is the one that
#: makes a calendar possible; `Phase` and `EnrollmentCount` are what separate a
#: readout that can move a stock from one that cannot.
FIELDS = ("NCTId", "BriefTitle", "OverallStatus", "Phase", "EnrollmentCount",
          "StartDate", "PrimaryCompletionDate", "CompletionDate",
          "LeadSponsorName", "Condition", "InterventionName",
          "LastUpdatePostDate", "StudyFirstPostDate")


def studies(client, sponsor: str | None = None, *, page_size: int = 100,
            pages: int = 1, extra: dict | None = None) -> pd.DataFrame:
    """Studies matching a sponsor, flattened to one row per trial."""
    rows: list[dict] = []
    token = None
    for _ in range(max(1, pages)):
        q = {"pageSize": str(page_size), "fields": ",".join(FIELDS)}
        if sponsor:
            q["query.spons"] = sponsor
        if extra:
            q.update(extra)
        if token:
            q["pageToken"] = token
        url = CTG + "?" + "&".join(f"{k}={v}" for k, v in q.items())
        blob = client.get(url)
        if not blob:
            break
        for s in blob.get("studies", []):
            p = s.get("protocolSection", {})
            ident = p.get("identificationModule", {})
            status = p.get("statusModule", {})
            design = p.get("designModule", {})
            spon = p.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {})
            rows.append({
                "nct": ident.get("nctId"),
                "title": ident.get("briefTitle"),
                "sponsor": spon.get("name"),
                "status": status.get("overallStatus"),
                "phase": ",".join(design.get("phases", []) or []),
                "enrollment": (design.get("enrollmentInfo") or {}).get("count"),
                "start": (status.get("startDateStruct") or {}).get("date"),
                "primary_completion": (status.get("primaryCompletionDateStruct") or {}).get("date"),
                "completion": (status.get("completionDateStruct") or {}).get("date"),
                "first_posted": (status.get("studyFirstPostDateStruct") or {}).get("date"),
                "last_update": (status.get("lastUpdatePostDateStruct") or {}).get("date"),
            })
        token = blob.get("nextPageToken")
        if not token:
            break
    d = pd.DataFrame(rows)
    for c in ("start", "primary_completion", "completion", "first_posted", "last_update"):
        if c in d:
            d[c] = pd.to_datetime(d[c], errors="coerce")
    return d


def study_history(client, nct: str) -> pd.DataFrame:
    """Every recorded version of one study, so a feature can take the one that was current.

    Without this a backtest reads today's record against a 2019 row. A trial
    that was "recruiting, primary completion Q4 2019" and was later revised to
    "terminated" will read as terminated in 2019, and any model trained on it
    will look prescient for a reason that has nothing to do with skill.
    """
    blob = client.get(f"{CTG}/{nct}/history")
    if not blob:
        return pd.DataFrame()
    rows = [{"nct": nct,
             "version": c.get("version"),
             "date": c.get("versionDate") or c.get("date"),
             "status": (c.get("statusModule") or {}).get("overallStatus")}
            for c in (blob.get("changes") or blob.get("history") or [])]
    d = pd.DataFrame(rows)
    if "date" in d:
        d["date"] = pd.to_datetime(d["date"], errors="coerce")
    return d


def drug_approvals(client, year: int, limit: int = 1000) -> pd.DataFrame:
    """Applications with a submission status date inside one year.

    The date is a fact about a past event, which is what makes this safe to use
    historically in a way that a current drug label is not.
    """
    url = (f"{FDA}/drug/drugsfda.json?search=submissions.submission_status_date:"
           f"[{year}0101+TO+{year}1231]&limit={min(limit, 1000)}")
    blob = client.get(url)
    if not blob:
        return pd.DataFrame()
    rows = []
    for r in blob.get("results", []):
        sponsor = r.get("sponsor_name")
        app = r.get("application_number")
        for s in r.get("submissions", []) or []:
            rows.append({"application": app, "sponsor": sponsor,
                         "type": s.get("submission_type"),
                         "number": s.get("submission_number"),
                         "status": s.get("submission_status"),
                         "date": s.get("submission_status_date"),
                         "review": s.get("review_priority")})
    d = pd.DataFrame(rows)
    if "date" in d:
        d["date"] = pd.to_datetime(d["date"], format="%Y%m%d", errors="coerce")
    return d


__all__ = ["CTG", "FDA", "FIELDS", "drug_approvals", "studies", "study_history"]

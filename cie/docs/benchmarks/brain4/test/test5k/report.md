### The company brain test, round 2 (v16)

587 questions (counts 60, email_chat 40, history 40, multi 56, not_found 40, prose 80, single 140, unanswerable 131; parts heldout 91, v15 276, v16 220) on /tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad/brain4/test5k.

| arm | single | multi | prose | not_found | counts | history | email_chat | unanswerable | mean of 8 | mean of v15's 4 | left out | not answered |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| quotes | 0.116 | 0.036 | 0.556 | 0.000 | 0.017 | 0.025 | 0.297 | 0.000 | 0.131 | 0.177 | 0 | 0 |
| v1 | 0.796 | 0.036 | 0.000 | 0.250 | 0.000 | 0.125 | 0.150 | 0.176 | 0.192 | 0.271 | 0 | 0 |
| v17 | 0.929 | 0.946 | 0.671 | 1.000 | 1.000 | 1.000 | 1.000 | 0.885 | 0.929 | 0.887 | 0 | 0 |
| v18 | 0.929 | 0.946 | 0.681 | 1.000 | 1.000 | 1.000 | 1.000 | 0.908 | 0.933 | 0.889 | 0 | 0 |
| v2 | 0.641 | 0.036 | 0.006 | 0.250 | 0.000 | 0.200 | 0.214 | 0.023 | 0.171 | 0.233 | 0 | 0 |

By group:

| arm | absent | chat | combine | compare | count | deadlines | descriptive | email | embedded | fields | filter | heldout | history | link | lists | names | not_found | prose |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| quotes | 0.000 | 1.000 | 0.038 | 0.000 | 0.018 | 0.000 | 0.160 | 0.093 | 0.050 | 0.200 | 0.000 | 0.000 | 0.025 | 0.042 | 0.000 | 0.121 | 0.000 | 0.556 |
| v1 | 0.000 | 0.000 | 0.038 | 0.000 | 0.000 | 0.933 | 0.780 | 0.194 | 0.750 | 0.833 | 0.000 | 0.253 | 0.125 | 0.042 | 0.800 | 0.644 | 0.250 | 0.000 |
| v17 | 1.000 | 1.000 | 0.962 | 1.000 | 1.000 | 1.000 | 0.900 | 1.000 | 0.950 | 0.967 | 1.000 | 0.835 | 1.000 | 0.917 | 0.800 | 1.000 | 1.000 | 0.671 |
| v18 | 1.000 | 1.000 | 0.962 | 1.000 | 1.000 | 1.000 | 0.900 | 1.000 | 0.950 | 0.967 | 1.000 | 0.868 | 1.000 | 0.917 | 0.800 | 1.000 | 1.000 | 0.681 |
| v2 | 0.000 | 0.333 | 0.000 | 0.000 | 0.000 | 0.933 | 0.620 | 0.180 | 0.400 | 0.733 | 0.000 | 0.033 | 0.200 | 0.083 | 0.800 | 0.275 | 0.250 | 0.006 |

False "not found" on answerable questions, the strict free-text score (facts quoted from a gold document; – when the arm quotes nothing or the quoted documents are not known), free-text facts in the evidence, route accuracy (mean over families), time per question (ms) and the answers' length (characters):

| arm | false not found | strict prose | quoted | prose 2,000 | prose 6,000 | prose 24,000 | route accuracy | median ms | p90 ms | max ms | median chars |
|---|---|---|---|---|---|---|---|---|---|---|---|
| quotes | 0.000 | 0.542 | 80/80 | 0.629 | 0.919 | 0.981 | 0.143 | 23.6 | 38.8 | 66.4 | 1056 |
| v1 | 0.079 | – | 0/80 | 0.019 | 0.062 | 0.100 | – | 727.1 | 1061.0 | 1615.1 | 10 |
| v17 | 0.017 | 0.671 | 74/80 | 0.660 | 0.912 | 0.919 | 0.985 | 1157.5 | 2010.3 | 27977.4 | 10 |
| v18 | 0.022 | 0.681 | 74/80 | 0.660 | 0.912 | 0.919 | 0.985 | 1206.1 | 2151.2 | 27851.8 | 10 |
| v2 | 0.053 | – | 0/80 | 0.138 | 0.173 | 0.204 | – | 1742.3 | 2144.3 | 2459.8 | 10 |

Routes of quotes (right route: a fact route for single, multi, counts, history and email_chat; prose for free text; not found for not_found; unanswerable not counted):

| family | routes | right route |
|---|---|---|
| single | {"prose": 140} | 0.000 |
| multi | {"prose": 56} | 0.000 |
| prose | {"prose": 80} | 1.000 |
| not_found | {"prose": 40} | 0.000 |
| counts | {"prose": 60} | 0.000 |
| history | {"prose": 40} | 0.000 |
| email_chat | {"prose": 40} | 0.000 |
| unanswerable | {"prose": 131} | – |
| mean over families | | **0.143** |

Routes of v17 (right route: a fact route for single, multi, counts, history and email_chat; prose for free text; not found for not_found; unanswerable not counted):

| family | routes | right route |
|---|---|---|
| single | {"absent_doc": 2, "derived": 3, "described": 38, "fact": 21, "plan": 61, "prose": 2, "table": 13} | 0.971 |
| multi | {"fact": 1, "plan": 54, "table": 1} | 1.000 |
| prose | {"absent_doc": 1, "described": 2, "fact": 2, "plan": 1, "prose": 74} | 0.925 |
| not_found | {"not_found": 40} | 1.000 |
| counts | {"table": 60} | 1.000 |
| history | {"derived": 40} | 1.000 |
| email_chat | {"derived": 40} | 1.000 |
| unanswerable | {"absent": 40, "not_found": 32, "plan": 1, "prose": 58} | – |
| mean over families | | **0.985** |

Routes of v18 (right route: a fact route for single, multi, counts, history and email_chat; prose for free text; not found for not_found; unanswerable not counted):

| family | routes | right route |
|---|---|---|
| single | {"absent_doc": 2, "derived": 3, "described": 38, "fact": 21, "plan": 61, "prose": 2, "table": 13} | 0.971 |
| multi | {"fact": 1, "plan": 54, "table": 1} | 1.000 |
| prose | {"absent_doc": 1, "described": 2, "fact": 2, "plan": 1, "prose": 74} | 0.925 |
| not_found | {"not_found": 40} | 1.000 |
| counts | {"table": 60} | 1.000 |
| history | {"derived": 40} | 1.000 |
| email_chat | {"derived": 40} | 1.000 |
| unanswerable | {"absent": 40, "absent_doc": 1, "not_found": 32, "prose": 58} | – |
| mean over families | | **0.985** |

By kind:

| kind | n | quotes | v1 | v17 | v18 | v2 |
|---|---|---|---|---|---|---|
| action_due | 8 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| action_owner_issues | 5 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| author_issues | 4 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| compare_two | 6 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| confluence_author | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| confluence_space | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| confluence_updated | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| count1_confluence | 4 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| count1_fireflies | 4 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| count1_github | 2 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| count1_google_drive | 4 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| count1_hubspot | 4 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| count1_jira | 4 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| count1_linear | 5 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| count2_confluence | 4 | 0.250 | 0.000 | 1.000 | 1.000 | 0.000 |
| count2_fireflies | 4 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| count2_google_drive | 5 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| count2_hubspot | 4 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| count2_jira | 4 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| count2_linear | 4 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| count_gmail | 4 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| created_on | 5 | 0.000 | 0.800 | 1.000 | 1.000 | 0.600 |
| customer_tickets | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| descriptive | 50 | 0.160 | 0.780 | 0.900 | 0.900 | 0.620 |
| drive_created | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| drive_owner | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| drive_status | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| email_account | 4 | 0.500 | 0.500 | 1.000 | 1.000 | 0.000 |
| email_attachments | 5 | 0.178 | 0.600 | 1.000 | 1.000 | 0.313 |
| email_cc | 5 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| email_count | 4 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| email_date | 4 | 0.000 | 0.250 | 1.000 | 1.000 | 1.000 |
| email_sender | 4 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| email_to | 5 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| embedded_confluence_author | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| embedded_confluence_space | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_drive_created | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_drive_owner | 1 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| embedded_drive_status | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| embedded_hubspot_owner | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| embedded_hubspot_se | 1 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| embedded_hubspot_stage | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_jira_customer | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| embedded_jira_priority | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_jira_reporter | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_jira_sla | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_jira_status | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| embedded_linear_issue_assignee | 1 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| embedded_linear_issue_creator | 1 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| embedded_linear_issue_priority | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_linear_issue_status | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| embedded_meeting_customer | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| embedded_pr_merged | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_pr_repo | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| field_absent | 40 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| filter_list | 4 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| first_commenter | 6 | 0.000 | 0.167 | 1.000 | 1.000 | 0.167 |
| github_author | 2 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| heldout | 91 | 0.000 | 0.253 | 0.835 | 0.868 | 0.033 |
| hubspot_close | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| hubspot_first_activity | 6 | 0.167 | 0.000 | 1.000 | 1.000 | 0.000 |
| hubspot_owner | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| hubspot_se | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| hubspot_stage | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| issue_pr_author | 4 | 0.000 | 0.000 | 1.000 | 1.000 | 0.500 |
| jira_assignee | 2 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| jira_customer | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| jira_priority | 2 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| jira_reporter | 2 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| jira_sla | 1 | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 |
| jira_status | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| jira_ticket_assignee | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| last_comment_date | 6 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| last_updated | 5 | 0.000 | 0.000 | 1.000 | 1.000 | 0.400 |
| linear_assignee | 3 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| linear_due | 7 | 0.000 | 0.857 | 1.000 | 1.000 | 0.857 |
| linear_due_window | 2 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| linear_issue_assignee | 1 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| linear_issue_creator | 1 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| linear_issue_priority | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| linear_issue_project | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| linear_issue_status | 2 | 0.000 | 1.000 | 1.000 | 1.000 | 0.500 |
| linear_project_members | 3 | 0.000 | 0.222 | 1.000 | 1.000 | 0.222 |
| linear_status | 3 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| meeting_attendees | 3 | 0.222 | 0.590 | 1.000 | 1.000 | 0.194 |
| meeting_customer | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| meeting_date | 1 | 1.000 | 0.000 | 0.000 | 0.000 | 1.000 |
| meeting_owner | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| moved_to_status | 6 | 0.000 | 0.000 | 1.000 | 1.000 | 0.333 |
| nf_person | 10 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| nf_pr | 10 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| nf_ticket | 10 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| nf_title | 10 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| owner_accounts | 3 | 0.000 | 0.000 | 0.667 | 0.667 | 0.000 |
| parent_issue | 4 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| person_count | 5 | 0.200 | 0.000 | 1.000 | 1.000 | 0.000 |
| person_first | 5 | 0.000 | 0.200 | 1.000 | 1.000 | 0.000 |
| pr_author | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| pr_days_to_merge | 6 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| pr_issue | 4 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| pr_issue_creator | 3 | 0.000 | 0.000 | 0.333 | 0.333 | 0.000 |
| pr_issue_project | 3 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| pr_issue_team | 3 | 0.333 | 0.000 | 1.000 | 1.000 | 0.000 |
| pr_merged | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| pr_repo | 1 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| pr_reviewers | 4 | 0.136 | 1.000 | 1.000 | 1.000 | 0.375 |
| prose | 80 | 0.556 | 0.000 | 0.671 | 0.681 | 0.006 |
| reporter_issues | 4 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| slack_channel | 4 | 1.000 | 0.000 | 1.000 | 1.000 | 0.750 |
| slack_starter | 5 | 1.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| ticket_link | 3 | 0.000 | 0.333 | 1.000 | 1.000 | 0.000 |

Big folder minus the small one (/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad/brain4/test5ksmall; not reproduced there, left out: 1):

| arm | questions | single | multi | prose | changed |
|---|---|---|---|---|---|
| quotes | 586 | 0.001 | 0.018 | -0.034 | 19 |
| v1 | 586 | -0.021 | 0.000 | 0.000 | 12 |
| v17 | 586 | -0.007 | 0.000 | -0.002 | 18 |
| v18 | 586 | -0.007 | 0.000 | -0.009 | 12 |
| v2 | 586 | 0.003 | -0.035 | 0.000 | 16 |

Rules: none applied (`--preregistered` applies them).

- best other arm per family: {"single": {"arm": "v17", "mean": 0.929}, "multi": {"arm": "v17", "mean": 0.946}, "prose": {"arm": "v18", "mean": 0.681}, "not_found": {"arm": "v17", "mean": 1.0}, "counts": {"arm": "v17", "mean": 1.0}, "history": {"arm": "v17", "mean": 1.0}, "email_chat": {"arm": "v17", "mean": 1.0}, "unanswerable": {"arm": "v18", "mean": 0.908}}
- the v16 brain's own answers, never another arm: ["v16", "v16_seed1"]
- hash-seed check (v16 under another hash seed, v16_seed1): null
- arms: {"quotes": {"arm": "quotes", "file": "quotes.jsonl", "single": null, "plans": null, "router": null, "seconds": 19.53, "answers": 587, "single_sha256": null, "plans_sha256": null, "router_sha256": null, "pythonhashseed": "0"}, "v1": {"arm": "v1", "file": "factbank.jsonl", "single": null, "plans": null, "router": null, "seconds": 480.23, "answers": 587, "single_sha256": null, "plans_sha256": null, "router_sha256": null, "pythonhashseed": "0"}, "v17": {"arm": "v17", "file": "factbank_v17.jsonl", "single": "docs/benchmarks/brain2/lessons/single_lessons.json", "plans": "docs/benchmarks/brain2/lessons/plan_lessons.json", "router": "docs/benchmarks/brain2/lessons/router.json", "seconds": 920.07, "answers": 587, "single_sha256": "ee8b9d053405a47fc9cae32eff8a46cef2d742172ed6818a4aa967e5d7deb029", "plans_sha256": "4c2c8c6201be08ececdd8eb3db1d6d8f083bd06bdf038882466f06cc2712c3b7", "router_sha256": "20e9c05046406f147c3a06f99adc2363320c9d27fac0d1e4e7a386c344dfb10f", "pythonhashseed": "0"}, "v18": {"arm": "v18", "file": "factbank_v18.jsonl", "single": "docs/benchmarks/brain2/lessons/single_lessons.json", "plans": "docs/benchmarks/brain2/lessons/plan_lessons.json", "router": "docs/benchmarks/brain2/lessons/router.json", "seconds": 958.93, "answers": 587, "single_sha256": "ee8b9d053405a47fc9cae32eff8a46cef2d742172ed6818a4aa967e5d7deb029", "plans_sha256": "4c2c8c6201be08ececdd8eb3db1d6d8f083bd06bdf038882466f06cc2712c3b7", "router_sha256": "20e9c05046406f147c3a06f99adc2363320c9d27fac0d1e4e7a386c344dfb10f", "pythonhashseed": "0"}, "v2": {"arm": "v2", "file": "factbank_v2.jsonl", "single": "/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad/fb50/lessons.json", "plans": null, "router": null, "seconds": 1073.02, "answers": 587, "single_sha256": "afa4e7d9fee0a05c2a267c38e019513b653bfa5ce700c0eddfd17331c0ef7dd9", "plans_sha256": null, "router_sha256": null, "pythonhashseed": "0"}}
- left out as stale: {}
- builds: {"factbank": {"sources": 5000, "entities": 14254, "facts": 97606, "bytes": 95019008, "check": {"ok": true, "errors": [], "facts": 97606, "stale": 97578, "contradictions": 0, "contradiction_examples": []}, "seconds": 6.27}, "factbank_v2": {"sources": 5000, "entities": 14254, "facts": 116330, "bytes": 103063552, "check": {"ok": true, "errors": [], "facts": 116330, "stale": 116293, "contradictions": 0, "contradiction_examples": []}, "seconds": 12.77}}
- draw: {"seed": 1020, "mix15": {"asked": {"deadlines": 15, "lists": 15, "fields": 30, "names": 10, "link": 15, "combine": 15, "compare": 6, "not_found": 40, "prose": 80, "descriptive": 50}, "given": {"deadlines": 15, "lists": 15, "fields": 30, "names": 10, "link": 15, "combine": 15, "compare": 6, "not_found": 40, "prose": 80, "descriptive": 50}}, "mix16": {"asked": {"counts": 60, "history": 40, "email_chat": 40, "pr_issue_project": 3, "pr_issue_creator": 3, "pr_issue_team": 3, "author_issues": 4, "reporter_issues": 4, "owner_accounts": 3, "field_absent": 40, "embedded": 20}, "given": {"counts": 60, "history": 40, "email_chat": 40, "pr_issue_project": 3, "pr_issue_creator": 3, "pr_issue_team": 3, "author_issues": 4, "reporter_issues": 4, "owner_accounts": 3, "field_absent": 40, "embedded": 20}}, "heldout": {"read": 91, "kept": 91, "set_aside": {}}, "set_aside_written": {"action_owner_issues": 17, "count1_confluence": 1, "count1_fireflies": 1, "count1_github": 5, "count1_gmail": 2, "count1_google_drive": 10, "count1_hubspot": 1, "count1_linear": 8, "count2_confluence": 2, "count2_fireflies": 4, "count2_google_drive": 25, "count2_hubspot": 57, "count2_jira": 13, "count2_linear": 79, "count_gmail": 31, "created_on": 29, "email_account": 418, "email_cc": 1, "email_count": 1, "email_to": 2, "embedded_confluence_author": 3, "embedded_confluence_space": 4, "embedded_confluence_updated": 4, "embedded_drive_created": 16, "embedded_drive_owner": 5, "embedded_drive_status": 27, "embedded_hubspot_close": 3, "embedded_hubspot_owner": 3, "embedded_hubspot_se": 3, "embedded_hubspot_stage": 2, "embedded_jira_customer": 3, "embedded_jira_priority": 4, "embedded_jira_reporter": 3, "embedded_jira_sla": 1, "embedded_jira_status": 1, "embedded_jira_ticket_assignee": 2, "embedded_linear_issue_assignee": 8, "embedded_linear_issue_creator": 2, "embedded_linear_issue_priority": 2, "embedded_linear_issue_project": 2, "embedded_linear_issue_status": 10, "embedded_meeting_customer": 51, "embedded_meeting_date": 6, "embedded_meeting_owner": 4, "embedded_pr_author": 7, "embedded_pr_merged": 4, "embedded_pr_repo": 3, "field_absent": 30, "last_updated": 106, "person_count": 12, "slack_channel": 66, "ticket_link": 3}, "gold_documents": 571}

### Round 4: v18 against v17

Round 4's rules are the ones below. The round-2 sections above (their rules, "own" labels and best-other pairing) are
not used in round 4: there v17, v18 and v18_seed1 count as other arms.

v18 minus v17 (paired over the questions; 95% bootstrap interval; questions better and worse):

| family | questions | v18 - v17 | 95% interval | better | worse |
|---|---|---|---|---|---|
| single | 140 | 0.000 | (0.0, 0.0) | 0 | 0 |
| multi | 56 | 0.000 | (0.0, 0.0) | 0 | 0 |
| prose | 80 | 0.010 | (-0.05, 0.067) | 7 | 4 |
| not_found | 40 | 0.000 | (0.0, 0.0) | 0 | 0 |
| counts | 60 | 0.000 | (0.0, 0.0) | 0 | 0 |
| history | 40 | 0.000 | (0.0, 0.0) | 0 | 0 |
| email_chat | 40 | 0.000 | (0.0, 0.0) | 0 | 0 |
| unanswerable | 131 | 0.023 | (0.0, 0.046) | 3 | 0 |
| descriptive | 50 | 0.000 | (0.0, 0.0) | 0 | 0 |
| all | 587 | 0.007 | (-0.003, 0.017) | 10 | 4 |

Free-text answers' mean length: v17 917.5, v18 890.1 characters.

Hash-seed check (v18 against v18_seed1): not run.

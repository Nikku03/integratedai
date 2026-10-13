### The company brain test, round 2 (v16)

518 questions (counts 40, email_chat 40, history 40, multi 56, not_found 20, prose 50, single 180, unanswerable 92; parts heldout 72, v15 266, v16 180) on /tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad/brain3/test5k.

| arm | single | multi | prose | not_found | counts | history | email_chat | unanswerable | mean of 8 | mean of v15's 4 | left out | not answered |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| quotes | 0.132 | 0.018 | 0.630 | 0.000 | 0.025 | 0.025 | 0.348 | 0.000 | 0.147 | 0.195 | 0 | 0 |
| v17 | 0.906 | 0.929 | 0.750 | 1.000 | 1.000 | 1.000 | 1.000 | 0.913 | 0.937 | 0.896 | 0 | 0 |
| v16 | 0.861 | 0.929 | 0.750 | 1.000 | 1.000 | 1.000 | 1.000 | 0.913 | 0.932 | 0.885 | 0 | 0 |
| v1 | 0.827 | 0.089 | 0.000 | 0.350 | 0.000 | 0.150 | 0.275 | 0.228 | 0.240 | 0.317 | 0 | 0 |
| v2 | 0.699 | 0.071 | 0.000 | 0.250 | 0.000 | 0.175 | 0.292 | 0.022 | 0.189 | 0.255 | 0 | 0 |

By group:

| arm | absent | chat | combine | compare | count | deadlines | descriptive | email | embedded | fields | filter | heldout | history | link | lists | names | not_found | prose |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| quotes | 0.000 | 1.000 | 0.000 | 0.000 | 0.026 | 0.000 | 0.144 | 0.186 | 0.150 | 0.200 | 0.000 | 0.000 | 0.025 | 0.042 | 0.000 | 0.174 | 0.000 | 0.630 |
| v17 | 1.000 | 1.000 | 0.923 | 1.000 | 1.000 | 1.000 | 0.878 | 1.000 | 0.950 | 0.900 | 1.000 | 0.889 | 1.000 | 0.917 | 1.000 | 0.800 | 1.000 | 0.750 |
| v16 | 1.000 | 1.000 | 0.923 | 1.000 | 1.000 | 1.000 | 0.789 | 1.000 | 0.950 | 0.900 | 1.000 | 0.889 | 1.000 | 0.917 | 1.000 | 0.800 | 1.000 | 0.750 |
| v1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.811 | 0.344 | 0.900 | 0.833 | 0.000 | 0.292 | 0.150 | 0.208 | 0.800 | 0.580 | 0.350 | 0.000 |
| v2 | 0.000 | 0.250 | 0.000 | 0.000 | 0.000 | 0.867 | 0.756 | 0.302 | 0.700 | 0.567 | 0.000 | 0.028 | 0.175 | 0.167 | 0.800 | 0.175 | 0.250 | 0.000 |

False "not found" on answerable questions, the strict free-text score (facts quoted from a gold document; – when the arm quotes nothing or the quoted documents are not known), free-text facts in the evidence, route accuracy (mean over families), time per question (ms) and the answers' length (characters):

| arm | false not found | strict prose | quoted | prose 2,000 | prose 6,000 | prose 24,000 | route accuracy | median ms | p90 ms | max ms | median chars |
|---|---|---|---|---|---|---|---|---|---|---|---|
| quotes | 0.000 | 0.630 | 50/50 | 0.720 | 0.930 | 0.980 | 0.143 | 24.7 | 40.8 | 66.5 | 1059 |
| v17 | 0.012 | 0.750 | 47/50 | 0.723 | 0.920 | 0.940 | 0.985 | 840.7 | 1441.1 | 5896.6 | 10 |
| v16 | 0.015 | 0.750 | 47/50 | 0.723 | 0.920 | 0.940 | 0.985 | 848.0 | 1498.8 | 5744.8 | 10 |
| v1 | 0.071 | – | 0/50 | 0.020 | 0.080 | 0.140 | – | 737.2 | 1087.2 | 1498.5 | 10 |
| v2 | 0.047 | – | 0/50 | 0.110 | 0.140 | 0.180 | – | 1800.6 | 2234.0 | 2554.9 | 10 |

Routes of quotes (right route: a fact route for single, multi, counts, history and email_chat; prose for free text; not found for not_found; unanswerable not counted):

| family | routes | right route |
|---|---|---|
| single | {"prose": 180} | 0.000 |
| multi | {"prose": 56} | 0.000 |
| prose | {"prose": 50} | 1.000 |
| not_found | {"prose": 20} | 0.000 |
| counts | {"prose": 40} | 0.000 |
| history | {"prose": 40} | 0.000 |
| email_chat | {"prose": 40} | 0.000 |
| unanswerable | {"prose": 92} | – |
| mean over families | | **0.143** |

Routes of v17 (right route: a fact route for single, multi, counts, history and email_chat; prose for free text; not found for not_found; unanswerable not counted):

| family | routes | right route |
|---|---|---|
| single | {"absent_doc": 3, "derived": 5, "described": 67, "fact": 30, "plan": 57, "prose": 5, "table": 13} | 0.956 |
| multi | {"plan": 55, "table": 1} | 1.000 |
| prose | {"absent_doc": 2, "described": 1, "prose": 47} | 0.940 |
| not_found | {"not_found": 20} | 1.000 |
| counts | {"table": 40} | 1.000 |
| history | {"derived": 40} | 1.000 |
| email_chat | {"derived": 40} | 1.000 |
| unanswerable | {"absent": 20, "absent_doc": 1, "not_found": 22, "plan": 1, "prose": 48} | – |
| mean over families | | **0.985** |

Routes of v16 (right route: a fact route for single, multi, counts, history and email_chat; prose for free text; not found for not_found; unanswerable not counted):

| family | routes | right route |
|---|---|---|
| single | {"absent_doc": 3, "derived": 5, "fact": 93, "plan": 61, "prose": 5, "table": 13} | 0.956 |
| multi | {"plan": 55, "table": 1} | 1.000 |
| prose | {"absent_doc": 3, "prose": 47} | 0.940 |
| not_found | {"not_found": 20} | 1.000 |
| counts | {"table": 40} | 1.000 |
| history | {"derived": 40} | 1.000 |
| email_chat | {"derived": 40} | 1.000 |
| unanswerable | {"absent": 20, "absent_doc": 1, "not_found": 22, "plan": 1, "prose": 48} | – |
| mean over families | | **0.985** |

v16 minus the best other arm on each family (paired over the family's questions; 95% bootstrap interval):

| family | best other arm | questions | v16 - other | 95% interval |
|---|---|---|---|---|
| single | v17 | 180 | -0.044 | [-0.078, -0.017] |
| multi | v17 | 56 | 0.000 | [0.0, 0.0] |
| prose | v17 | 50 | 0.000 | [0.0, 0.0] |
| not_found | v17 | 20 | 0.000 | [0.0, 0.0] |
| counts | v17 | 40 | 0.000 | [0.0, 0.0] |
| history | v17 | 40 | 0.000 | [0.0, 0.0] |
| email_chat | v17 | 40 | 0.000 | [0.0, 0.0] |
| unanswerable | v17 | 92 | 0.000 | [0.0, 0.0] |

By kind:

| kind | n | quotes | v17 | v16 | v1 | v2 |
|---|---|---|---|---|---|---|
| action_due | 7 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| action_owner_issues | 5 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| author_issues | 4 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| compare_two | 6 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| confluence_author | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| confluence_space | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| confluence_updated | 2 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| count1_confluence | 2 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| count1_fireflies | 3 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| count1_github | 3 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| count1_gmail | 2 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| count1_google_drive | 3 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| count1_hubspot | 3 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| count1_jira | 2 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| count1_linear | 3 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| count2_confluence | 2 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| count2_fireflies | 2 | 0.500 | 1.000 | 1.000 | 0.000 | 0.000 |
| count2_google_drive | 3 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| count2_hubspot | 3 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| count2_jira | 2 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| count2_linear | 2 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| count_gmail | 3 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| created_on | 5 | 0.000 | 1.000 | 1.000 | 0.400 | 0.400 |
| customer_tickets | 3 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| descriptive | 90 | 0.144 | 0.878 | 0.789 | 0.811 | 0.756 |
| drive_created | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| drive_owner | 1 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| drive_status | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| email_account | 5 | 0.400 | 1.000 | 1.000 | 1.000 | 0.000 |
| email_attachments | 4 | 0.735 | 1.000 | 1.000 | 0.750 | 0.417 |
| email_cc | 4 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| email_count | 5 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| email_date | 5 | 0.000 | 1.000 | 1.000 | 0.400 | 1.000 |
| email_sender | 5 | 0.200 | 1.000 | 1.000 | 0.200 | 0.600 |
| email_to | 4 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| embedded_confluence_space | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_confluence_updated | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_drive_created | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_drive_owner | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_drive_status | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_hubspot_close | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_hubspot_se | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_jira_customer | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| embedded_jira_priority | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_jira_reporter | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_jira_status | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| embedded_jira_ticket_assignee | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_linear_issue_assignee | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| embedded_linear_issue_creator | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| embedded_linear_issue_project | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| embedded_meeting_date | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |
| embedded_meeting_owner | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_pr_author | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_pr_merged | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_pr_repo | 1 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| field_absent | 20 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| filter_list | 2 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| first_commenter | 5 | 0.000 | 1.000 | 1.000 | 0.600 | 0.200 |
| github_author | 2 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| heldout | 72 | 0.000 | 0.889 | 0.889 | 0.292 | 0.028 |
| hubspot_close | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| hubspot_first_activity | 6 | 0.167 | 1.000 | 1.000 | 0.000 | 0.167 |
| hubspot_owner | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| hubspot_se | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| hubspot_stage | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| issue_pr_author | 4 | 0.000 | 1.000 | 1.000 | 0.750 | 0.500 |
| jira_assignee | 2 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| jira_customer | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| jira_priority | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| jira_reporter | 2 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| jira_sla | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| jira_status | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| jira_ticket_assignee | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| last_comment_date | 6 | 0.000 | 1.000 | 1.000 | 0.000 | 0.167 |
| last_updated | 6 | 0.000 | 1.000 | 1.000 | 0.167 | 0.333 |
| linear_assignee | 2 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| linear_due | 8 | 0.000 | 1.000 | 1.000 | 1.000 | 0.750 |
| linear_due_window | 3 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| linear_issue_assignee | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| linear_issue_creator | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| linear_issue_priority | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| linear_issue_project | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| linear_issue_status | 2 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| linear_project_members | 3 | 0.000 | 0.333 | 0.333 | 0.000 | 0.000 |
| linear_status | 3 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| meeting_attendees | 3 | 0.399 | 1.000 | 1.000 | 0.600 | 0.250 |
| meeting_customer | 1 | 1.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| meeting_date | 1 | 1.000 | 0.000 | 0.000 | 0.000 | 1.000 |
| meeting_owner | 1 | 1.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| moved_to_status | 6 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| nf_person | 5 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| nf_pr | 5 | 0.000 | 1.000 | 1.000 | 0.400 | 0.000 |
| nf_ticket | 5 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| nf_title | 5 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| owner_accounts | 3 | 0.000 | 0.333 | 0.333 | 0.000 | 0.000 |
| parent_issue | 4 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| person_count | 5 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| person_first | 5 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| pr_author | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| pr_days_to_merge | 6 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| pr_issue | 4 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| pr_issue_creator | 3 | 0.000 | 0.333 | 0.333 | 0.000 | 0.000 |
| pr_issue_project | 3 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| pr_issue_team | 3 | 0.333 | 1.000 | 1.000 | 0.667 | 0.667 |
| pr_merged | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| pr_repo | 1 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| pr_reviewers | 4 | 0.136 | 1.000 | 1.000 | 1.000 | 0.250 |
| prose | 50 | 0.630 | 0.750 | 0.750 | 0.000 | 0.000 |
| reporter_issues | 4 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| slack_channel | 4 | 1.000 | 1.000 | 1.000 | 0.000 | 0.500 |
| slack_starter | 4 | 1.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| ticket_link | 3 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |

Big folder minus the small one (/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad/brain3/test5ksmall; not reproduced there, left out: 0):

| arm | questions | single | multi | prose | changed |
|---|---|---|---|---|---|
| quotes | 518 | 0.007 | 0.000 | -0.070 | 19 |
| v17 | 518 | 0.006 | -0.017 | 0.020 | 9 |
| v16 | 518 | 0.005 | -0.017 | 0.020 | 7 |
| v1 | 518 | 0.013 | 0.018 | 0.000 | 27 |
| v2 | 518 | 0.002 | 0.000 | 0.000 | 15 |

Rules: none applied (`--preregistered` applies them).

- best other arm per family: {"single": {"arm": "v17", "mean": 0.906}, "multi": {"arm": "v17", "mean": 0.929}, "prose": {"arm": "v17", "mean": 0.75}, "not_found": {"arm": "v17", "mean": 1.0}, "counts": {"arm": "v17", "mean": 1.0}, "history": {"arm": "v17", "mean": 1.0}, "email_chat": {"arm": "v17", "mean": 1.0}, "unanswerable": {"arm": "v17", "mean": 0.913}}
- the v16 brain's own answers, never another arm: ["v16", "v16_seed1"]
- hash-seed check (v16 under another hash seed, v16_seed1): null
- arms: {"quotes": {"arm": "quotes", "file": "quotes.jsonl", "single": null, "plans": null, "router": null, "seconds": 18.63, "answers": 518, "single_sha256": null, "plans_sha256": null, "router_sha256": null, "pythonhashseed": "0"}, "v17": {"arm": "v17", "file": "factbank_v17.jsonl", "single": "docs/benchmarks/brain2/lessons/single_lessons.json", "plans": "docs/benchmarks/brain2/lessons/plan_lessons.json", "router": "docs/benchmarks/brain2/lessons/router.json", "seconds": 376.86, "answers": 518, "single_sha256": "ee8b9d053405a47fc9cae32eff8a46cef2d742172ed6818a4aa967e5d7deb029", "plans_sha256": "4c2c8c6201be08ececdd8eb3db1d6d8f083bd06bdf038882466f06cc2712c3b7", "router_sha256": "20e9c05046406f147c3a06f99adc2363320c9d27fac0d1e4e7a386c344dfb10f", "pythonhashseed": "0"}, "v16": {"arm": "v16", "file": "factbank_v16.jsonl", "single": "docs/benchmarks/brain2/lessons/single_lessons.json", "plans": "docs/benchmarks/brain2/lessons/plan_lessons.json", "router": "docs/benchmarks/brain2/lessons/router.json", "seconds": 392.86, "answers": 518, "single_sha256": "ee8b9d053405a47fc9cae32eff8a46cef2d742172ed6818a4aa967e5d7deb029", "plans_sha256": "4c2c8c6201be08ececdd8eb3db1d6d8f083bd06bdf038882466f06cc2712c3b7", "router_sha256": "20e9c05046406f147c3a06f99adc2363320c9d27fac0d1e4e7a386c344dfb10f", "pythonhashseed": "0"}, "v1": {"arm": "v1", "file": "factbank.jsonl", "single": null, "plans": null, "router": null, "seconds": 433.3, "answers": 518, "single_sha256": null, "plans_sha256": null, "router_sha256": null, "pythonhashseed": "0"}, "v2": {"arm": "v2", "file": "factbank_v2.jsonl", "single": "/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad/fb50/lessons.json", "plans": null, "router": null, "seconds": 983.61, "answers": 518, "single_sha256": "afa4e7d9fee0a05c2a267c38e019513b653bfa5ce700c0eddfd17331c0ef7dd9", "plans_sha256": null, "router_sha256": null, "pythonhashseed": "0"}}
- left out as stale: {}
- builds: {"factbank": {"sources": 5000, "entities": 14278, "facts": 97599, "bytes": 95346688, "check": {"ok": true, "errors": [], "facts": 97599, "stale": 97579, "contradictions": 0, "contradiction_examples": []}, "seconds": 7.48}, "factbank_v2": {"sources": 5000, "entities": 14278, "facts": 116153, "bytes": 103292928, "check": {"ok": true, "errors": [], "facts": 116153, "stale": 116131, "contradictions": 0, "contradiction_examples": []}, "seconds": 15.13}}
- draw: {"seed": 1010, "mix15": {"asked": {"deadlines": 15, "lists": 15, "fields": 30, "names": 10, "link": 15, "combine": 15, "compare": 6, "not_found": 20, "prose": 50, "descriptive": 90}, "given": {"deadlines": 15, "lists": 15, "fields": 30, "names": 10, "link": 15, "combine": 15, "compare": 6, "not_found": 20, "prose": 50, "descriptive": 90}}, "mix16": {"asked": {"counts": 40, "history": 40, "email_chat": 40, "pr_issue_project": 3, "pr_issue_creator": 3, "pr_issue_team": 3, "author_issues": 4, "reporter_issues": 4, "owner_accounts": 3, "field_absent": 20, "embedded": 20}, "given": {"counts": 40, "history": 40, "email_chat": 40, "pr_issue_project": 3, "pr_issue_creator": 3, "pr_issue_team": 3, "author_issues": 4, "reporter_issues": 4, "owner_accounts": 3, "field_absent": 20, "embedded": 20}}, "heldout": {"read": 72, "kept": 72, "set_aside": {}}, "set_aside_written": {"action_owner_issues": 9, "count1_confluence": 5, "count1_fireflies": 1, "count1_github": 3, "count1_gmail": 2, "count1_google_drive": 13, "count1_hubspot": 1, "count1_jira": 1, "count1_linear": 9, "count2_confluence": 2, "count2_fireflies": 5, "count2_google_drive": 21, "count2_hubspot": 72, "count2_jira": 9, "count2_linear": 91, "count_gmail": 28, "created_on": 24, "email_account": 399, "email_cc": 2, "email_to": 5, "embedded_confluence_author": 5, "embedded_confluence_space": 6, "embedded_confluence_updated": 6, "embedded_drive_created": 12, "embedded_drive_owner": 10, "embedded_drive_status": 21, "embedded_hubspot_close": 2, "embedded_hubspot_owner": 5, "embedded_hubspot_se": 4, "embedded_hubspot_stage": 4, "embedded_jira_customer": 3, "embedded_jira_priority": 3, "embedded_jira_reporter": 4, "embedded_jira_sla": 3, "embedded_jira_status": 3, "embedded_jira_ticket_assignee": 3, "embedded_linear_issue_assignee": 7, "embedded_linear_issue_creator": 4, "embedded_linear_issue_priority": 2, "embedded_linear_issue_project": 4, "embedded_linear_issue_status": 12, "embedded_meeting_customer": 64, "embedded_meeting_date": 6, "embedded_meeting_owner": 8, "embedded_pr_author": 9, "embedded_pr_merged": 6, "embedded_pr_repo": 6, "field_absent": 26, "last_updated": 71, "person_count": 7, "pr_issue_project": 4, "slack_channel": 82, "ticket_link": 2}, "gold_documents": 539}

### Round 3: v17 against v16

Round 3's rules are the ones below. The round-2 sections above (their rules, "own" labels and best-other pairing) are
not used in round 3: there v17 and v17_seed1 count as other arms.

v17 minus v16 (paired over the questions; 95% bootstrap interval; questions better and worse):

| family | questions | v17 - v16 | 95% interval | better | worse |
|---|---|---|---|---|---|
| single | 180 | 0.044 | (0.017, 0.078) | 8 | 0 |
| multi | 56 | 0.000 | (0.0, 0.0) | 0 | 0 |
| prose | 50 | 0.000 | (0.0, 0.0) | 0 | 0 |
| not_found | 20 | 0.000 | (0.0, 0.0) | 0 | 0 |
| counts | 40 | 0.000 | (0.0, 0.0) | 0 | 0 |
| history | 40 | 0.000 | (0.0, 0.0) | 0 | 0 |
| email_chat | 40 | 0.000 | (0.0, 0.0) | 0 | 0 |
| unanswerable | 92 | 0.000 | (0.0, 0.0) | 0 | 0 |
| descriptive | 90 | 0.089 | (0.033, 0.144) | 8 | 0 |
| all | 518 | 0.015 | (0.006, 0.027) | 8 | 0 |

Hash-seed check (v17 against v17_seed1): not run.

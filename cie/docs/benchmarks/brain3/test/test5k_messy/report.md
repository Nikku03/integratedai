### The company brain test, round 2 (v16)

517 questions (counts 40, email_chat 40, history 40, multi 56, not_found 20, prose 50, single 179, unanswerable 92; parts heldout 72, v15 265, v16 180) on /tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad/brain3/test5k_messy.

| arm | single | multi | prose | not_found | counts | history | email_chat | unanswerable | mean of 8 | mean of v15's 4 | left out | not answered |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| quotes | 0.128 | 0.054 | 0.630 | 0.000 | 0.025 | 0.050 | 0.348 | 0.000 | 0.154 | 0.203 | 0 | 0 |
| v17 | 0.854 | 0.839 | 0.750 | 0.800 | 0.825 | 0.950 | 0.975 | 0.880 | 0.859 | 0.811 | 0 | 0 |
| v16 | 0.809 | 0.839 | 0.750 | 0.800 | 0.825 | 0.950 | 0.975 | 0.870 | 0.852 | 0.799 | 0 | 0 |
| v1 | 0.791 | 0.089 | 0.000 | 0.350 | 0.000 | 0.100 | 0.200 | 0.228 | 0.220 | 0.307 | 0 | 0 |
| v2 | 0.683 | 0.107 | 0.000 | 0.250 | 0.000 | 0.175 | 0.300 | 0.022 | 0.192 | 0.260 | 0 | 0 |
| v17_seed1 | 0.854 | 0.839 | 0.750 | 0.800 | 0.825 | 0.950 | 0.975 | 0.880 | 0.859 | 0.811 | 0 | 0 |

By group:

| arm | absent | chat | combine | compare | count | deadlines | descriptive | email | embedded | fields | filter | heldout | history | link | lists | names | not_found | prose |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| quotes | 0.000 | 1.000 | 0.038 | 0.000 | 0.026 | 0.000 | 0.144 | 0.186 | 0.150 | 0.172 | 0.000 | 0.000 | 0.050 | 0.083 | 0.000 | 0.188 | 0.000 | 0.630 |
| v17 | 0.850 | 1.000 | 0.769 | 1.000 | 0.816 | 0.800 | 0.878 | 0.969 | 0.900 | 0.862 | 1.000 | 0.889 | 0.950 | 0.875 | 0.793 | 0.700 | 0.800 | 0.750 |
| v16 | 0.800 | 1.000 | 0.769 | 1.000 | 0.816 | 0.800 | 0.789 | 0.969 | 0.900 | 0.862 | 1.000 | 0.889 | 0.950 | 0.875 | 0.793 | 0.700 | 0.800 | 0.750 |
| v1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.811 | 0.250 | 0.900 | 0.793 | 0.000 | 0.292 | 0.100 | 0.208 | 0.453 | 0.580 | 0.350 | 0.000 |
| v2 | 0.000 | 0.500 | 0.038 | 0.000 | 0.000 | 0.933 | 0.756 | 0.250 | 0.700 | 0.414 | 0.000 | 0.028 | 0.175 | 0.208 | 0.766 | 0.275 | 0.250 | 0.000 |
| v17_seed1 | 0.850 | 1.000 | 0.769 | 1.000 | 0.816 | 0.800 | 0.878 | 0.969 | 0.900 | 0.862 | 1.000 | 0.889 | 0.950 | 0.875 | 0.793 | 0.700 | 0.800 | 0.750 |

False "not found" on answerable questions, the strict free-text score (facts quoted from a gold document; – when the arm quotes nothing or the quoted documents are not known), free-text facts in the evidence, route accuracy (mean over families), time per question (ms) and the answers' length (characters):

| arm | false not found | strict prose | quoted | prose 2,000 | prose 6,000 | prose 24,000 | route accuracy | median ms | p90 ms | max ms | median chars |
|---|---|---|---|---|---|---|---|---|---|---|---|
| quotes | 0.000 | 0.630 | 50/50 | 0.720 | 0.930 | 0.980 | 0.143 | 25.2 | 41.9 | 79.6 | 1056 |
| v17 | 0.025 | 0.750 | 47/50 | 0.723 | 0.920 | 0.940 | 0.947 | 873.2 | 1580.0 | 5268.0 | 10 |
| v16 | 0.027 | 0.750 | 47/50 | 0.723 | 0.920 | 0.940 | 0.947 | 903.8 | 1619.2 | 4964.4 | 10 |
| v1 | 0.054 | – | 0/50 | 0.020 | 0.080 | 0.140 | – | 729.3 | 1079.7 | 1650.1 | 10 |
| v2 | 0.052 | – | 0/50 | 0.110 | 0.140 | 0.180 | – | 1742.9 | 2181.1 | 2551.6 | 10 |
| v17_seed1 | 0.025 | 0.750 | 47/50 | 0.723 | 0.920 | 0.940 | 0.947 | 885.2 | 1515.2 | 3703.7 | 10 |

Routes of quotes (right route: a fact route for single, multi, counts, history and email_chat; prose for free text; not found for not_found; unanswerable not counted):

| family | routes | right route |
|---|---|---|
| single | {"prose": 179} | 0.000 |
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
| single | {"absent_doc": 6, "derived": 4, "described": 68, "fact": 49, "plan": 35, "prose": 7, "table": 10} | 0.927 |
| multi | {"absent_doc": 2, "fact": 3, "plan": 50, "table": 1} | 0.964 |
| prose | {"absent_doc": 2, "described": 1, "prose": 47} | 0.940 |
| not_found | {"absent_doc": 2, "described": 4, "not_found": 14} | 0.800 |
| counts | {"fact": 5, "plan": 3, "table": 32} | 1.000 |
| history | {"derived": 37, "described": 1, "plan": 2} | 1.000 |
| email_chat | {"derived": 40} | 1.000 |
| unanswerable | {"absent": 16, "absent_doc": 1, "described": 1, "not_found": 22, "plan": 2, "prose": 50} | – |
| mean over families | | **0.947** |

Routes of v16 (right route: a fact route for single, multi, counts, history and email_chat; prose for free text; not found for not_found; unanswerable not counted):

| family | routes | right route |
|---|---|---|
| single | {"absent_doc": 6, "derived": 4, "fact": 113, "plan": 39, "prose": 7, "table": 10} | 0.927 |
| multi | {"absent_doc": 2, "fact": 3, "plan": 50, "table": 1} | 0.964 |
| prose | {"absent_doc": 3, "prose": 47} | 0.940 |
| not_found | {"absent_doc": 2, "fact": 4, "not_found": 14} | 0.800 |
| counts | {"fact": 5, "plan": 3, "table": 32} | 1.000 |
| history | {"derived": 37, "fact": 1, "plan": 2} | 1.000 |
| email_chat | {"derived": 40} | 1.000 |
| unanswerable | {"absent": 16, "absent_doc": 1, "fact": 1, "not_found": 22, "plan": 2, "prose": 50} | – |
| mean over families | | **0.947** |

Routes of v17_seed1 (right route: a fact route for single, multi, counts, history and email_chat; prose for free text; not found for not_found; unanswerable not counted):

| family | routes | right route |
|---|---|---|
| single | {"absent_doc": 6, "derived": 4, "described": 68, "fact": 49, "plan": 35, "prose": 7, "table": 10} | 0.927 |
| multi | {"absent_doc": 2, "fact": 3, "plan": 50, "table": 1} | 0.964 |
| prose | {"absent_doc": 2, "described": 1, "prose": 47} | 0.940 |
| not_found | {"absent_doc": 2, "described": 4, "not_found": 14} | 0.800 |
| counts | {"fact": 5, "plan": 3, "table": 32} | 1.000 |
| history | {"derived": 37, "described": 1, "plan": 2} | 1.000 |
| email_chat | {"derived": 40} | 1.000 |
| unanswerable | {"absent": 16, "absent_doc": 1, "described": 1, "not_found": 22, "plan": 2, "prose": 50} | – |
| mean over families | | **0.947** |

v16 minus the best other arm on each family (paired over the family's questions; 95% bootstrap interval):

| family | best other arm | questions | v16 - other | 95% interval |
|---|---|---|---|---|
| single | v17 | 179 | -0.045 | [-0.078, -0.017] |
| multi | v17 | 56 | 0.000 | [0.0, 0.0] |
| prose | v17 | 50 | 0.000 | [0.0, 0.0] |
| not_found | v17 | 20 | 0.000 | [0.0, 0.0] |
| counts | v17 | 40 | 0.000 | [0.0, 0.0] |
| history | v17 | 40 | 0.000 | [0.0, 0.0] |
| email_chat | v17 | 40 | 0.000 | [0.0, 0.0] |
| unanswerable | v17 | 92 | -0.011 | [-0.033, 0.0] |

By kind:

| kind | n | quotes | v17 | v16 | v1 | v2 | v17_seed1 |
|---|---|---|---|---|---|---|---|
| action_due | 7 | 0.000 | 0.571 | 0.571 | 1.000 | 1.000 | 0.571 |
| action_owner_issues | 5 | 0.000 | 0.400 | 0.400 | 0.000 | 0.000 | 0.400 |
| author_issues | 4 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| compare_two | 6 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| confluence_author | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| confluence_space | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| confluence_updated | 2 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| count1_confluence | 2 | 0.000 | 0.500 | 0.500 | 0.000 | 0.000 | 0.500 |
| count1_fireflies | 3 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| count1_github | 3 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| count1_gmail | 2 | 0.000 | 0.500 | 0.500 | 0.000 | 0.000 | 0.500 |
| count1_google_drive | 3 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| count1_hubspot | 3 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| count1_jira | 2 | 0.000 | 0.500 | 0.500 | 0.000 | 0.000 | 0.500 |
| count1_linear | 3 | 0.000 | 0.667 | 0.667 | 0.000 | 0.000 | 0.667 |
| count2_confluence | 2 | 0.000 | 0.500 | 0.500 | 0.000 | 0.000 | 0.500 |
| count2_fireflies | 2 | 0.500 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| count2_google_drive | 3 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| count2_hubspot | 3 | 0.000 | 0.667 | 0.667 | 0.000 | 0.000 | 0.667 |
| count2_jira | 2 | 0.000 | 0.500 | 0.500 | 0.000 | 0.000 | 0.500 |
| count2_linear | 2 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| count_gmail | 3 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| created_on | 5 | 0.000 | 1.000 | 1.000 | 0.400 | 0.400 | 1.000 |
| customer_tickets | 3 | 0.000 | 0.667 | 0.667 | 0.000 | 0.000 | 0.667 |
| descriptive | 90 | 0.144 | 0.878 | 0.789 | 0.811 | 0.756 | 0.878 |
| drive_owner | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| drive_status | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| email_account | 5 | 0.400 | 1.000 | 1.000 | 0.800 | 0.000 | 1.000 |
| email_attachments | 4 | 0.735 | 1.000 | 1.000 | 0.250 | 0.250 | 1.000 |
| email_cc | 4 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| email_count | 5 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| email_date | 5 | 0.000 | 1.000 | 1.000 | 0.400 | 0.800 | 1.000 |
| email_sender | 5 | 0.200 | 1.000 | 1.000 | 0.200 | 0.600 | 1.000 |
| email_to | 4 | 0.000 | 0.750 | 0.750 | 0.000 | 0.000 | 0.750 |
| embedded_confluence_space | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_confluence_updated | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_drive_created | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_drive_owner | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| embedded_drive_status | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_hubspot_close | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_hubspot_se | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_jira_customer | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| embedded_jira_priority | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_jira_reporter | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_jira_status | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| embedded_jira_ticket_assignee | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_linear_issue_assignee | 1 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| embedded_linear_issue_creator | 1 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| embedded_linear_issue_project | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| embedded_meeting_date | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 |
| embedded_meeting_owner | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_pr_author | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_pr_merged | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_pr_repo | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| field_absent | 20 | 0.000 | 0.850 | 0.800 | 0.000 | 0.000 | 0.850 |
| filter_list | 2 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| first_commenter | 5 | 0.000 | 0.800 | 0.800 | 0.000 | 0.000 | 0.800 |
| github_author | 2 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| heldout | 72 | 0.000 | 0.889 | 0.889 | 0.292 | 0.028 | 0.889 |
| hubspot_close | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| hubspot_first_activity | 6 | 0.167 | 1.000 | 1.000 | 0.000 | 0.167 | 1.000 |
| hubspot_owner | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| hubspot_se | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| hubspot_stage | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| issue_pr_author | 4 | 0.000 | 1.000 | 1.000 | 0.500 | 0.500 | 1.000 |
| jira_assignee | 2 | 0.000 | 1.000 | 1.000 | 0.500 | 1.000 | 1.000 |
| jira_customer | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| jira_priority | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| jira_reporter | 2 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| jira_sla | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| jira_status | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| jira_ticket_assignee | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| last_comment_date | 6 | 0.000 | 0.833 | 0.833 | 0.000 | 0.167 | 0.833 |
| last_updated | 6 | 0.000 | 1.000 | 1.000 | 0.333 | 0.500 | 1.000 |
| linear_assignee | 2 | 0.000 | 1.000 | 1.000 | 0.500 | 1.000 | 1.000 |
| linear_due | 8 | 0.000 | 1.000 | 1.000 | 1.000 | 0.875 | 1.000 |
| linear_due_window | 3 | 0.000 | 0.333 | 0.333 | 0.667 | 1.000 | 0.333 |
| linear_issue_assignee | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| linear_issue_creator | 1 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| linear_issue_priority | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| linear_issue_project | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| linear_issue_status | 2 | 0.000 | 1.000 | 1.000 | 0.500 | 0.000 | 1.000 |
| linear_project_members | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| linear_status | 3 | 0.000 | 0.963 | 0.963 | 0.267 | 0.830 | 0.963 |
| meeting_attendees | 3 | 0.302 | 1.000 | 1.000 | 0.600 | 0.250 | 1.000 |
| meeting_customer | 1 | 1.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| meeting_date | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 |
| meeting_owner | 1 | 1.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| moved_to_status | 6 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| nf_person | 5 | 0.000 | 1.000 | 1.000 | 0.800 | 1.000 | 1.000 |
| nf_pr | 5 | 0.000 | 1.000 | 1.000 | 0.600 | 0.000 | 1.000 |
| nf_ticket | 5 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| nf_title | 5 | 0.000 | 0.200 | 0.200 | 0.000 | 0.000 | 0.200 |
| owner_accounts | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| parent_issue | 4 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| person_count | 5 | 0.200 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| person_first | 5 | 0.000 | 1.000 | 1.000 | 0.000 | 0.200 | 1.000 |
| pr_author | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| pr_days_to_merge | 6 | 0.167 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| pr_issue | 4 | 0.250 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| pr_issue_creator | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| pr_issue_project | 3 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| pr_issue_team | 3 | 0.333 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| pr_merged | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| pr_repo | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| pr_reviewers | 4 | 0.243 | 1.000 | 1.000 | 1.000 | 0.500 | 1.000 |
| prose | 50 | 0.630 | 0.750 | 0.750 | 0.000 | 0.000 | 0.750 |
| reporter_issues | 4 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| slack_channel | 4 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 |
| slack_starter | 4 | 1.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |
| ticket_link | 3 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 |

Big folder minus the small one (/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad/brain3/test5ksmall_messy; not reproduced there, left out: 0):

| arm | questions | single | multi | prose | changed |
|---|---|---|---|---|---|
| quotes | 517 | 0.002 | 0.036 | -0.070 | 28 |
| v17 | 517 | -0.006 | 0.000 | 0.020 | 11 |
| v16 | 517 | -0.006 | 0.000 | 0.020 | 9 |
| v1 | 517 | 0.011 | -0.018 | 0.000 | 25 |
| v2 | 517 | 0.017 | 0.018 | 0.000 | 13 |

Rules: none applied (`--preregistered` applies them).

- best other arm per family: {"single": {"arm": "v17", "mean": 0.854}, "multi": {"arm": "v17", "mean": 0.839}, "prose": {"arm": "v17", "mean": 0.75}, "not_found": {"arm": "v17", "mean": 0.8}, "counts": {"arm": "v17", "mean": 0.825}, "history": {"arm": "v17", "mean": 0.95}, "email_chat": {"arm": "v17", "mean": 0.975}, "unanswerable": {"arm": "v17", "mean": 0.88}}
- the v16 brain's own answers, never another arm: ["v16", "v16_seed1"]
- hash-seed check (v16 under another hash seed, v16_seed1): null
- arms: {"quotes": {"arm": "quotes", "file": "quotes.jsonl", "single": null, "plans": null, "router": null, "seconds": 19.43, "answers": 517, "single_sha256": null, "plans_sha256": null, "router_sha256": null, "pythonhashseed": "0"}, "v17": {"arm": "v17", "file": "factbank_v17.jsonl", "single": "docs/benchmarks/brain2/lessons/single_lessons.json", "plans": "docs/benchmarks/brain2/lessons/plan_lessons.json", "router": "docs/benchmarks/brain2/lessons/router.json", "seconds": 410.94, "answers": 517, "single_sha256": "ee8b9d053405a47fc9cae32eff8a46cef2d742172ed6818a4aa967e5d7deb029", "plans_sha256": "4c2c8c6201be08ececdd8eb3db1d6d8f083bd06bdf038882466f06cc2712c3b7", "router_sha256": "20e9c05046406f147c3a06f99adc2363320c9d27fac0d1e4e7a386c344dfb10f", "pythonhashseed": "0"}, "v16": {"arm": "v16", "file": "factbank_v16.jsonl", "single": "docs/benchmarks/brain2/lessons/single_lessons.json", "plans": "docs/benchmarks/brain2/lessons/plan_lessons.json", "router": "docs/benchmarks/brain2/lessons/router.json", "seconds": 434.61, "answers": 517, "single_sha256": "ee8b9d053405a47fc9cae32eff8a46cef2d742172ed6818a4aa967e5d7deb029", "plans_sha256": "4c2c8c6201be08ececdd8eb3db1d6d8f083bd06bdf038882466f06cc2712c3b7", "router_sha256": "20e9c05046406f147c3a06f99adc2363320c9d27fac0d1e4e7a386c344dfb10f", "pythonhashseed": "0"}, "v1": {"arm": "v1", "file": "factbank.jsonl", "single": null, "plans": null, "router": null, "seconds": 425.9, "answers": 517, "single_sha256": null, "plans_sha256": null, "router_sha256": null, "pythonhashseed": "0"}, "v2": {"arm": "v2", "file": "factbank_v2.jsonl", "single": "/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad/fb50/lessons.json", "plans": null, "router": null, "seconds": 954.32, "answers": 517, "single_sha256": "afa4e7d9fee0a05c2a267c38e019513b653bfa5ce700c0eddfd17331c0ef7dd9", "plans_sha256": null, "router_sha256": null, "pythonhashseed": "0"}, "v17_seed1": {"arm": "v17", "file": "v17_seed1.jsonl", "single": "docs/benchmarks/brain2/lessons/single_lessons.json", "plans": "docs/benchmarks/brain2/lessons/plan_lessons.json", "router": "docs/benchmarks/brain2/lessons/router.json", "seconds": 405.93, "answers": 517, "single_sha256": "ee8b9d053405a47fc9cae32eff8a46cef2d742172ed6818a4aa967e5d7deb029", "plans_sha256": "4c2c8c6201be08ececdd8eb3db1d6d8f083bd06bdf038882466f06cc2712c3b7", "router_sha256": "20e9c05046406f147c3a06f99adc2363320c9d27fac0d1e4e7a386c344dfb10f", "pythonhashseed": "1"}}
- left out as stale: {}
- builds: {"factbank": {"sources": 5000, "entities": 14278, "facts": 97599, "bytes": 95346688, "check": {"ok": true, "errors": [], "facts": 97599, "stale": 97579, "contradictions": 0, "contradiction_examples": []}, "seconds": 7.48}, "factbank_v2": {"sources": 5000, "entities": 14278, "facts": 116153, "bytes": 103292928, "check": {"ok": true, "errors": [], "facts": 116153, "stale": 116131, "contradictions": 0, "contradiction_examples": []}, "seconds": 15.13}}
- draw: {"seed": 1010, "mix15": {"asked": {"deadlines": 15, "lists": 15, "fields": 30, "names": 10, "link": 15, "combine": 15, "compare": 6, "not_found": 20, "prose": 50, "descriptive": 90}, "given": {"deadlines": 15, "lists": 15, "fields": 30, "names": 10, "link": 15, "combine": 15, "compare": 6, "not_found": 20, "prose": 50, "descriptive": 90}}, "mix16": {"asked": {"counts": 40, "history": 40, "email_chat": 40, "pr_issue_project": 3, "pr_issue_creator": 3, "pr_issue_team": 3, "author_issues": 4, "reporter_issues": 4, "owner_accounts": 3, "field_absent": 20, "embedded": 20}, "given": {"counts": 40, "history": 40, "email_chat": 40, "pr_issue_project": 3, "pr_issue_creator": 3, "pr_issue_team": 3, "author_issues": 4, "reporter_issues": 4, "owner_accounts": 3, "field_absent": 20, "embedded": 20}}, "heldout": {"read": 72, "kept": 72, "set_aside": {}}, "set_aside_written": {"action_owner_issues": 9, "count1_confluence": 5, "count1_fireflies": 1, "count1_github": 3, "count1_gmail": 2, "count1_google_drive": 13, "count1_hubspot": 1, "count1_jira": 1, "count1_linear": 9, "count2_confluence": 2, "count2_fireflies": 5, "count2_google_drive": 21, "count2_hubspot": 72, "count2_jira": 9, "count2_linear": 91, "count_gmail": 28, "created_on": 24, "email_account": 399, "email_cc": 2, "email_to": 5, "embedded_confluence_author": 5, "embedded_confluence_space": 6, "embedded_confluence_updated": 6, "embedded_drive_created": 12, "embedded_drive_owner": 10, "embedded_drive_status": 21, "embedded_hubspot_close": 2, "embedded_hubspot_owner": 5, "embedded_hubspot_se": 4, "embedded_hubspot_stage": 4, "embedded_jira_customer": 3, "embedded_jira_priority": 3, "embedded_jira_reporter": 4, "embedded_jira_sla": 3, "embedded_jira_status": 3, "embedded_jira_ticket_assignee": 3, "embedded_linear_issue_assignee": 7, "embedded_linear_issue_creator": 4, "embedded_linear_issue_priority": 2, "embedded_linear_issue_project": 4, "embedded_linear_issue_status": 12, "embedded_meeting_customer": 64, "embedded_meeting_date": 6, "embedded_meeting_owner": 8, "embedded_pr_author": 9, "embedded_pr_merged": 6, "embedded_pr_repo": 6, "field_absent": 26, "last_updated": 71, "person_count": 7, "pr_issue_project": 4, "slack_channel": 82, "ticket_link": 2}, "gold_documents": 539}

### Round 3: v17 against v16

Round 3's rules are the ones below. The round-2 sections above (their rules, "own" labels and best-other pairing) are
not used in round 3: there v17 and v17_seed1 count as other arms.

| rule | met |
|---|---|
| 1 descriptive questions: v17 >= v16 + 0.1 | False |
| 2 single-document questions: v17 >= v16 + 0.03 | True |
| 3 no harm: on each of the other seven families, v17 >= v16 - 0.03 | True |
| 4 no answer in the haystack: v17 >= 0.7 on the unanswerable questions | True |
| 5 false 'not found': v17 says not found to at most 0.05 of the answerable questions | True |
| 6 not worse overall: v17's mean over the eight families >= v16's + 0.0 | True |
| 7 it holds at size: for each of single, multi and free text, v17 at 5,000 documents >= the small set - 0.05 | True |

v17 minus v16 (paired over the questions; 95% bootstrap interval; questions better and worse):

| family | questions | v17 - v16 | 95% interval | better | worse |
|---|---|---|---|---|---|
| single | 179 | 0.045 | (0.017, 0.078) | 8 | 0 |
| multi | 56 | 0.000 | (0.0, 0.0) | 0 | 0 |
| prose | 50 | 0.000 | (0.0, 0.0) | 0 | 0 |
| not_found | 20 | 0.000 | (0.0, 0.0) | 0 | 0 |
| counts | 40 | 0.000 | (0.0, 0.0) | 0 | 0 |
| history | 40 | 0.000 | (0.0, 0.0) | 0 | 0 |
| email_chat | 40 | 0.000 | (0.0, 0.0) | 0 | 0 |
| unanswerable | 92 | 0.011 | (0.0, 0.033) | 1 | 0 |
| descriptive | 90 | 0.089 | (0.033, 0.144) | 8 | 0 |
| all | 517 | 0.017 | (0.008, 0.029) | 9 | 0 |

Hash-seed check (v17 against v17_seed1): 0 of 517 answers differ.

### The company brain test, round 2 (v16)

443 questions (counts 40, email_chat 40, history 40, multi 56, not_found 20, prose 50, single 126, unanswerable 71; parts heldout 51, v15 212, v16 180) on $S/brain2/dev5k_q2.

| arm | single | multi | prose | not_found | counts | history | email_chat | unanswerable | mean of 8 | mean of v15's 4 | left out | not answered |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| quotes | 0.114 | 0.071 | 0.640 | 0.000 | 0.150 | 0.025 | 0.393 | 0.000 | 0.174 | 0.206 | 0 | 0 |
| v1 | 0.800 | 0.071 | 0.000 | 0.250 | 0.000 | 0.175 | 0.250 | 0.183 | 0.216 | 0.280 | 0 | 0 |
| v2 | 0.646 | 0.089 | 0.007 | 0.250 | 0.000 | 0.225 | 0.265 | 0.014 | 0.187 | 0.248 | 0 | 0 |
| v16 | 0.878 | 0.929 | 0.777 | 1.000 | 1.000 | 1.000 | 1.000 | 0.901 | 0.936 | 0.896 | 0 | 0 |
| v16_seed1 | 0.878 | 0.929 | 0.777 | 1.000 | 1.000 | 1.000 | 1.000 | 0.901 | 0.936 | 0.896 | 0 | 0 |
| v13 | 0.294 | 0.768 | 0.000 | 0.000 | 0.150 | 0.100 | 0.125 | 0.000 | 0.180 | 0.266 | 0 | 0 |
| v15 | 0.811 | 0.911 | 0.650 | 1.000 | 0.150 | 0.375 | 0.325 | 0.014 | 0.529 | 0.843 | 0 | 0 |

By group:

| arm | absent | chat | combine | compare | count | deadlines | descriptive | email | embedded | fields | filter | heldout | history | link | lists | names | not_found | prose |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| quotes | 0.000 | 1.000 | 0.038 | 0.000 | 0.158 | 0.000 | 0.111 | 0.217 | 0.150 | 0.200 | 0.000 | 0.000 | 0.025 | 0.125 | 0.000 | 0.137 | 0.000 | 0.640 |
| v1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.639 | 0.323 | 0.800 | 0.933 | 0.000 | 0.255 | 0.175 | 0.167 | 0.778 | 0.715 | 0.250 | 0.000 |
| v2 | 0.000 | 0.333 | 0.000 | 0.000 | 0.000 | 0.933 | 0.528 | 0.246 | 0.700 | 0.667 | 0.000 | 0.020 | 0.225 | 0.208 | 0.800 | 0.233 | 0.250 | 0.007 |
| v16 | 1.000 | 1.000 | 0.923 | 1.000 | 1.000 | 1.000 | 0.750 | 1.000 | 0.900 | 0.967 | 1.000 | 0.863 | 1.000 | 0.917 | 0.778 | 1.000 | 1.000 | 0.777 |
| v16_seed1 | 1.000 | 1.000 | 0.923 | 1.000 | 1.000 | 1.000 | 0.750 | 1.000 | 0.900 | 0.967 | 1.000 | 0.863 | 1.000 | 0.917 | 0.778 | 1.000 | 1.000 | 0.777 |
| v13 | 0.000 | 0.111 | 0.923 | 1.000 | 0.158 | 0.467 | 0.111 | 0.129 | 0.500 | 0.300 | 0.000 | 0.000 | 0.100 | 0.542 | 0.467 | 0.000 | 0.000 | 0.000 |
| v15 | 0.000 | 0.000 | 0.885 | 1.000 | 0.158 | 1.000 | 0.639 | 0.419 | 0.850 | 0.967 | 0.000 | 0.020 | 0.375 | 0.917 | 0.778 | 0.653 | 1.000 | 0.650 |

False "not found" on answerable questions, the strict free-text score (facts quoted from a gold document; – when the arm quotes nothing or the quoted documents are not known), free-text facts in the evidence, route accuracy (mean over families), time per question (ms) and the answers' length (characters):

| arm | false not found | strict prose | quoted | prose 2,000 | prose 6,000 | prose 24,000 | route accuracy | median ms | p90 ms | max ms | median chars |
|---|---|---|---|---|---|---|---|---|---|---|---|
| quotes | 0.000 | 0.630 | 50/50 | 0.677 | 0.903 | 0.970 | 0.143 | 26.6 | 47.0 | 77.7 | 1057 |
| v1 | 0.062 | – | 0/50 | 0.017 | 0.047 | 0.057 | – | 867.5 | 1329.3 | 2570.0 | 10 |
| v2 | 0.054 | – | 0/50 | 0.067 | 0.117 | 0.117 | – | 2060.5 | 2609.0 | 3226.1 | 10 |
| v16 | 0.009 | 0.777 | 49/50 | 0.737 | 0.960 | 0.970 | 0.994 | 956.7 | 1896.1 | 4514.4 | 10 |
| v16_seed1 | 0.009 | 0.777 | 49/50 | 0.737 | 0.960 | 0.970 | 0.994 | 964.8 | 1924.1 | 5665.8 | 10 |
| v13 | 0.000 | – | 0/50 | 0.067 | 0.117 | 0.127 | – | 4983.4 | 6813.2 | 12587.5 | 11 |
| v15 | 0.000 | – | 49/50 | 0.427 | 0.850 | 0.990 | 0.986 | 5049.5 | 6618.5 | 9992.5 | 11 |

Routes of quotes (right route: a fact route for single, multi, counts, history and email_chat; prose for free text; not found for not_found; unanswerable not counted):

| family | routes | right route |
|---|---|---|
| single | {"prose": 126} | 0.000 |
| multi | {"prose": 56} | 0.000 |
| prose | {"prose": 50} | 1.000 |
| not_found | {"prose": 20} | 0.000 |
| counts | {"prose": 40} | 0.000 |
| history | {"prose": 40} | 0.000 |
| email_chat | {"prose": 40} | 0.000 |
| unanswerable | {"prose": 71} | – |
| mean over families | | **0.143** |

Routes of v16 (right route: a fact route for single, multi, counts, history and email_chat; prose for free text; not found for not_found; unanswerable not counted):

| family | routes | right route |
|---|---|---|
| single | {"absent_doc": 3, "derived": 3, "fact": 50, "plan": 58, "table": 12} | 0.976 |
| multi | {"fact": 2, "plan": 51, "table": 3} | 1.000 |
| prose | {"fact": 1, "prose": 49} | 0.980 |
| not_found | {"not_found": 20} | 1.000 |
| counts | {"table": 40} | 1.000 |
| history | {"derived": 40} | 1.000 |
| email_chat | {"derived": 40} | 1.000 |
| unanswerable | {"absent": 20, "absent_doc": 2, "fact": 1, "not_found": 9, "plan": 1, "prose": 38} | – |
| mean over families | | **0.994** |

Routes of v16_seed1 (right route: a fact route for single, multi, counts, history and email_chat; prose for free text; not found for not_found; unanswerable not counted):

| family | routes | right route |
|---|---|---|
| single | {"absent_doc": 3, "derived": 3, "fact": 50, "plan": 58, "table": 12} | 0.976 |
| multi | {"fact": 2, "plan": 51, "table": 3} | 1.000 |
| prose | {"fact": 1, "prose": 49} | 0.980 |
| not_found | {"not_found": 20} | 1.000 |
| counts | {"table": 40} | 1.000 |
| history | {"derived": 40} | 1.000 |
| email_chat | {"derived": 40} | 1.000 |
| unanswerable | {"absent": 20, "absent_doc": 2, "fact": 1, "not_found": 9, "plan": 1, "prose": 38} | – |
| mean over families | | **0.994** |

Routes of v15 (right route: a fact route for single, multi, counts, history and email_chat; prose for free text; not found for not_found; unanswerable not counted):

| family | routes | right route |
|---|---|---|
| single | {"fact": 55, "plan": 71} | 1.000 |
| multi | {"fact": 2, "plan": 54} | 1.000 |
| prose | {"fact": 1, "prose": 49} | 0.980 |
| not_found | {"not_found": 20} | 1.000 |
| counts | {"fact": 22, "plan": 16, "prose": 2} | 0.950 |
| history | {"fact": 2, "plan": 37, "prose": 1} | 0.975 |
| email_chat | {"fact": 11, "plan": 29} | 1.000 |
| unanswerable | {"fact": 6, "not_found": 1, "plan": 18, "prose": 46} | – |
| mean over families | | **0.986** |

v16 minus the best other arm on each family (paired over the family's questions; 95% bootstrap interval):

| family | best other arm | questions | v16 - other | 95% interval |
|---|---|---|---|---|
| single | v15 | 126 | 0.067 | [0.028, 0.112] |
| multi | v15 | 56 | 0.018 | [0.0, 0.054] |
| prose | v15 | 50 | 0.127 | [0.027, 0.223] |
| not_found | v15 | 20 | 0.000 | [0.0, 0.0] |
| counts | quotes | 40 | 0.850 | [0.75, 0.95] |
| history | v15 | 40 | 0.625 | [0.475, 0.775] |
| email_chat | quotes | 40 | 0.607 | [0.454, 0.757] |
| unanswerable | v1 | 71 | 0.718 | [0.592, 0.831] |

By kind:

| kind | n | quotes | v1 | v2 | v16 | v16_seed1 | v13 | v15 |
|---|---|---|---|---|---|---|---|---|
| action_due | 7 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| action_owner_issues | 5 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| author_issues | 4 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| compare_two | 6 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| confluence_author | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| confluence_space | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| confluence_updated | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| count1_confluence | 3 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| count1_fireflies | 3 | 0.333 | 0.000 | 0.000 | 1.000 | 1.000 | 0.667 | 0.667 |
| count1_gmail | 2 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| count1_google_drive | 3 | 0.333 | 0.000 | 0.000 | 1.000 | 1.000 | 0.333 | 0.667 |
| count1_hubspot | 2 | 0.500 | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| count1_jira | 3 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| count1_linear | 3 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.333 | 0.000 |
| count2_confluence | 3 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| count2_fireflies | 3 | 0.333 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| count2_google_drive | 3 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| count2_hubspot | 2 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| count2_jira | 3 | 0.333 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| count2_linear | 2 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| count_gmail | 3 | 0.333 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| created_on | 6 | 0.167 | 0.833 | 0.500 | 1.000 | 1.000 | 0.167 | 0.667 |
| customer_tickets | 2 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| descriptive | 36 | 0.111 | 0.639 | 0.528 | 0.750 | 0.750 | 0.111 | 0.639 |
| drive_created | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| drive_owner | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| drive_status | 1 | 0.000 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| email_account | 5 | 0.600 | 0.800 | 0.000 | 1.000 | 1.000 | 0.200 | 0.800 |
| email_attachments | 4 | 0.678 | 1.000 | 0.488 | 1.000 | 1.000 | 0.000 | 0.250 |
| email_cc | 4 | 0.000 | 0.000 | 0.167 | 1.000 | 1.000 | 0.000 | 0.000 |
| email_count | 4 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.750 | 0.250 |
| email_date | 4 | 0.250 | 0.500 | 1.000 | 1.000 | 1.000 | 0.000 | 0.500 |
| email_sender | 5 | 0.000 | 0.000 | 0.200 | 1.000 | 1.000 | 0.000 | 0.200 |
| email_to | 5 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 | 0.800 |
| embedded_confluence_author | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_confluence_space | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_drive_created | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| embedded_drive_status | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_hubspot_close | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| embedded_hubspot_owner | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| embedded_hubspot_se | 1 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| embedded_hubspot_stage | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| embedded_jira_priority | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| embedded_jira_reporter | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| embedded_jira_sla | 1 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_jira_status | 1 | 0.000 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_jira_ticket_assignee | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_linear_issue_assignee | 1 | 0.000 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_linear_issue_project | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| embedded_linear_issue_status | 1 | 0.000 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_meeting_customer | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| embedded_meeting_date | 1 | 1.000 | 0.000 | 1.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| embedded_pr_author | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_pr_merged | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| field_absent | 20 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| filter_list | 2 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| first_commenter | 5 | 0.000 | 0.000 | 0.200 | 1.000 | 1.000 | 0.000 | 0.000 |
| github_author | 2 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| heldout | 51 | 0.000 | 0.255 | 0.020 | 0.863 | 0.863 | 0.000 | 0.020 |
| hubspot_close | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| hubspot_first_activity | 6 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| hubspot_owner | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| hubspot_se | 1 | 0.000 | 1.000 | 0.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| hubspot_stage | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| issue_pr_author | 4 | 0.250 | 0.250 | 0.500 | 1.000 | 1.000 | 1.000 | 1.000 |
| jira_assignee | 2 | 0.000 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 |
| jira_customer | 2 | 0.500 | 1.000 | 0.500 | 1.000 | 1.000 | 0.000 | 1.000 |
| jira_priority | 1 | 0.000 | 1.000 | 0.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| jira_reporter | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| jira_sla | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| jira_status | 1 | 0.000 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| jira_ticket_assignee | 2 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| last_comment_date | 6 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 | 0.333 |
| last_updated | 6 | 0.000 | 0.333 | 0.667 | 1.000 | 1.000 | 0.333 | 1.000 |
| linear_assignee | 3 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| linear_due | 8 | 0.000 | 1.000 | 0.875 | 1.000 | 1.000 | 0.875 | 1.000 |
| linear_due_window | 3 | 0.000 | 0.889 | 1.000 | 0.889 | 0.889 | 0.000 | 0.889 |
| linear_issue_assignee | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| linear_issue_creator | 1 | 0.000 | 1.000 | 0.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| linear_issue_priority | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| linear_issue_project | 1 | 0.000 | 1.000 | 0.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| linear_issue_status | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| linear_project_members | 3 | 0.000 | 0.445 | 0.445 | 1.000 | 1.000 | 0.000 | 0.445 |
| linear_status | 3 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| meeting_attendees | 3 | 0.331 | 0.605 | 0.000 | 1.000 | 1.000 | 0.000 | 0.400 |
| meeting_customer | 2 | 1.000 | 1.000 | 0.500 | 1.000 | 1.000 | 0.000 | 1.000 |
| meeting_date | 1 | 1.000 | 0.000 | 1.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| meeting_owner | 1 | 0.000 | 1.000 | 0.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| moved_to_status | 5 | 0.000 | 0.000 | 0.200 | 1.000 | 1.000 | 0.000 | 0.400 |
| nf_person | 5 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| nf_pr | 5 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| nf_ticket | 5 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| nf_title | 5 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| owner_accounts | 3 | 0.000 | 0.000 | 0.000 | 0.333 | 0.333 | 0.333 | 0.000 |
| parent_issue | 4 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.500 | 1.000 |
| person_count | 5 | 0.200 | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| person_first | 5 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| pr_author | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| pr_days_to_merge | 6 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.167 | 0.167 |
| pr_issue | 4 | 0.000 | 0.250 | 0.250 | 1.000 | 1.000 | 1.000 | 1.000 |
| pr_issue_creator | 3 | 0.000 | 0.000 | 0.000 | 0.333 | 0.333 | 0.000 | 0.333 |
| pr_issue_project | 3 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| pr_issue_team | 3 | 0.667 | 0.667 | 0.667 | 1.000 | 1.000 | 0.000 | 1.000 |
| pr_merged | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| pr_repo | 1 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| pr_reviewers | 4 | 0.094 | 1.000 | 0.250 | 1.000 | 1.000 | 0.000 | 1.000 |
| prose | 50 | 0.640 | 0.000 | 0.007 | 0.777 | 0.777 | 0.000 | 0.650 |
| reporter_issues | 4 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| slack_channel | 4 | 1.000 | 0.000 | 0.500 | 1.000 | 1.000 | 0.000 | 0.000 |
| slack_starter | 5 | 1.000 | 0.000 | 0.200 | 1.000 | 1.000 | 0.200 | 0.000 |
| ticket_link | 3 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 |

Big folder minus the small one ($S/brain2/dev5k_q2_small; not reproduced there, left out: 0):

| arm | questions | single | multi | prose | changed |
|---|---|---|---|---|---|
| quotes | 443 | -0.035 | 0.017 | -0.020 | 20 |
| v1 | 443 | 0.002 | 0.017 | 0.000 | 8 |
| v2 | 443 | 0.039 | 0.018 | 0.000 | 12 |
| v16 | 443 | 0.000 | 0.018 | -0.003 | 16 |
| v13 | 443 | -0.002 | 0.018 | 0.000 | 10 |
| v15 | 443 | -0.012 | 0.000 | 0.017 | 14 |

Rules:
- 1 single-document questions: v16 >= the best other arm - 0.03: **met**
- 2 multi-document questions: v16 >= the best other arm - 0.03: **met**
- 3 free text: v16 >= the best other arm - 0.0: **met**
- 4 not found: v16 >= 0.8 on questions about nothing in the bank: **met**
- 5 no answer in the haystack: v16 >= 0.7 on the unanswerable questions: **met**
- 6 false 'not found': v16 says not found to at most 0.05 of the answerable questions: **met**
- 7 counts: v16 >= 0.7 and >= the best other arm + 0.2: **met**
- 8 history: v16 >= 0.7 and >= the best other arm + 0.2: **met**
- 9 email_chat: v16 >= 0.7 and >= the best other arm + 0.2: **met**
- 10 one brain for every kind: v16's mean over the eight families >= every other arm's + 0.2: **met**
- 11 the right route: v16's route accuracy, mean over families, >= 0.9: **met**
- 12 it holds at size: for each of single, multi and free text, v16 at 5,000 documents >= the small set - 0.05: **met**

- best other arm per family: {"single": {"arm": "v15", "mean": 0.811}, "multi": {"arm": "v15", "mean": 0.911}, "prose": {"arm": "v15", "mean": 0.65}, "not_found": {"arm": "v15", "mean": 1.0}, "counts": {"arm": "quotes", "mean": 0.15}, "history": {"arm": "v15", "mean": 0.375}, "email_chat": {"arm": "quotes", "mean": 0.393}, "unanswerable": {"arm": "v1", "mean": 0.183}}
- the v16 brain's own answers, never another arm: ["v16", "v16_seed1"]
- hash-seed check (v16 under another hash seed, v16_seed1): {"questions": 443, "different": []}
- arms: {"quotes": {"arm": "quotes", "file": "quotes.jsonl", "single": null, "plans": null, "router": null, "seconds": 18.87, "answers": 443, "single_sha256": null, "plans_sha256": null, "router_sha256": null, "pythonhashseed": "0"}, "v1": {"arm": "v1", "file": "factbank.jsonl", "single": null, "plans": null, "router": null, "seconds": 441.9, "answers": 443, "single_sha256": null, "plans_sha256": null, "router_sha256": null, "pythonhashseed": "0"}, "v2": {"arm": "v2", "file": "factbank_v2.jsonl", "single": "$S/fb50/lessons.json", "plans": null, "router": null, "seconds": 960.23, "answers": 443, "single_sha256": "afa4e7d9fee0a05c2a267c38e019513b653bfa5ce700c0eddfd17331c0ef7dd9", "plans_sha256": null, "router_sha256": null, "pythonhashseed": "0"}, "v16": {"arm": "v16", "file": "factbank_v16.jsonl", "single": "docs/benchmarks/brain2/lessons/single_lessons.json", "plans": "docs/benchmarks/brain2/lessons/plan_lessons.json", "router": "docs/benchmarks/brain2/lessons/router.json", "seconds": 384.4, "answers": 443, "single_sha256": "ee8b9d053405a47fc9cae32eff8a46cef2d742172ed6818a4aa967e5d7deb029", "plans_sha256": "4c2c8c6201be08ececdd8eb3db1d6d8f083bd06bdf038882466f06cc2712c3b7", "router_sha256": "20e9c05046406f147c3a06f99adc2363320c9d27fac0d1e4e7a386c344dfb10f", "pythonhashseed": "0"}, "v16_seed1": {"arm": "v16", "file": "v16_seed1.jsonl", "single": "docs/benchmarks/brain2/lessons/single_lessons.json", "plans": "docs/benchmarks/brain2/lessons/plan_lessons.json", "router": "docs/benchmarks/brain2/lessons/router.json", "seconds": 394.13, "answers": 443, "single_sha256": "ee8b9d053405a47fc9cae32eff8a46cef2d742172ed6818a4aa967e5d7deb029", "plans_sha256": "4c2c8c6201be08ececdd8eb3db1d6d8f083bd06bdf038882466f06cc2712c3b7", "router_sha256": "20e9c05046406f147c3a06f99adc2363320c9d27fac0d1e4e7a386c344dfb10f", "pythonhashseed": "1"}, "v13": {"arm": "v13", "file": "factbank_v13.jsonl", "single": "$S/fb50/lessons.json", "plans": "$S/mdtrain/plan_lessons_v13.json", "router": null, "seconds": 2330.5, "answers": 443, "single_sha256": "afa4e7d9fee0a05c2a267c38e019513b653bfa5ce700c0eddfd17331c0ef7dd9", "plans_sha256": "64cf5b302a826b2e7a8af5a4f39842afd746032416ea5d1f12ca1db28037d9be", "router_sha256": null, "pythonhashseed": "0"}, "v15": {"arm": "v15", "file": "factbank_v15.jsonl", "single": "docs/benchmarks/brain/lessons/single_lessons.json", "plans": "docs/benchmarks/brain/lessons/plan_lessons.json", "router": "docs/benchmarks/brain/lessons/router.json", "seconds": 2215.44, "answers": 443, "single_sha256": "ee8b9d053405a47fc9cae32eff8a46cef2d742172ed6818a4aa967e5d7deb029", "plans_sha256": "de756122b9f027be0e44131faa7b7fdca284c877b31b3e38e7c34a8ce7591e6a", "router_sha256": "20e9c05046406f147c3a06f99adc2363320c9d27fac0d1e4e7a386c344dfb10f", "pythonhashseed": "0"}}
- left out as stale: {}
- builds: {"factbank": {"sources": 5000, "entities": 14340, "facts": 97777, "bytes": 95211520, "check": {"ok": true, "errors": [], "facts": 97777, "stale": 97762, "contradictions": 0, "contradiction_examples": []}, "seconds": 6.99}, "factbank_v2": {"sources": 5000, "entities": 14340, "facts": 115949, "bytes": 102993920, "check": {"ok": true, "errors": [], "facts": 115949, "stale": 115927, "contradictions": 0, "contradiction_examples": []}, "seconds": 12.41}}
- draw: {"seed": 721, "mix15": {"asked": {"deadlines": 15, "lists": 15, "fields": 30, "names": 10, "link": 15, "combine": 15, "compare": 6, "not_found": 20, "prose": 50, "descriptive": 40}, "given": {"deadlines": 15, "lists": 15, "fields": 30, "names": 10, "link": 15, "combine": 15, "compare": 6, "not_found": 20, "prose": 50, "descriptive": 36}}, "mix16": {"asked": {"counts": 40, "history": 40, "email_chat": 40, "pr_issue_project": 3, "pr_issue_creator": 3, "pr_issue_team": 3, "author_issues": 4, "reporter_issues": 4, "owner_accounts": 3, "field_absent": 20, "embedded": 20}, "given": {"counts": 40, "history": 40, "email_chat": 40, "pr_issue_project": 3, "pr_issue_creator": 3, "pr_issue_team": 3, "author_issues": 4, "reporter_issues": 4, "owner_accounts": 3, "field_absent": 20, "embedded": 20}}, "heldout": {"read": 51, "kept": 51, "set_aside": {}}, "set_aside_written": {"action_owner_issues": 2, "count1_confluence": 2, "count1_fireflies": 1, "count1_github": 5, "count1_gmail": 1, "count1_google_drive": 15, "count1_linear": 4, "count2_confluence": 1, "count2_fireflies": 4, "count2_google_drive": 37, "count2_hubspot": 66, "count2_jira": 12, "count2_linear": 82, "count_gmail": 26, "created_on": 29, "email_account": 437, "email_cc": 1, "email_sender": 1, "email_to": 6, "embedded_confluence_author": 3, "embedded_confluence_space": 3, "embedded_confluence_updated": 3, "embedded_drive_created": 6, "embedded_drive_owner": 7, "embedded_drive_status": 30, "embedded_hubspot_close": 2, "embedded_hubspot_owner": 3, "embedded_hubspot_se": 2, "embedded_hubspot_stage": 2, "embedded_jira_customer": 3, "embedded_jira_priority": 1, "embedded_jira_reporter": 2, "embedded_jira_sla": 2, "embedded_jira_status": 1, "embedded_jira_ticket_assignee": 3, "embedded_linear_issue_assignee": 8, "embedded_linear_issue_creator": 2, "embedded_linear_issue_priority": 2, "embedded_linear_issue_project": 2, "embedded_linear_issue_status": 9, "embedded_meeting_customer": 62, "embedded_meeting_date": 7, "embedded_meeting_owner": 4, "embedded_pr_author": 6, "embedded_pr_merged": 2, "embedded_pr_repo": 1, "field_absent": 26, "last_updated": 85, "person_count": 6, "pr_issue_project": 1, "slack_channel": 96, "slack_starter": 1, "ticket_link": 3}, "gold_documents": 477}

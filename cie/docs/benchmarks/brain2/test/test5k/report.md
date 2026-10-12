### The company brain test, round 2 (v16)

579 questions (counts 40, email_chat 40, history 40, multi 56, not_found 20, prose 150, single 130, unanswerable 103; parts heldout 83, v15 316, v16 180) on /tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad/brain2/test5k.

| arm | single | multi | prose | not_found | counts | history | email_chat | unanswerable | mean of 8 | mean of v15's 4 | left out | not answered |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| quotes | 0.116 | 0.018 | 0.646 | 0.000 | 0.025 | 0.025 | 0.357 | 0.000 | 0.148 | 0.195 | 0 | 0 |
| v1 | 0.741 | 0.054 | 0.002 | 0.250 | 0.000 | 0.175 | 0.300 | 0.184 | 0.213 | 0.262 | 0 | 0 |
| v2 | 0.674 | 0.071 | 0.006 | 0.250 | 0.000 | 0.225 | 0.242 | 0.029 | 0.187 | 0.250 | 0 | 0 |
| v16 | 0.794 | 0.893 | 0.666 | 1.000 | 1.000 | 1.000 | 1.000 | 0.883 | 0.904 | 0.838 | 0 | 0 |
| v15 | 0.774 | 0.893 | 0.581 | 1.000 | 0.150 | 0.250 | 0.300 | 0.243 | 0.524 | 0.812 | 0 | 0 |
| v13 | 0.308 | 0.750 | 0.000 | 0.000 | 0.075 | 0.000 | 0.200 | 0.000 | 0.167 | 0.265 | 0 | 0 |

By group:

| arm | absent | chat | combine | compare | count | deadlines | descriptive | email | embedded | fields | filter | heldout | history | link | lists | names | not_found | prose |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| quotes | 0.000 | 1.000 | 0.000 | 0.167 | 0.027 | 0.000 | 0.125 | 0.196 | 0.150 | 0.200 | 0.000 | 0.000 | 0.025 | 0.000 | 0.000 | 0.114 | 0.000 | 0.646 |
| v1 | 0.000 | 0.250 | 0.000 | 0.000 | 0.000 | 1.000 | 0.725 | 0.312 | 0.650 | 0.733 | 0.000 | 0.229 | 0.175 | 0.125 | 0.800 | 0.533 | 0.250 | 0.002 |
| v2 | 0.000 | 0.250 | 0.000 | 0.000 | 0.000 | 1.000 | 0.750 | 0.240 | 0.550 | 0.600 | 0.000 | 0.036 | 0.225 | 0.167 | 0.800 | 0.162 | 0.250 | 0.006 |
| v16 | 1.000 | 1.000 | 0.885 | 1.000 | 1.000 | 1.000 | 0.500 | 1.000 | 0.900 | 0.933 | 1.000 | 0.855 | 1.000 | 0.875 | 1.000 | 0.718 | 1.000 | 0.666 |
| v15 | 0.000 | 0.250 | 0.885 | 1.000 | 0.162 | 1.000 | 0.600 | 0.312 | 0.900 | 0.900 | 0.000 | 0.301 | 0.250 | 0.875 | 0.800 | 0.467 | 1.000 | 0.581 |
| v13 | 0.000 | 0.375 | 0.923 | 1.000 | 0.081 | 0.467 | 0.225 | 0.156 | 0.300 | 0.400 | 0.000 | 0.000 | 0.000 | 0.500 | 0.400 | 0.000 | 0.000 | 0.000 |

False "not found" on answerable questions, the strict free-text score (facts quoted from a gold document; – when the arm quotes nothing or the quoted documents are not known), free-text facts in the evidence, route accuracy (mean over families), time per question (ms) and the answers' length (characters):

| arm | false not found | strict prose | quoted | prose 2,000 | prose 6,000 | prose 24,000 | route accuracy | median ms | p90 ms | max ms | median chars |
|---|---|---|---|---|---|---|---|---|---|---|---|
| quotes | 0.000 | 0.633 | 150/150 | 0.712 | 0.957 | 1.000 | 0.143 | 25.4 | 39.7 | 81.0 | 1055 |
| v1 | 0.101 | – | 0/150 | 0.023 | 0.078 | 0.110 | – | 752.2 | 1141.5 | 1696.3 | 10 |
| v2 | 0.053 | – | 0/150 | 0.108 | 0.151 | 0.188 | – | 1841.2 | 2354.5 | 2970.6 | 10 |
| v16 | 0.026 | 0.666 | 143/150 | 0.724 | 0.927 | 0.956 | 0.984 | 819.0 | 1494.2 | 5603.9 | 10 |
| v15 | 0.000 | – | 145/150 | 0.553 | 0.812 | 0.972 | 0.979 | 4671.4 | 6040.0 | 12118.1 | 13 |
| v13 | 0.000 | – | 0/150 | 0.101 | 0.148 | 0.203 | – | 4412.4 | 5919.1 | 11469.8 | 11 |

Routes of quotes (right route: a fact route for single, multi, counts, history and email_chat; prose for free text; not found for not_found; unanswerable not counted):

| family | routes | right route |
|---|---|---|
| single | {"prose": 130} | 0.000 |
| multi | {"prose": 56} | 0.000 |
| prose | {"prose": 150} | 1.000 |
| not_found | {"prose": 20} | 0.000 |
| counts | {"prose": 40} | 0.000 |
| history | {"prose": 40} | 0.000 |
| email_chat | {"prose": 40} | 0.000 |
| unanswerable | {"prose": 103} | – |
| mean over families | | **0.143** |

Routes of v16 (right route: a fact route for single, multi, counts, history and email_chat; prose for free text; not found for not_found; unanswerable not counted):

| family | routes | right route |
|---|---|---|
| single | {"absent_doc": 5, "derived": 4, "fact": 39, "plan": 65, "prose": 3, "table": 14} | 0.938 |
| multi | {"fact": 2, "plan": 52, "table": 2} | 1.000 |
| prose | {"absent_doc": 4, "fact": 3, "prose": 143} | 0.953 |
| not_found | {"not_found": 20} | 1.000 |
| counts | {"table": 40} | 1.000 |
| history | {"derived": 40} | 1.000 |
| email_chat | {"derived": 40} | 1.000 |
| unanswerable | {"absent": 20, "absent_doc": 2, "fact": 1, "not_found": 34, "plan": 1, "prose": 45} | – |
| mean over families | | **0.984** |

Routes of v15 (right route: a fact route for single, multi, counts, history and email_chat; prose for free text; not found for not_found; unanswerable not counted):

| family | routes | right route |
|---|---|---|
| single | {"fact": 44, "plan": 81, "prose": 5} | 0.962 |
| multi | {"fact": 2, "plan": 54} | 1.000 |
| prose | {"fact": 5, "prose": 145} | 0.967 |
| not_found | {"not_found": 20} | 1.000 |
| counts | {"fact": 22, "plan": 17, "prose": 1} | 0.975 |
| history | {"fact": 3, "plan": 35, "prose": 2} | 0.950 |
| email_chat | {"fact": 10, "plan": 30} | 1.000 |
| unanswerable | {"fact": 4, "not_found": 25, "plan": 18, "prose": 56} | – |
| mean over families | | **0.979** |

v16 minus the best other arm on each family (paired over the family's questions; 95% bootstrap interval):

| family | best other arm | questions | v16 - other | 95% interval |
|---|---|---|---|---|
| single | v15 | 130 | 0.019 | [-0.029, 0.072] |
| multi | v15 | 56 | 0.000 | [0.0, 0.0] |
| prose | quotes | 150 | 0.020 | [-0.052, 0.089] |
| not_found | v15 | 20 | 0.000 | [0.0, 0.0] |
| counts | v15 | 40 | 0.850 | [0.725, 0.95] |
| history | v15 | 40 | 0.750 | [0.625, 0.875] |
| email_chat | quotes | 40 | 0.643 | [0.493, 0.782] |
| unanswerable | v15 | 103 | 0.641 | [0.544, 0.738] |

By kind:

| kind | n | quotes | v1 | v2 | v16 | v15 | v13 |
|---|---|---|---|---|---|---|---|
| action_due | 7 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| action_owner_issues | 5 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 |
| author_issues | 4 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 |
| compare_two | 6 | 0.167 | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 |
| confluence_author | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| confluence_space | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| confluence_updated | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| count1_confluence | 3 | 0.000 | 0.000 | 0.000 | 1.000 | 0.333 | 0.333 |
| count1_fireflies | 2 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| count1_github | 2 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 0.000 |
| count1_gmail | 2 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 0.000 |
| count1_google_drive | 2 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.500 |
| count1_hubspot | 2 | 0.000 | 0.000 | 0.000 | 1.000 | 0.500 | 0.500 |
| count1_jira | 3 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 0.000 |
| count1_linear | 3 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 0.000 |
| count2_confluence | 2 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 0.000 |
| count2_fireflies | 2 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 0.000 |
| count2_google_drive | 3 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 0.000 |
| count2_hubspot | 2 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 0.000 |
| count2_jira | 3 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 0.000 |
| count2_linear | 3 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 0.000 |
| count_gmail | 3 | 0.333 | 0.000 | 0.000 | 1.000 | 0.000 | 0.000 |
| created_on | 6 | 0.000 | 0.500 | 0.167 | 1.000 | 0.333 | 0.000 |
| customer_tickets | 3 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 0.000 |
| descriptive | 40 | 0.125 | 0.725 | 0.750 | 0.500 | 0.600 | 0.225 |
| drive_created | 2 | 0.000 | 0.500 | 1.000 | 1.000 | 1.000 | 0.000 |
| drive_owner | 1 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 |
| drive_status | 1 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 |
| email_account | 5 | 0.400 | 0.800 | 0.000 | 1.000 | 0.800 | 0.000 |
| email_attachments | 4 | 0.794 | 0.500 | 0.250 | 1.000 | 0.250 | 0.000 |
| email_cc | 4 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 0.000 |
| email_count | 5 | 0.000 | 0.000 | 0.000 | 1.000 | 0.200 | 0.600 |
| email_date | 5 | 0.200 | 0.600 | 1.000 | 1.000 | 0.600 | 0.400 |
| email_sender | 4 | 0.000 | 0.000 | 0.250 | 1.000 | 0.000 | 0.000 |
| email_to | 5 | 0.019 | 0.200 | 0.133 | 1.000 | 0.200 | 0.000 |
| embedded_confluence_space | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| embedded_drive_created | 1 | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| embedded_drive_owner | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| embedded_drive_status | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_hubspot_close | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_hubspot_stage | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| embedded_jira_customer | 1 | 0.000 | 1.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| embedded_jira_priority | 1 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| embedded_jira_reporter | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| embedded_jira_sla | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| embedded_jira_status | 1 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 |
| embedded_jira_ticket_assignee | 1 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 |
| embedded_linear_issue_assignee | 1 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| embedded_linear_issue_priority | 1 | 0.000 | 1.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| embedded_linear_issue_project | 1 | 0.000 | 1.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| embedded_meeting_date | 1 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| embedded_meeting_owner | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| embedded_pr_author | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_pr_merged | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embedded_pr_repo | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| field_absent | 20 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 0.000 |
| filter_list | 3 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 0.000 |
| first_commenter | 6 | 0.000 | 0.333 | 0.500 | 1.000 | 0.333 | 0.000 |
| github_author | 3 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| heldout | 83 | 0.000 | 0.229 | 0.036 | 0.855 | 0.301 | 0.000 |
| hubspot_close | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| hubspot_first_activity | 6 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 0.000 |
| hubspot_owner | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| hubspot_se | 1 | 0.000 | 1.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| hubspot_stage | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| issue_pr_author | 4 | 0.000 | 0.000 | 0.500 | 1.000 | 1.000 | 1.000 |
| jira_assignee | 2 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| jira_customer | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| jira_priority | 1 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| jira_reporter | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| jira_sla | 1 | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| jira_status | 1 | 0.000 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 |
| jira_ticket_assignee | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| last_comment_date | 6 | 0.167 | 0.000 | 0.000 | 1.000 | 0.167 | 0.000 |
| last_updated | 5 | 0.000 | 0.400 | 0.600 | 1.000 | 0.800 | 0.000 |
| linear_assignee | 2 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| linear_due | 8 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.875 |
| linear_due_window | 3 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| linear_issue_assignee | 1 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 |
| linear_issue_creator | 2 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| linear_issue_priority | 1 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| linear_issue_project | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| linear_issue_status | 1 | 0.000 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 |
| linear_project_members | 3 | 0.000 | 0.222 | 0.000 | 0.667 | 0.222 | 0.000 |
| linear_status | 2 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| meeting_attendees | 3 | 0.161 | 0.222 | 0.206 | 0.394 | 0.000 | 0.000 |
| meeting_customer | 1 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| meeting_date | 1 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| meeting_owner | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| moved_to_status | 5 | 0.000 | 0.000 | 0.400 | 1.000 | 0.200 | 0.000 |
| nf_person | 5 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| nf_pr | 5 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| nf_ticket | 5 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| nf_title | 5 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| owner_accounts | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.667 |
| parent_issue | 3 | 0.000 | 0.333 | 0.333 | 1.000 | 1.000 | 0.333 |
| person_count | 5 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 |
| person_first | 5 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 |
| pr_author | 2 | 0.000 | 1.000 | 0.500 | 1.000 | 1.000 | 1.000 |
| pr_days_to_merge | 6 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 0.000 |
| pr_issue | 4 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.750 |
| pr_issue_creator | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| pr_issue_project | 3 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.000 |
| pr_issue_team | 3 | 0.000 | 0.667 | 0.333 | 1.000 | 1.000 | 0.000 |
| pr_merged | 1 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| pr_repo | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| pr_reviewers | 4 | 0.163 | 1.000 | 0.250 | 1.000 | 1.000 | 0.000 |
| prose | 150 | 0.646 | 0.002 | 0.006 | 0.666 | 0.581 | 0.000 |
| reporter_issues | 4 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.750 |
| slack_channel | 4 | 1.000 | 0.500 | 0.500 | 1.000 | 0.500 | 0.250 |
| slack_starter | 4 | 1.000 | 0.000 | 0.000 | 1.000 | 0.000 | 0.500 |
| ticket_link | 4 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 |

Big folder minus the small one (/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad/brain2/test5ksmall; not reproduced there, left out: 0):

| arm | questions | single | multi | prose | changed |
|---|---|---|---|---|---|
| quotes | 579 | -0.017 | -0.018 | -0.014 | 36 |
| v1 | 579 | 0.023 | -0.017 | -0.002 | 24 |
| v2 | 579 | 0.046 | 0.017 | -0.002 | 13 |
| v16 | 579 | -0.023 | 0.000 | 0.009 | 20 |
| v15 | 579 | -0.005 | 0.000 | -0.010 | 38 |
| v13 | 579 | 0.000 | 0.018 | 0.000 | 13 |

Rules: none applied (`--preregistered` applies them).

- best other arm per family: {"single": {"arm": "v15", "mean": 0.774}, "multi": {"arm": "v15", "mean": 0.893}, "prose": {"arm": "quotes", "mean": 0.646}, "not_found": {"arm": "v15", "mean": 1.0}, "counts": {"arm": "v15", "mean": 0.15}, "history": {"arm": "v15", "mean": 0.25}, "email_chat": {"arm": "quotes", "mean": 0.357}, "unanswerable": {"arm": "v15", "mean": 0.243}}
- the v16 brain's own answers, never another arm: ["v16", "v16_seed1"]
- hash-seed check (v16 under another hash seed, v16_seed1): null
- arms: {"quotes": {"arm": "quotes", "file": "quotes.jsonl", "single": null, "plans": null, "router": null, "seconds": 20.4, "answers": 579, "single_sha256": null, "plans_sha256": null, "router_sha256": null, "pythonhashseed": "0"}, "v1": {"arm": "v1", "file": "factbank.jsonl", "single": null, "plans": null, "router": null, "seconds": 493.17, "answers": 579, "single_sha256": null, "plans_sha256": null, "router_sha256": null, "pythonhashseed": "0"}, "v2": {"arm": "v2", "file": "factbank_v2.jsonl", "single": "/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad/fb50/lessons.json", "plans": null, "router": null, "seconds": 1124.48, "answers": 579, "single_sha256": "afa4e7d9fee0a05c2a267c38e019513b653bfa5ce700c0eddfd17331c0ef7dd9", "plans_sha256": null, "router_sha256": null, "pythonhashseed": "0"}, "v16": {"arm": "v16", "file": "factbank_v16.jsonl", "single": "docs/benchmarks/brain2/lessons/single_lessons.json", "plans": "docs/benchmarks/brain2/lessons/plan_lessons.json", "router": "docs/benchmarks/brain2/lessons/router.json", "seconds": 434.57, "answers": 579, "single_sha256": "ee8b9d053405a47fc9cae32eff8a46cef2d742172ed6818a4aa967e5d7deb029", "plans_sha256": "4c2c8c6201be08ececdd8eb3db1d6d8f083bd06bdf038882466f06cc2712c3b7", "router_sha256": "20e9c05046406f147c3a06f99adc2363320c9d27fac0d1e4e7a386c344dfb10f", "pythonhashseed": "0"}, "v15": {"arm": "v15", "file": "factbank_v15.jsonl", "single": "docs/benchmarks/brain/lessons/single_lessons.json", "plans": "docs/benchmarks/brain/lessons/plan_lessons.json", "router": "docs/benchmarks/brain/lessons/router.json", "seconds": 2603.33, "answers": 579, "single_sha256": "ee8b9d053405a47fc9cae32eff8a46cef2d742172ed6818a4aa967e5d7deb029", "plans_sha256": "de756122b9f027be0e44131faa7b7fdca284c877b31b3e38e7c34a8ce7591e6a", "router_sha256": "20e9c05046406f147c3a06f99adc2363320c9d27fac0d1e4e7a386c344dfb10f", "pythonhashseed": "0"}, "v13": {"arm": "v13", "file": "factbank_v13.jsonl", "single": "/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad/fb50/lessons.json", "plans": "/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad/mdtrain/plan_lessons_v13.json", "router": null, "seconds": 2719.62, "answers": 579, "single_sha256": "afa4e7d9fee0a05c2a267c38e019513b653bfa5ce700c0eddfd17331c0ef7dd9", "plans_sha256": "64cf5b302a826b2e7a8af5a4f39842afd746032416ea5d1f12ca1db28037d9be", "router_sha256": null, "pythonhashseed": "0"}}
- left out as stale: {}
- builds: {"factbank": {"sources": 5000, "entities": 14249, "facts": 97581, "bytes": 95727616, "check": {"ok": true, "errors": [], "facts": 97581, "stale": 97571, "contradictions": 0, "contradiction_examples": []}, "seconds": 7.46}, "factbank_v2": {"sources": 5000, "entities": 14249, "facts": 116313, "bytes": 103878656, "check": {"ok": true, "errors": [], "facts": 116313, "stale": 116297, "contradictions": 0, "contradiction_examples": []}, "seconds": 14.56}}
- draw: {"seed": 910, "mix15": {"asked": {"deadlines": 15, "lists": 15, "fields": 30, "names": 10, "link": 15, "combine": 15, "compare": 6, "not_found": 20, "prose": 150, "descriptive": 40}, "given": {"deadlines": 15, "lists": 15, "fields": 30, "names": 10, "link": 15, "combine": 15, "compare": 6, "not_found": 20, "prose": 150, "descriptive": 40}}, "mix16": {"asked": {"counts": 40, "history": 40, "email_chat": 40, "pr_issue_project": 3, "pr_issue_creator": 3, "pr_issue_team": 3, "author_issues": 4, "reporter_issues": 4, "owner_accounts": 3, "field_absent": 20, "embedded": 20}, "given": {"counts": 40, "history": 40, "email_chat": 40, "pr_issue_project": 3, "pr_issue_creator": 3, "pr_issue_team": 3, "author_issues": 4, "reporter_issues": 4, "owner_accounts": 3, "field_absent": 20, "embedded": 20}}, "heldout": {"read": 83, "kept": 83, "set_aside": {}}, "set_aside_written": {"action_owner_issues": 5, "count1_confluence": 3, "count1_fireflies": 1, "count1_github": 4, "count1_gmail": 2, "count1_google_drive": 16, "count1_linear": 6, "count2_confluence": 3, "count2_fireflies": 5, "count2_google_drive": 42, "count2_hubspot": 62, "count2_jira": 6, "count2_linear": 73, "count_gmail": 34, "created_on": 31, "email_account": 425, "email_count": 1, "email_sender": 1, "email_to": 4, "embedded_confluence_author": 3, "embedded_confluence_space": 2, "embedded_confluence_updated": 2, "embedded_drive_created": 8, "embedded_drive_owner": 4, "embedded_drive_status": 22, "embedded_hubspot_close": 3, "embedded_hubspot_owner": 3, "embedded_hubspot_se": 2, "embedded_hubspot_stage": 2, "embedded_jira_customer": 2, "embedded_jira_priority": 2, "embedded_jira_reporter": 2, "embedded_jira_sla": 2, "embedded_jira_status": 2, "embedded_jira_ticket_assignee": 2, "embedded_linear_issue_assignee": 8, "embedded_linear_issue_creator": 3, "embedded_linear_issue_priority": 2, "embedded_linear_issue_project": 2, "embedded_linear_issue_status": 8, "embedded_meeting_customer": 66, "embedded_meeting_date": 2, "embedded_meeting_owner": 5, "embedded_pr_author": 8, "embedded_pr_merged": 3, "embedded_pr_repo": 3, "field_absent": 33, "last_updated": 77, "person_count": 6, "pr_issue_project": 2, "slack_channel": 68, "ticket_link": 1}, "gold_documents": 550}

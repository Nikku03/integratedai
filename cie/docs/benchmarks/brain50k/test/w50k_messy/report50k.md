# The company brain at 50,000 documents: report

## The plan's rules (messy set)

| rule | met |
|---|---|
| 1 size: v18 at 50,000 documents >= v18 at 5,000 - 0.05 (mean over the eight families of the paired difference) | met |
| 2 the reasoner's mean of the eight families >= v18's + 0.03 | met |
| 3 free text: the reasoner >= v18 + 0.1 | met |
| 4 complex questions: the reasoner >= v18 + 0.2 | met |
| 5 no harm where the brain is exact: not found, counts and unanswerable, the reasoner each >= v18 - 0.05 | met |
| 6 the reasoner's false 'not found' on answerable questions <= 0.05 | met |
| 7 the reasoner's mean of the eight families >= plain search with the same model + 0.05 | met |
| 8 complex questions: the reasoner >= plain search with the same model + 0.1 | met |

How the model arms ran (messy set; cut: replies cut off at the token limit; gave_up: conversations that kept the brain's answer; too_long: of them, out of room in the model's window; no_reply: rag answers with nothing visible):

| arm | model | effort | asked | seconds | output_tokens | tool_calls | cut | cut_turns | retried | gave_up | too_long | no_reply |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| rag | Qwen/Qwen3.8-27B@1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0 | medium | 635 | 1376.300 | 289815 |  | 0 |  | 0 |  |  | 0 |
| reasoner | Qwen/Qwen3.8-27B@1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0 | medium | 635 | 1556.300 | 337914 | 1424 |  | 0 |  | 0 | 0 |  |

## The messy set (635 questions)

| arm | single | multi | prose | not_found | counts | history | email_chat | unanswerable | complex | mean of 8 | false not found | answered |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| reasoner | 0.960 | 1.000 | 0.812 | 0.973 | 0.982 | 0.975 | 1.000 | 0.960 | 0.929 | 0.958 | 0.016 | 635 |
| rag | 0.858 | 0.323 | 0.702 | 1.000 | 0.073 | 0.500 | 0.937 | 0.950 | 0.190 | 0.668 | 0.277 | 635 |
| v18 | 0.803 | 0.903 | 0.625 | 0.973 | 0.947 | 0.950 | 0.950 | 0.870 | 0.167 | 0.878 | 0.032 | 635 |
| v18_5k | 0.876 | 0.903 | 0.681 | 1.000 | 1.000 | 0.950 | 0.950 | 0.870 |  | 0.904 | 0.035 | 454 |
| v18 on v18_5k's questions | 0.803 | 0.903 | 0.625 | 0.973 | 1.000 | 0.950 | 0.950 | 0.870 |  | | | 454 |

v18_5k is round 4's v18 at 5,000 documents, scored on round 4's questions not counted again here; the row below it is v18 at 50,000 on those same questions, which rule 1 compares (paired, below).

Paired differences (mean, 95% interval, better / worse):

| | single | multi | prose | not_found | counts | history | email_chat | unanswerable | complex | all |
|---|---|---|---|---|---|---|---|---|---|---|
| reasoner - rag | 0.102 [0.041, 0.165] 16/2 | 0.677 [0.484, 0.839] 21/0 | 0.110 [0.056, 0.171] 14/0 | -0.027 [-0.081, 0.0] 0/1 | 0.909 [0.825, 0.976] 52/0 | 0.475 [0.3, 0.625] 20/1 | 0.063 [0.005, 0.138] 4/0 | 0.010 [-0.04, 0.06] 4/3 | 0.738 [0.651, 0.817] 94/1 | 0.329 [0.291, 0.368] 225/8 |
| reasoner - v18 | 0.156 [0.089, 0.221] 21/1 | 0.097 [0.0, 0.194] 3/0 | 0.188 [0.067, 0.312] 28/12 | 0.000 [-0.081, 0.081] 1/1 | 0.035 [-0.035, 0.105] 3/1 | 0.025 [-0.05, 0.125] 2/1 | 0.050 [0.0, 0.125] 2/0 | 0.090 [0.02, 0.17] 12/3 | 0.762 [0.683, 0.833] 96/0 | 0.232 [0.197, 0.269] 168/19 |
| reasoner - v18_5k | 0.084 [0.024, 0.145] 14/3 | 0.097 [0.0, 0.194] 3/0 | 0.131 [0.019, 0.246] 24/12 | -0.027 [-0.081, 0.0] 0/1 | 0.000 [0.0, 0.0] 0/0 | 0.025 [-0.05, 0.125] 2/1 | 0.050 [0.0, 0.125] 2/0 | 0.090 [0.01, 0.17] 13/4 |  | 0.077 [0.043, 0.112] 58/21 |
| rag - v18 | 0.055 [-0.032, 0.14] 18/11 | -0.581 [-0.742, -0.419] 0/18 | 0.077 [-0.048, 0.215] 26/19 | 0.027 [0.0, 0.081] 1/0 | -0.874 [-0.962, -0.769] 1/51 | -0.450 [-0.6, -0.3] 0/18 | -0.013 [-0.113, 0.095] 2/4 | 0.080 [0.01, 0.15] 11/3 | 0.024 [-0.079, 0.127] 24/21 | -0.097 [-0.141, -0.053] 83/145 |
| rag - v18_5k | -0.018 [-0.095, 0.059] 13/14 | -0.581 [-0.742, -0.419] 0/18 | 0.021 [-0.106, 0.152] 23/21 | 0.000 [0.0, 0.0] 0/0 | -0.500 [-1.0, 0.0] 0/1 | -0.450 [-0.6, -0.3] 0/18 | -0.013 [-0.113, 0.095] 2/4 | 0.080 [0.0, 0.16] 12/4 |  | -0.066 [-0.109, -0.021] 50/80 |
| v18 - v18_5k | -0.073 [-0.137, -0.008] 5/14 | 0.000 [0.0, 0.0] 0/0 | -0.056 [-0.106, -0.013] 0/5 | -0.027 [-0.081, 0.0] 0/1 | 0.000 [0.0, 0.0] 0/0 | 0.000 [0.0, 0.0] 0/0 | 0.000 [0.0, 0.0] 0/0 | 0.000 [-0.07, 0.07] 6/6 |  | -0.032 [-0.058, -0.007] 11/26 |

Complex questions by kind:

| arm | assignee_open_p | compare_due_assignee | creator_jira_load | email_account_owner | meeting_account_owner | meeting_account_stage | owner_meetings | pr_assignee_load | project_first_due |
|---|---|---|---|---|---|---|---|---|---|
| reasoner | 1.000 | 1.000 | 1.000 | 0.750 | 1.000 | 1.000 | 1.000 | 0.875 | 0.812 |
| rag | 0.000 | 0.875 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.625 |
| v18 | 0.062 | 0.000 | 0.938 | 0.125 | 0.000 | 0.429 | 0.000 | 0.000 | 0.000 |

## The tidy set (635 questions)

| arm | single | multi | prose | not_found | counts | history | email_chat | unanswerable | complex | mean of 8 | false not found | answered |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| reasoner | 0.952 | 0.968 | 0.804 | 1.000 | 0.982 | 1.000 | 1.000 | 0.970 | 0.952 | 0.960 | 0.018 | 635 |
| rag | 0.863 | 0.323 | 0.702 | 1.000 | 0.091 | 0.475 | 0.962 | 0.950 | 0.190 | 0.671 | 0.263 | 635 |
| v18 | 0.855 | 0.935 | 0.625 | 1.000 | 0.982 | 1.000 | 1.000 | 0.910 | 0.167 | 0.913 | 0.030 | 635 |

Paired differences (mean, 95% interval, better / worse):

| | single | multi | prose | not_found | counts | history | email_chat | unanswerable | complex | all |
|---|---|---|---|---|---|---|---|---|---|---|
| reasoner - rag | 0.089 [0.032, 0.145] 12/1 | 0.645 [0.452, 0.806] 21/1 | 0.102 [0.021, 0.183] 16/5 | 0.000 [0.0, 0.0] 0/0 | 0.892 [0.804, 0.965] 51/0 | 0.525 [0.35, 0.675] 21/0 | 0.038 [0.008, 0.075] 5/0 | 0.020 [-0.03, 0.07] 4/2 | 0.762 [0.675, 0.841] 97/1 | 0.332 [0.294, 0.37] 227/10 |
| reasoner - v18 | 0.097 [0.04, 0.153] 13/1 | 0.032 [-0.065, 0.129] 2/1 | 0.179 [0.06, 0.296] 28/12 | 0.000 [0.0, 0.0] 0/0 | 0.000 [-0.053, 0.053] 1/1 | 0.000 [0.0, 0.0] 0/0 | 0.000 [0.0, 0.0] 0/0 | 0.060 [0.0, 0.12] 8/2 | 0.786 [0.714, 0.857] 99/0 | 0.208 [0.175, 0.243] 151/17 |
| rag - v18 | 0.008 [-0.065, 0.081] 11/10 | -0.613 [-0.774, -0.452] 0/19 | 0.077 [-0.05, 0.217] 26/20 | 0.000 [0.0, 0.0] 0/0 | -0.892 [-0.962, -0.804] 0/51 | -0.525 [-0.675, -0.35] 0/21 | -0.038 [-0.075, -0.008] 0/5 | 0.040 [-0.02, 0.1] 7/3 | 0.024 [-0.079, 0.127] 24/21 | -0.123 [-0.164, -0.081] 68/150 |

Complex questions by kind:

| arm | assignee_open_p | compare_due_assignee | creator_jira_load | email_account_owner | meeting_account_owner | meeting_account_stage | owner_meetings | pr_assignee_load | project_first_due |
|---|---|---|---|---|---|---|---|---|---|
| reasoner | 1.000 | 1.000 | 1.000 | 0.750 | 1.000 | 1.000 | 1.000 | 1.000 | 0.875 |
| rag | 0.000 | 0.875 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.625 |
| v18 | 0.062 | 0.000 | 0.938 | 0.125 | 0.000 | 0.429 | 0.000 | 0.000 | 0.000 |


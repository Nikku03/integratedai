### Part B: the fact bank against the memory bank at 5,089 documents

**primary questions, small set** (50 questions: owners 26, deadlines 18, lists 6)

| arm | budget | owners | deadlines | lists | mean |
|---|---|---|---|---|---|
| plain-words | 2,000 | 0.962 | 1.000 | 0.128 | 0.697 |
| plain-words | 6,000 | 1.000 | 1.000 | 0.723 | 0.908 |
| plain-words | 24,000 | 1.000 | 1.000 | 1.000 | 1.000 |
| plain | 2,000 | 0.923 | 1.000 | 0.333 | 0.752 |
| plain | 6,000 | 0.962 | 1.000 | 0.609 | 0.857 |
| plain | 24,000 | 1.000 | 1.000 | 0.911 | 0.970 |
| bank | 2,000 | 0.615 | 0.333 | 0.134 | 0.361 |
| bank | 6,000 | 0.692 | 0.444 | 0.250 | 0.462 |
| bank | 24,000 | 0.769 | 0.500 | 0.718 | 0.662 |
| v1 | 2,000 | 0.923 | 0.889 | 0.356 | 0.723 |
| v1 | 6,000 | 1.000 | 1.000 | 0.674 | 0.891 |
| v1 | 24,000 | 1.000 | 1.000 | 0.872 | 0.957 |
| v2 | 2,000 | 0.962 | 1.000 | 1.000 | 0.987 |
| v2 | 6,000 | 1.000 | 1.000 | 1.000 | 1.000 |
| v2 | 24,000 | 1.000 | 1.000 | 1.000 | 1.000 |
| own answers, v1 | | 0.654 | 0.944 | 1.000 | 0.866 |
| own answers, v2 | | 0.538 | 0.778 | 1.000 | 0.772 |

time per question (ms): {"plain-words": {"median": 0.8, "p90": 1.2, "max": 2.9}, "plain": {"median": 17.1, "p90": 26.3, "max": 35.5}, "bank": {"median": 228.9, "p90": 340.6, "max": 440.3}, "v1": {"median": 9.7, "p90": 13.6, "max": 21.8}, "v2": {"median": 109.1, "p90": 137.2, "max": 168.5}}
load and build times (s): {"bank_load": 131.8, "bank_embed": 127.0, "bank_finish": 1.8, "bank_bm25": 0.2, "plain_bm25": 0.6, "plain_embed": 54.2, "v1_build": 0.72, "v2_build": 0.81}
storage: {"bank_total": 4437405, "bank_bytes": {"documents": 88488, "sections": 1286936, "memory_records": 2402940, "record_links": 153560, "section_facts": 0, "bm25": 505481}, "plain_total": 1359466, "v1_bytes": 2404352, "v2_bytes": 2641920}
checks: {"bank_errors": 0, "evidence_missing": 0, "gave_up": 0, "gave_up_questions": [], "bm25_ready": true, "load_average": [1.78, 2.65, 3.47], "retry": {"retried": [], "still_affected": []}, "bank_documents": 67, "bank_failed": 0, "bank_bm25_error": null, "haystack_documents": 67, "fact_bank_sources": {"v1": 67, "v2": 67}}

**primary questions, 5,089 documents** (50 questions: owners 26, deadlines 18, lists 6)

| arm | budget | owners | deadlines | lists | mean |
|---|---|---|---|---|---|
| plain-words | 2,000 | 0.808 | 1.000 | 0.000 | 0.603 |
| plain-words | 6,000 | 0.885 | 1.000 | 0.000 | 0.628 |
| plain-words | 24,000 | 0.962 | 1.000 | 0.128 | 0.697 |
| plain | 2,000 | 0.654 | 1.000 | 0.024 | 0.559 |
| plain | 6,000 | 0.885 | 1.000 | 0.048 | 0.644 |
| plain | 24,000 | 0.962 | 1.000 | 0.113 | 0.692 |
| bank | 2,000 | 0.423 | 0.333 | 0.000 | 0.252 |
| bank | 6,000 | 0.500 | 0.500 | 0.042 | 0.347 |
| bank | 24,000 | 0.692 | 0.500 | 0.125 | 0.439 |
| v1 | 2,000 | 0.346 | 0.278 | 0.000 | 0.208 |
| v1 | 6,000 | 0.692 | 0.611 | 0.000 | 0.434 |
| v1 | 24,000 | 0.923 | 0.889 | 0.083 | 0.632 |
| v2 | 2,000 | 0.923 | 1.000 | 1.000 | 0.974 |
| v2 | 6,000 | 0.962 | 1.000 | 1.000 | 0.987 |
| v2 | 24,000 | 1.000 | 1.000 | 1.000 | 1.000 |
| own answers, v1 | | 0.615 | 0.944 | 0.989 | 0.849 |
| own answers, v2 | | 0.577 | 0.833 | 1.000 | 0.803 |

time per question (ms): {"plain-words": {"median": 1.8, "p90": 2.6, "max": 3.7}, "plain": {"median": 22.7, "p90": 33.7, "max": 52.1}, "bank": {"median": 462.5, "p90": 771.8, "max": 943.2}, "v1": {"median": 778.4, "p90": 1200.1, "max": 1379.0}, "v2": {"median": 1883.3, "p90": 2065.8, "max": 2343.2}}
load and build times (s): {"bank_load": 385.8, "bank_embed": 180.2, "bank_finish": 17.6, "bank_bm25": 8.4, "plain_bm25": 4.1, "plain_embed": 3298.1, "v1_build": 8.36, "v2_build": 13.73}
storage: {"bank_total": 183697907, "bank_bytes": {"documents": 5420030, "sections": 69027764, "memory_records": 87292935, "record_links": 6143368, "section_facts": 0, "bm25": 15813810}, "plain_total": 68021155, "v1_bytes": 106016768, "v2_bytes": 115056640}
checks: {"bank_errors": 0, "evidence_missing": 0, "gave_up": 2, "gave_up_questions": ["metadata-qst_0047", "metadata-qst_0063"], "bm25_ready": true, "load_average": [1.42, 3.11, 3.72], "retry": {"retried": ["metadata-qst_0047", "metadata-qst_0063"], "still_affected": ["metadata-qst_0047", "metadata-qst_0063"]}, "bank_documents": 5089, "bank_failed": 0, "bank_bm25_error": null, "haystack_documents": 5089, "fact_bank_sources": {"v1": 5089, "v2": 5089}}

**the first test's questions, 50 documents** (50 questions: owners 26, deadlines 18, lists 6)

| arm | budget | owners | deadlines | lists | mean |
|---|---|---|---|---|---|
| plain-words | 2,000 | 0.885 | 1.000 | 0.583 | 0.823 |
| plain-words | 6,000 | 1.000 | 1.000 | 0.917 | 0.972 |
| plain-words | 24,000 | 1.000 | 1.000 | 1.000 | 1.000 |
| plain | 2,000 | 0.885 | 1.000 | 0.167 | 0.684 |
| plain | 6,000 | 0.962 | 1.000 | 0.333 | 0.765 |
| plain | 24,000 | 1.000 | 1.000 | 1.000 | 1.000 |
| bank | 2,000 | 0.654 | 0.389 | 0.083 | 0.375 |
| bank | 6,000 | 0.769 | 0.389 | 0.083 | 0.414 |
| bank | 24,000 | 0.808 | 0.500 | 0.583 | 0.630 |
| v1 | 2,000 | 0.885 | 1.000 | 0.417 | 0.767 |
| v1 | 6,000 | 0.885 | 1.000 | 1.000 | 0.962 |
| v1 | 24,000 | 0.962 | 1.000 | 1.000 | 0.987 |
| v2 | 2,000 | 1.000 | 1.000 | 1.000 | 1.000 |
| v2 | 6,000 | 1.000 | 1.000 | 1.000 | 1.000 |
| v2 | 24,000 | 1.000 | 1.000 | 1.000 | 1.000 |
| own answers, v1 | | 0.654 | 1.000 | 1.000 | 0.885 |
| own answers, v2 | | 0.500 | 0.889 | 1.000 | 0.796 |

time per question (ms): {"plain-words": {"median": 0.9, "p90": 1.2, "max": 1.4}, "plain": {"median": 16.9, "p90": 29.1, "max": 43.7}, "bank": {"median": 246.9, "p90": 315.7, "max": 395.2}, "v1": {"median": 9.5, "p90": 13.3, "max": 27.5}, "v2": {"median": 112.6, "p90": 147.0, "max": 169.4}}
load and build times (s): {"bank_load": 12.6, "bank_embed": 0.0, "bank_finish": 10.6, "bank_bm25": 0.2, "plain_bm25": 0.4, "plain_embed": 28.6, "v1_build": 0.79, "v2_build": 0.86}
storage: {"bank_total": 3045210, "bank_bytes": {"documents": 64849, "sections": 951652, "memory_records": 1549124, "record_links": 103152, "section_facts": 0, "bm25": 376433}, "plain_total": 1068217, "v1_bytes": 1814528, "v2_bytes": 1949696}
checks: {"bank_errors": 0, "evidence_missing": 0, "gave_up": 0, "gave_up_questions": [], "bm25_ready": true, "load_average": [1.25, 1.95, 2.45], "retry": {"retried": [], "still_affected": []}, "bank_documents": 50, "bank_failed": 0, "bank_bm25_error": null, "haystack_documents": 50, "fact_bank_sources": {"v1": 50, "v2": 50}}

**the first test's questions, 5,089 documents** (50 questions: owners 26, deadlines 18, lists 6)

| arm | budget | owners | deadlines | lists | mean |
|---|---|---|---|---|---|
| plain-words | 2,000 | 0.692 | 1.000 | 0.000 | 0.564 |
| plain-words | 6,000 | 0.885 | 1.000 | 0.000 | 0.628 |
| plain-words | 24,000 | 0.962 | 1.000 | 0.167 | 0.710 |
| plain | 2,000 | 0.769 | 1.000 | 0.000 | 0.590 |
| plain | 6,000 | 0.846 | 1.000 | 0.000 | 0.615 |
| plain | 24,000 | 0.923 | 1.000 | 0.083 | 0.669 |
| bank | 2,000 | 0.500 | 0.389 | 0.000 | 0.296 |
| bank | 6,000 | 0.577 | 0.444 | 0.083 | 0.368 |
| bank | 24,000 | 0.731 | 0.444 | 0.083 | 0.419 |
| v1 | 2,000 | 0.346 | 0.333 | 0.000 | 0.226 |
| v1 | 6,000 | 0.538 | 0.667 | 0.000 | 0.402 |
| v1 | 24,000 | 0.846 | 0.889 | 0.500 | 0.745 |
| v2 | 2,000 | 0.962 | 1.000 | 1.000 | 0.987 |
| v2 | 6,000 | 0.962 | 1.000 | 1.000 | 0.987 |
| v2 | 24,000 | 0.962 | 1.000 | 1.000 | 0.987 |
| own answers, v1 | | 0.538 | 1.000 | 1.000 | 0.846 |
| own answers, v2 | | 0.423 | 0.889 | 1.000 | 0.771 |

time per question (ms): {"plain-words": {"median": 1.8, "p90": 2.4, "max": 3.2}, "plain": {"median": 22.5, "p90": 28.4, "max": 40.3}, "bank": {"median": 445.9, "p90": 610.0, "max": 837.2}, "v1": {"median": 822.7, "p90": 1098.0, "max": 1296.9}, "v2": {"median": 1802.6, "p90": 2037.7, "max": 2156.9}}
load and build times (s): {"bank_load": 385.8, "bank_embed": 180.2, "bank_finish": 17.6, "bank_bm25": 8.4, "plain_bm25": 4.1, "plain_embed": 3298.1, "v1_build": 8.36, "v2_build": 13.73}
storage: {"bank_total": 183697907, "bank_bytes": {"documents": 5420030, "sections": 69027764, "memory_records": 87292935, "record_links": 6143368, "section_facts": 0, "bm25": 15813810}, "plain_total": 68021155, "v1_bytes": 106016768, "v2_bytes": 115056640}
checks: {"bank_errors": 0, "evidence_missing": 0, "gave_up": 0, "gave_up_questions": [], "bm25_ready": true, "load_average": [2.05, 2.92, 3.61], "retry": {"retried": [], "still_affected": []}, "bank_documents": 5089, "bank_failed": 0, "bank_bm25_error": null, "haystack_documents": 5089, "fact_bank_sources": {"v1": 5089, "v2": 5089}}

Rules (fact bank v1, primary questions, 5,089 documents):
- 1 not worse at the evidence budget (fact bank - bank >= -0.03 in every group, 24,000 chars): **not met**
- 2 better near the top (fact bank - bank >= +0.10 on the mean, first 2,000 chars): **not met**
- 3 answers without a model (own answers >= 0.70 on the mean): **met**
- 4 smaller (fact bank <= 1/3 of the bank's storage): **not met**
- 5 own answers hold at size (5,089 documents >= control - 0.05): **met**
- replace (rules 1, 2 and 4): **not met**

- v2 on the same rules: {"1 not worse at the evidence budget (fact bank - bank >= -0.03 in every group, 24,000 chars)": true, "2 better near the top (fact bank - bank >= +0.10 on the mean, first 2,000 chars)": true, "3 answers without a model (own answers >= 0.70 on the mean)": true, "4 smaller (fact bank <= 1/3 of the bank's storage)": false, "5 own answers hold at size (5,089 documents >= control - 0.05)": true}
- the first test's questions at 5,089: {"1 not worse at the evidence budget (fact bank - bank >= -0.03 in every group, 24,000 chars)": true, "2 better near the top (fact bank - bank >= +0.10 on the mean, first 2,000 chars)": false, "3 answers without a model (own answers >= 0.70 on the mean)": true, "4 smaller (fact bank <= 1/3 of the bank's storage)": false, "5 own answers hold at size (5,089 documents >= control - 0.05)": true}
- fact bank minus plain-words: {"2000": -0.395, "6000": -0.194, "24000": -0.065}
- bank evidence collected twice: {"b5k": {"questions": 50, "different": []}, "b5ksmall": {"questions": 50, "different": []}, "b5kfb": {"questions": 50, "different": []}, "b5kfb50": {"questions": 50, "different": []}}
- the control against the original run: {"plain-words": [], "plain": [], "bank": ["action_due-018", "linear_due-005", "metadata-qst_0027", "metadata-qst_0069", "metadata-qst_0079"]}
- still cut short after the retry: {"b5k": ["metadata-qst_0047", "metadata-qst_0063"], "b5ksmall": [], "b5kfb": [], "b5kfb50": []}
- the rules without those questions: {"1 not worse at the evidence budget (fact bank - bank >= -0.03 in every group, 24,000 chars)": false, "2 better near the top (fact bank - bank >= +0.10 on the mean, first 2,000 chars)": false, "3 answers without a model (own answers >= 0.70 on the mean)": true, "4 smaller (fact bank <= 1/3 of the bank's storage)": false, "5 own answers hold at size (5,089 documents >= control - 0.05)": true}

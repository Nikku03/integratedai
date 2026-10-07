### Fact bank vs memory bank: 50 questions (owners 26, deadlines 18, lists 6), 50 documents

Answer within the evidence (owners, deadlines: share; lists: share of the keys):

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
| factbank | 2,000 | 0.885 | 1.000 | 0.417 | 0.767 |
| factbank | 6,000 | 0.885 | 1.000 | 1.000 | 0.962 |
| factbank | 24,000 | 0.962 | 1.000 | 1.000 | 0.987 |

Answers from the fact bank alone, no model (owners, deadlines: share correct; lists: mean F1): owners 0.654, deadlines 1.0, lists 1.0, mean 0.885

Search time p50 (ms): {'plain-words': 0.6, 'plain': 10.6, 'bank': 149.89999999999998, 'factbank': 5.38}
Storage (bytes): {'bank_bytes': 3038881, 'plain_bytes': 1068217, 'factbank_bytes': 1814528}
Fact bank: 1969 facts, 380 entities, built in 0.48 s; checker ok: True, contradictions 0, stale 1956

Rules:
- 1 not worse at the evidence budget (factbank - bank >= -0.03 in every group, 24,000 chars): **met**
- 2 better near the top (factbank - bank >= +0.10 on the mean, first 2,000 chars): **met**
- 3 answers without a model (direct >= 0.70 on the mean): **met**
- 4 smaller (factbank <= 1/3 of the bank's storage): **not met**

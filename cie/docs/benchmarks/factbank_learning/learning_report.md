### Fact bank: trained (v2) against untrained (v1), on held-out documents

**training** (50 questions: owners 26, deadlines 18, lists 6)

| | owners | deadlines | lists | mean |
|---|---|---|---|---|
| own answers, v1 | 0.654 | 1.000 | 1.000 | 0.885 |
| own answers, v2 | 0.500 | 0.889 | 1.000 | 0.796 |
| within 2,000 chars, bank | 0.654 | 0.389 | 0.083 | 0.375 |
| within 24,000 chars, bank | 0.808 | 0.500 | 0.583 | 0.630 |
| within 2,000 chars, plain | 0.885 | 1.000 | 0.167 | 0.684 |
| within 24,000 chars, plain | 1.000 | 1.000 | 1.000 | 1.000 |
| within 2,000 chars, plain-words | 0.885 | 1.000 | 0.583 | 0.823 |
| within 24,000 chars, plain-words | 1.000 | 1.000 | 1.000 | 1.000 |
| within 2,000 chars, v1 | 0.885 | 1.000 | 0.417 | 0.767 |
| within 24,000 chars, v1 | 0.962 | 1.000 | 1.000 | 0.987 |
| within 2,000 chars, v2 | 1.000 | 1.000 | 1.000 | 1.000 |
| within 24,000 chars, v2 | 1.000 | 1.000 | 1.000 | 1.000 |

**held-out** (46 questions: owners 22, deadlines 20, lists 4)

| | owners | deadlines | lists | mean |
|---|---|---|---|---|
| own answers, v1 | 0.591 | 0.850 | 0.292 | 0.578 |
| own answers, v2 | 0.500 | 0.200 | 1.000 | 0.567 |
| within 2,000 chars, bank | 0.591 | 0.500 | 0.125 | 0.405 |
| within 24,000 chars, bank | 0.909 | 0.550 | 0.250 | 0.570 |
| within 2,000 chars, plain | 0.909 | 1.000 | 0.125 | 0.678 |
| within 24,000 chars, plain | 1.000 | 1.000 | 0.833 | 0.944 |
| within 2,000 chars, plain-words | 0.955 | 1.000 | 0.625 | 0.860 |
| within 24,000 chars, plain-words | 1.000 | 1.000 | 1.000 | 1.000 |
| within 2,000 chars, v1 | 0.909 | 0.800 | 0.458 | 0.722 |
| within 24,000 chars, v1 | 0.955 | 1.000 | 1.000 | 0.985 |
| within 2,000 chars, v2 | 0.909 | 0.750 | 1.000 | 0.886 |
| within 24,000 chars, v2 | 1.000 | 1.000 | 1.000 | 1.000 |

**changed** (46 questions: owners 22, deadlines 20, lists 4)

| | owners | deadlines | lists | mean |
|---|---|---|---|---|
| own answers, v1 | 0.591 | 0.850 | 0.292 | 0.578 |
| own answers, v2 | 0.500 | 0.150 | 1.000 | 0.550 |
| within 2,000 chars, bank | 0.636 | 0.500 | 0.125 | 0.420 |
| within 24,000 chars, bank | 0.909 | 0.550 | 0.250 | 0.570 |
| within 2,000 chars, plain | 0.909 | 1.000 | 0.208 | 0.706 |
| within 24,000 chars, plain | 1.000 | 1.000 | 0.833 | 0.944 |
| within 2,000 chars, plain-words | 0.955 | 1.000 | 0.625 | 0.860 |
| within 24,000 chars, plain-words | 1.000 | 1.000 | 1.000 | 1.000 |
| within 2,000 chars, v1 | 0.909 | 0.800 | 0.292 | 0.667 |
| within 24,000 chars, v1 | 0.955 | 1.000 | 1.000 | 0.985 |
| within 2,000 chars, v2 | 0.909 | 0.750 | 1.000 | 0.886 |
| within 24,000 chars, v2 | 1.000 | 1.000 | 1.000 | 1.000 |

Rules:
- 1 learning helps (v2 - v1 >= +0.10 on the mean, own answers, held-out): **not met**
- 2 holds when information changes (v2 changed >= v2 held-out - 0.05): **met**
- 3 better near the top (v2 - v1 >= +0.05 on the mean, first 2,000 chars, held-out): **met**
- 4 not worse than the memory bank (v2 - bank >= -0.03 every group, 24,000 chars, held-out): **met**

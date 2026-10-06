# Brain wiring results (generated)

| arm | primitives | compositions, trained pairs | compositions, held-out pairs | a quarter silenced (primitives) | ms per call (45 inputs) |
|---|---|---|---|---|---|
| cortex | 1.000 | 1.000 | 0.725 | 0.721 | 1.78 |
| random | 1.000 | 1.000 | 0.723 | 0.735 | 1.60 |
| degree | 1.000 | 1.000 | 0.728 | 0.700 | 1.92 |
| dense | 1.000 | 1.000 | 0.741 | 0.731 | 1.65 |
| mlp | 1.000 | 1.000 | 0.885 | 0.973 | 0.06 |

| difference | mean | per seed | same sign in every seed |
|---|---|---|---|
| 1_cortex_vs_random_held_out | +0.002 | +0.026, -0.042, +0.021 | False |
| 1_cortex_vs_degree_held_out | -0.004 | +0.000, -0.026, +0.016 | False |
| 2_cortex_vs_random_quarter_silenced | -0.014 | -0.011, -0.029, -0.003 | True |
| 3_cortex_vs_mlp_held_out | -0.160 | -0.185, -0.175, -0.122 | True |

Rules met:
- 1 brain wiring helps composition: **no**
- 2 brain wiring is more robust: **no**
- 3 better than a plain network: **no**
- 4 the cortex wiring has more cliques of 4+ neurons than both controls: **yes**

Cliques of 4 or more neurons (simplices of dimension 3+), per seed: {"11": {"cortex": 30, "random": 0, "degree": 18}, "22": {"cortex": 17, "random": 0, "degree": 6}, "33": {"cortex": 37, "random": 0, "degree": 27}}

### Graph topology benchmark (N=3000, 30 clusters, budgets={'c=1.0': 12, 'c=2.0': 24, 'c=4.0': 47}, 200 queries × 3 planted two-hop cross-cluster consequences)

Expander spectral check (n=600, d=6): λ2=2.815 vs Ramanujan bound 4.472 → Ramanujan

| budget | arm | recall of planted consequences | edges | nodes touched/query | ms/query |
|---|---|---|---|---|---|
| c=1.0 | vector-only(k=budget) | 0.0 | 0 | 12 | 0.058 |
| c=1.0 | A:sparse-justified | 0.235 | 10049 | 33.4 | 0.064 |
| c=1.0 | B:+random-shortcuts | 0.08 | 16027 | 41.2 | 0.064 |
| c=1.0 | C:+expander(d=6) | 0.12 | 13104 | 35.8 | 0.062 |
| c=2.0 | vector-only(k=budget) | 0.0 | 0 | 24 | 0.061 |
| c=2.0 | A:sparse-justified | 0.4883 | 10049 | 118.1 | 0.071 |
| c=2.0 | B:+random-shortcuts | 0.2783 | 16027 | 65.4 | 0.068 |
| c=2.0 | C:+expander(d=6) | 0.335 | 13104 | 113.3 | 0.075 |
| c=4.0 | vector-only(k=budget) | 0.0 | 0 | 47 | 0.06 |
| c=4.0 | A:sparse-justified | 0.8833 | 10049 | 186.4 | 0.078 |
| c=4.0 | B:+random-shortcuts | 0.52 | 16027 | 366.3 | 0.095 |
| c=4.0 | C:+expander(d=6) | 0.64 | 13104 | 274.3 | 0.086 |

Best graph arm at c=4.0: **A:sparse-justified**. Expander gain over sparse justified graph: -0.2433 → adopt expander: **no**.

Expander/random overlays add unjustified edges that consume the fixed budget without pointing at semantically or causally related records; the sparse justified graph wins or ties. Justified graph expansion, however, recovers cross-cluster consequences that vector search at the same budget misses.
# Brain wiring and optogenetics for the reasoning neurons: results

**Run on 2026-10-06, after the rules in `docs/BRAIN_WIRING_PREREGISTRATION.md` were written.**
- Raw results: `docs/benchmarks/brain_wiring/results.json` and `report.md`.
- Code: `cie/src/cie/neuro/`.
- Reproduce: `python -m cie.neuro.experiment --circuit <ToyCircuit-S1-6k> --out <dir>`. It takes about 4.5 minutes
  on 2 CPU threads.

## Decisions

| Rule | Result |
|---|---|
| 1. Brain wiring helps composition (cortex − random ≥ +0.05 and cortex − degree ≥ +0.03, held-out pairs) | **Not met.** cortex − random +0.002 (per seed +0.026, −0.042, +0.021); cortex − degree −0.004 (+0.000, −0.026, +0.016). |
| 2. Brain wiring is more robust (cortex − random ≥ +0.05, a quarter silenced) | **Not met.** −0.014 (−0.011, −0.029, −0.003): slightly worse in every seed. |
| 3. Better than a plain network (cortex − mlp ≥ +0.05, held-out pairs) | **Not met. Clearly the other way:** −0.160 (−0.185, −0.175, −0.122). |
| 4. The cortex wiring has more cliques of 4+ neurons than both controls | **Met** in every seed: 30, 17 and 37 against 0, 0 and 0 for random wiring, and 18, 6 and 27 for the degree-preserving control. |

The brain's multi-dimensional wiring was really there (rule 4), and it made no difference to how well the neurons
reason (rules 1–3). The neural part stays out of the product. The reasoning engine's useful part is already in the
product as exact rules (`docs/PLAYBOOKS.md`).

## Results (mean of seeds 11, 22, 33)

| arm | primitives | compositions, trained pairs | compositions, held-out pairs | a quarter silenced (primitives) | ms per call (45 inputs) |
|---|---|---|---|---|---|
| cortex | 1.000 | 1.000 | 0.725 | 0.721 | 1.78 |
| random | 1.000 | 1.000 | 0.723 | 0.735 | 1.60 |
| degree | 1.000 | 1.000 | 0.728 | 0.700 | 1.92 |
| dense (the engine's wiring) | 1.000 | 1.000 | 0.741 | 0.731 | 1.65 |
| mlp (the engine's plain network) | 1.000 | 1.000 | 0.885 | 0.973* | 0.06 |

\* The plain network has no neurons to put opsins in. Its value is with a quarter of its hidden units set to zero,
so it is not the same perturbation.

- **Every arm learns everything it is trained on:** all 45 primitives and all 486 training compositions.
- **Combining operations never seen together is where they differ.** All four wirings of the spiking neurons score
  about 0.72–0.74 on the 189 held-out cases; always answering "unknown" would score 0.413. The plain network scores
  0.885 and is roughly 30 times faster.

## The wiring (Blue Brain SSCx toy circuit, 7% of biological density)

| seed | hub neuron | connections among the 64 | directed simplices: cortex | random | degree-preserving |
|---|---|---|---|---|---|
| 11 | 3708 (L5) | 258 | 258 / 216 / 30 | 258 / 59 / 0 | 258 / 197 / 18 |
| 22 | 1432 (L3) | 223 | 223 / 167 / 17 | 223 / 40 / 0 | 223 / 147 / 6 |
| 33 | 1605 (L3) | 257 | 257 / 226 / 36 / 1 | 257 / 42 / 0 | 257 / 218 / 27 |

The simplex counts are listed by dimension: connections / 3-neuron cliques / 4-neuron / 5-neuron.
- Relative to random wiring, the cortex has 3–5 times as many 3-neuron cliques, and dozens of 4-neuron ones where
  random wiring has none.
- Much of this comes from the neurons' degrees: the degree-preserving control keeps most of the 3-neuron cliques. The
  4-neuron cliques are where the cortex stands out.
- At this density the largest clique has 5 neurons. A full-density reconstruction reaches 7–8.
- Neurons per neighbourhood:
  - inhibitory: 3, 2 and 1;
  - by layer: seed 11 is mostly layer 5 (40 neurons); seeds 22 and 33 are mixed across layers 2–5.

## What the light showed

Opsin models, as run (PyRhO's fitted parameters, at 10 mW/mm²):
- **ChR2** peaks 4.9 ms after the light comes on, at 2.6 times its steady current, and closes with a 12 ms time
  constant. This matches the known behaviour of ChR2.
- **NpHR** peaks at 54 ms and closes in 10 ms. It takes seconds to settle back.

Results on the primitive networks (100% without light):

| perturbation | cortex | random | degree | dense |
|---|---|---|---|---|
| NpHR on a random quarter of the neurons (20 draws) | 0.721 | 0.735 | 0.700 | 0.731 |
| ChR2 on a random quarter (20 draws) | 0.822 | 0.848 | 0.824 | 0.857 |

- **The computation is spread out.** Silencing any layer that holds a fair share of the neurons breaks most of the
  five operations, and the damage grows with the number of neurons silenced. Silencing the 40 layer-5 neurons of
  seed 11 left 0.49–0.67 correct across wirings; silencing 3 layer-6 neurons in seed 22 left 0.93–1.00.
- **No population is "the AND neurons".** Across wirings and seeds, no layer or cell class consistently carries one
  operation.
- **The inhibitory neurons** (1–3 per network) do not matter consistently. Silencing them broke operations in the
  cortex wiring of seeds 11 and 33, but not in the random wiring of seed 11.
- **Fragile.** Losing a quarter of the neurons costs about 27% of the answers. That is the opposite of the graceful
  degradation brains are known for, and the brain-like wiring does not change it.

## Checks

- **The neurons are the engine's.** With all-to-all wiring and the engine's synapse constants, `cie.neuro.Neurons`
  loaded with the engine's own checkpoints gives its outputs to within 3·10⁻⁶ for seeds 11, 22 and 33. All 45
  patterns are right.
- **Same units in every arm.** Every arm uses the same 64 neurons with the same synapse dynamics; only the
  connections differ.
- `tests/test_neuro.py` (6 tests): opsin kinetics, the controls keep their edge counts and degrees, clique counting,
  wiring and light reach the neurons, the task split, and the whole pipeline.

## Limits

- **One small toy circuit.** It is built at 7% of biological density, and the network has 64 neurons. A
  full-density microcircuit, or a larger network, could behave differently. Nothing here suggests it would help the
  product.
- **Opsin amplitude is set by protocol.** The opsin models fix the timing; the strength of the drive is chosen, as
  light power is in a laboratory.
- **Approximations.** The photocurrent's voltage dependence is not modelled. PyRhO's ChR2 parameters are fitted to
  recordings; its NpHR parameters are the package's own.
- **What it doesn't show.** The plain network's silencing is a different perturbation (zeroed units, not
  hyperpolarised neurons), so the 0.973 shows only that it degrades more gently.

## Data and licences

- **Blue Brain SSCx toy circuit:** Zenodo 12202781, CC-BY 4.0, archive sha256
  `e2bb3057ea8346718c35940387cb291e5726defe61208aba7634af6292bb5334`. Not stored in this repository: download and
  extract `networks/` to run the experiment.
- **PyRhO 0.9.4:** BSD licence. Only its published parameter values are used.
- **Reasoning-Engine-v2:** the user's prototype, used for the equivalence check only. Its Blue Brain EModelRunner
  sample files (CC-BY-NC-SA) are not used or stored here.

# Brain wiring and optogenetics for the reasoning neurons: what decides, fixed before the run

I wrote this on 2026-10-06, before the real run. The only runs so far were plumbing checks: 20 training steps on a
made-up circuit (`--quick`). The results go in `docs/BRAIN_WIRING_RESULTS.md`.

## Why

Reasoning-Engine-v2 (the user's prototype) has spiking "bio" neurons, all wired to each other, that learn the five
three-valued operations. Its own benchmark showed:
- they learn the 45 patterns as well as a plain network, about 8 times more slowly;
- composition was exact only because a symbolic program chains the operations.

Two ideas from neuroscience are tested here:

1. **Connections in many dimensions.** In Blue Brain's reconstructed cortex, neurons form directed cliques of up to
   7–8 neurons, far more than random wiring has (Reimann et al. 2017). Does wiring the reasoning neurons like a
   piece of cortex make them better at combining operations, or more robust?
2. **Optogenetics** (the 2026 Nobel Prize in Physiology or Medicine: Deisseroth, Hegemann, Nagel). Light-gated
   channels switch chosen neurons on (ChR2) or off (NpHR) within milliseconds. Used here as in the laboratory: to
   test which neurons a computation needs.

## Data

- **Wiring:** Blue Brain's "SSCx toy circuit with 6k neurons" (Zenodo 12202781, CC-BY 4.0; archive sha256
  `e2bb3057…5334`). It holds 5,924 rat somatosensory cortex neurons in all six layers, and 568,717 synapses forming
  123,636 connected pairs, built at 7% of biological density. For each seed, the network is the topological
  neighbourhood of one of the three best-connected neurons: the hub, plus the 63 partners with the most connections
  among its partners, keeping every connection between them.
- **Synapses:** each neuron's release probability, depression and facilitation times are the medians of its own
  synapses in the circuit. They are identical in every wiring arm.
- **Opsins:** PyRhO 0.9.4 (BSD licence) parameters: the four-state ChR2 model fitted to recorded ChR2 photocurrents
  (Evans et al. 2016), and the three-state NpHR model. The light protocol:
  - light on 100 ms before the input and throughout the six 20 ms steps;
  - 10 mW/mm² (ChR2 at 470 nm, NpHR at 590 nm);
  - drive set to 2 times the neuron's threshold at the opsin's steady current (+ for ChR2, − for NpHR).

## Arms

All arms use the engine's neuron, 64 units, 6 steps, with identical inputs and readout.

| arm | recurrent connections |
|---|---|
| `cortex` | the neighbourhood's own connections, in their own direction |
| `random` | the same number, placed uniformly at random between the same neurons |
| `degree` | the cortex connections swapped in pairs, so every neuron keeps its in- and out-degree but the cliques break up |
| `dense` | all to all, as in the engine (reference) |
| `mlp` | the engine's plain network (reference) |

## Tasks

- **Primitives:** the 45 patterns (a fit check), trained as the engine does it: full batch, Adam at lr 0.01, 400
  steps, keeping the weights with the lowest training loss.
- **Compositions:** `(a op1 b) op2 c` in one pass. NOT applies to the left side only.
  - Trained on 18 of the 25 operation pairs, every value combination: 486 cases, 1,000 steps.
  - Tested on the 7 pairs held out with seed 2026: AND→AND, AND→OR, AND→XOR, OR→XOR, NOT→OR, NOT→EXCEPT, XOR→OR.
    That is 189 cases; always answering "unknown" would score 0.413.
- **Light**, on the primitive networks:
  - NpHR on a random quarter of the neurons (20 draws);
  - ChR2 on a random quarter;
  - NpHR on each layer's neurons and on the inhibitory neurons.

  The plain network has no neurons, so for reference a quarter of its hidden units are set to zero.

Seeds 11, 22 and 33 (the engine's). Each seed has its own neighbourhood, its own controls and its own initial weights.

## Rules

Each rule is decided on the mean over the three seeds. It is called **clear** when every seed has the same sign.

1. **Brain wiring helps composition** if `cortex` minus `random` is at least +0.05 on the held-out pairs, and
   `cortex` minus `degree` is at least +0.03 (the cliques themselves, not just the degrees).
2. **Brain wiring is more robust** if, with a quarter of the neurons silenced by NpHR, `cortex` minus `random` is at
   least +0.05 on the primitives.
3. **Better than a plain network** if `cortex` minus `mlp` is at least +0.05 on the held-out pairs.
4. **Check of the premise:** the cortex wiring has more directed cliques of 4 or more neurons than both controls, in
   every seed.

## What each outcome means

- **1 and 3 met:** worth a larger study (full-density circuits, more neurons, harder compositions) before anything
  goes near the product.
- **1 or 3 not met:** the neural part stays out of the product, as now. The useful part of the reasoning engine is
  already in the product as exact rules (`docs/PLAYBOOKS.md`).
- **The light results are reported either way.** They show which populations each operation depends on.

## Known limits

- This toy circuit is at 7% density, so its cliques reach 4–5 neurons, not the 7–8 of a full-density
  reconstruction.
- With 64 neurons and three seeds, small differences are noise; hence the thresholds and the same-sign check.
- The opsin models give the time course. How strong the drive is per neuron is set by the protocol, as light power
  is in a laboratory. The voltage dependence of the photocurrent is not modelled, because the neurons' membrane is
  abstract.

# Study: can ADRN be trained to learn physics?

Follow-up to [`STUDY_ADRN.md`](STUDY_ADRN.md). Two questions were asked: (1) how
large an ADRN runs in this sandbox, aimed at simulating atoms; (2) whether ADRN
can instead be trained to *learn physical law* to <1% error in seconds, "just
like equations". A third proposal then arrived — a **small neural controller +
large symbolic law library + exact executable operators** — which is a different
and much better architecture, and most of this document is about that.

All measurements are from this sandbox: 4 Intel Xeon cores @2.8 GHz, AVX-512,
15 GB RAM, **no GPU**.

---

## Part 0 — the two numbers that were asked for

**ADRN capacity here.** Params scale as ≈5N² in `n_neurons`; wall time as ≈N².

| mode | max that fits | trainable params | peak RSS | wall time |
|---|---|---|---|---|
| training (batch 32, T=8) | N=2048 | 21.0 M | 12.3 GB | 69.9 s / step |
| inference (batch 1, no grad) | N=8192 | 335.7 M | 12.0 GB | 55.5 s / forward |

N=2560 training is OOM-killed. The bind is not the parameter count but the
eligibility tensor `e` of shape `(batch, N, branches, inputs)` held across T
unrolled steps.

**Classical MD here.** `cell_sim/atom_engine` with numba: ~4×10⁴ atom-steps/s,
flat from 1k to 10k atoms (the neighbour list is correctly O(N)), then collapsing
— 50k atoms ran >21 minutes for 100 steps against 125 s predicted by flat
scaling, at 0.1 GB RSS, so the fault is an un-neighbour-listed path in bond
formation, not memory.

For context on the original "billions of atoms" goal: fp32 positions **alone**
for 10⁹ atoms are 12 GB of this box's 15 GB. It does not fit before any compute.

---

## Part 1 — ADRN cannot be a physics model, and the reason is structural

An audit of `/workspace/cell/colab/adrn.py` (352 lines) checked eight inductive
biases that physics surrogates depend on. ADRN has **none** of them: no
translation invariance, no rotation equivariance, no permutation invariance over
particles, no locality/message passing, no energy conservation, no symplectic or
time-reversal structure, no extensivity, and no particle axis at all — its input
is one fixed-length vector through `nn.Linear` (`adrn.py:292`), so a molecule
must be flattened and is immediately crushed.

Three measured findings are worse than the missing symmetries, because no amount
of architectural bolt-on fixes them:

**1. The output is a piecewise-constant staircase.** A hard Heaviside spike
(`adrn.py:60`) feeds an integer spike count (`L319`) feeds a linear readout
(`L333`). Finite differences at ε = 1e-6, 1e-4, 1e-3 and 1e-2 all give
max|Δy| = **exactly 0**. Sweeping one input over [−2,2] at 801 points: 91.0% of
adjacent samples bit-identical, median jump **5.95% of output range**. A <1%
target is unreachable on a staircase whose tread is ~6% — and F = −∇E is
structurally impossible when ∂output/∂input is zero almost everywhere.

**2. The gradient the optimiser uses is a fabrication.** At a point where every
finite difference up to ε=1e-2 is exactly zero, autograd returns
`[0.0192, 0.0013, −0.0039, …]` — entirely from the surrogate derivative at
`adrn.py:63-65`. It does not correspond to the forward function.

**3. With plasticity on it is not a function.** The same input evaluated three
times gives three different answers, because `_plastic_update` mutates `W_f`,
`W_s`, `theta` and `A` in place under `@torch.no_grad`.

Also: the neurons never interact. `S` is never fed back as `s_in` — `L318` re-feeds
the encoder output every one of the T steps. ADRN as run is a bank of independent
LIF units, not a recurrent workspace.

---

## Part 2 — what "learn physics from data" actually delivers

### The repo has already measured its own error ceiling

This is the most plan-relevant asset in the cell repo and it was sitting
unremarked. Error scales with **what you let vary**:

| what varies | measured error | source |
|---|---:|---|
| initial conditions only, coefficients fixed | **0.06–0.9%** | P11, P12 |
| a hidden per-trajectory parameter | 15.5–18.6% | P14 |
| spatially switching rules | 26.7–27.7% | P15 |
| oscillatory / unitary (Schrödinger) | 43.3% | P13 |

I re-ran `prototype_p11_neural_pde.py` to confirm the top row: an 18,849-param
conv net on 2-D Fisher-KPP gives **0.03% one-step, 0.92% at 30 rollout steps**.
Two caveats the number needs: `D_DIFFUSION = 0.1` and `R_REACTION = 1.0` are
module constants, so it learned *one instance*, not a law family; and its ground
truth is explicit Euler, so 0.92% is agreement with a first-order scheme, not
with nature.

### The literature says the same thing, and warns about itself

- **FNO** hits 0.86–1.09% on laminar Navier-Stokes (ν=1e-3) and Darcy — and
  **19.18%** at ν=1e-4, falling only to 8.20% with 10× the data. The paper states
  verbatim: *"We do not compare against traditional solvers."*
- **McGreivy & Hakim, Nature Machine Intelligence 2024**: of 76 papers claiming
  to beat numerical solvers, **79% used weak baselines**; 94.8% of 232 abstracts
  reported only speed.
- **PINNs** have not beaten classical solvers on accuracy *or* solution time in
  controlled comparison (Grossmann et al. 2024).
- **MLIPs** reach near-DFT accuracy in-distribution but degrade ~4× out-of-distribution
  (45 → 176 meV/Å) via systematic potential-energy-surface softening. On rMD17
  aspirin at the field-standard 1,000-config split, against an independently
  re-measured force-component std of 1272.9–1273.2 meV/Å: **MACE 6.6 meV/Å =
  0.518%**, Allegro 7.3 = 0.573%, NequIP 8.2 = 0.644%. So the margin over the 1%
  bar is **1.4–1.9×, not 6×** — the 2.1–2.3 meV/Å figures often quoted are other
  molecules. Non-equivariant SchNet at 14.3 meV/Å = 1.12% **fails** the bar.
- **On CPU, MACE runs slower than this repo's own classical force field.**
  Measured here: MACE-MP-0-medium on aspirin (21 atoms) = 3.47 s/call.
- Every family listed is trained on the output of the classical simulation that
  was rejected. MPtrj = 1.58M DFT structures; OMat24 = ~110M calcs at >400M
  core-hours.

### What "<1%" turns out to mean (adversarial verification)

A dedicated refutation pass decomposed the claim. It survives in three places and
is **refuted in four**:

| claim | status |
|---|---|
| latency in seconds | **established**, ~5 orders of margin |
| <1% rel-L2 on a *fixed-coefficient*, smooth, dissipative 1–2D PDE, in-distribution | **established** |
| <1% force-component MAE for one molecule vs *its own* DFT reference | **established**, margin 1.4–1.9× |
| <1% vs **nature** or any gold standard | **refuted — nowhere, in any domain** |
| <1% on any **derived/integrated** observable | **refuted** |
| <1% with **physical parameters varying** | **refuted** |
| <1% **out of distribution**, turbulent, or oscillatory | **refuted** |

The sharpest single datapoint: the original MD17 and revised rMD17 labels **for
identical aspirin geometries** differ by 133.41 meV/Å — 10.48% of the force std,
with a systematic 4.3% scale factor — which is **20× larger than MACE's headline
error**. And PBE/def2-SVP itself gets ethanol's gauche–trans conformer ordering
*qualitatively* wrong (CCSD(T) +45 vs PBE −129 cm⁻¹). Sub-1% describes agreement
with a specific solver or a specific DFT input file, never with the world.

On derived quantities: phonon vibrational free energy 2.19 meV/atom at 300 K
rising to 9.30 at 1000 K with documented systematic bias; thermal conductivity
best κ-SRME 9.3–11.9%, with eqV2-M at 177% while ranking near the top on
stability; vorticity 36.1%; coarse-grained free energies 58× chemical accuracy.
**The quantity that clears 1% is not a quantity anyone wants.**

On varying parameters: 1.5% best case *even when handed the true parameter*,
3.6–18% when inferred. A 20% viscosity shift took an FNO from 0.0999% to
**9.9165%**.

### Speed was never the problem

Inference is over-satisfied by ~5 orders of magnitude: 404,875 configurations/s
for a 474k-param energy surrogate, i.e. 2.5 µs per prediction. **"In seconds" is
free. "<1% error" is the whole difficulty**, and it holds only inside the
training distribution.

---

## Part 2b — the result that actually answers "just like equations"

Three competing proposals were scored by two independent judges. The
**equation-discovery** proposal won on every axis (physics realism 9/9,
feasibility 10/10, meets-goal 9/8, honesty 9/10), and — unlike the others — its
headline **reproduced independently**: one judge reran it unmodified and got
0.0209% against a claimed 0.0208% in 2.2 s; the other wrote their own 60-line
STLSQ from scratch against P11's generator, fit in **0.53 s**, and recovered the
equation.

Sparse regression (SINDy / PDE-FIND) on the same Fisher-KPP problem where the
neural surrogate reaches 0.89%:

| | measured |
|---|---:|
| coefficient recovery, D and r, 20 trajectories | **0.07–0.27%** in 0.23 s |
| hidden per-trajectory r from a *single* 41-frame trajectory | 0.070% mean |
| 30-step rollout, in-distribution | **0.0208%** |
| 30-step rollout, **out of distribution** | **0.0172%** |
| at 100× the training horizon | 0.1762% |
| reaction rate pushed 2–3.3× outside the fitted range | 0.0658–0.1020% |
| transferred across 32×32 / 64×64 / 96×96 grids | 0.0208–0.0213% |
| cost to evaluate the recovered equation | ~10 µs; 30-step rollout ~0.3 ms |

Two things here are decisive. It is **~40× more accurate** than the neural
surrogate on the identical problem. And it is *no worse out of distribution than
in* — 0.0172% vs 0.0208% — because what it returns **is an equation**. That is
the property the whole request was reaching for, and no interpolating surrogate
has it: a 20% viscosity shift takes an FNO from 0.0999% to 9.9165%, a 99×
degradation, while the recovered equation extrapolates 2–3.3× in its parameter
and stays under 0.11%.

**The measured failure modes, which are severe and mostly silent:**

- **Library misspecification is silent and confident.** With a `sin(4u)` term
  absent from the candidate library, STLSQ returned a 6-term equation at
  **R² = 0.99976** — passing every check while being wrong. This is the same
  hazard as M1/M2 in the pilot, and it is the dominant risk.
- **It needs clean data.** ~0.13% coefficients at 0.1–1% noise, 1.438% at 3%
  (already missing the bar), total support collapse to 11.777% at 5%.
- **Sparsity selection is not automatic.** BIC over-selected at *every* noise
  level tested, retaining spurious terms even on noiseless data.
- **It does not scale in variable count.** AI Feynman's 9-variable gravitation
  case needed 10⁶ points and 5,975 s. No credible path to high dimensions.
- **On realistic sampling ranges** (SRSD) the best methods get 50–60% Easy,
  17.5–30% Medium, **4% Hard**.
- Everything is still measured against a numerical solver, not nature —
  recovering P11's coefficients to 0.1% recovers *explicit Euler's* law.

**A falsification worth recording.** The ADRN-maximalist proposal's one apparent
win — a hidden-parameter conditioning loop cutting rollout error 10.49% → 3.64% —
**did not survive reseeding**. `armC_matched.py` hardcodes `torch.manual_seed(0)`;
both judges reran at seeds 1/2/3 and got 10.65% / 12.80% / 16.87%. The effect was
a seed artifact. Separately, even the *oracle* arm handed the true hidden
parameter for free reached only 1.53% — so for neural surrogates with varying
physical parameters, perfect system identification may still not clear 1%.

---

## Part 3 — the controller + law library + exact operators architecture

This reframing is **right in its factoring**, and it is the strongest idea in the
thread. What follows is where it is supported, where it is inverted, and what is
genuinely new.

### 3.1 Do not restart — five efforts already exist

| project | scale (measured) | licence | what it lacks |
|---|---|---|---|
| **Physics Derivation Graph** (derivationmap.net) | *publishes no counts at all* | CC BY 4.0 | A(E), dimensional signature, regime variants, ancestry, templates |
| **Physlib** (leanprover-community) | 8,523 thms, 2,558 defs, 187,578 lines | Apache-2.0 | FluidDynamics 12 thms, Optics 0, Thermo 34 |
| **Modelica MSL 4.1.0** | 2,674 files, 2,645 models, 119 connectors | BSD-3 | no formal semantics; no A(E) |
| **DLMF** | 9,977 formulae, **2,691 constraints** | NIST © | special functions, not physical laws |
| **QUDT 3.1.4** | 2,844 units, 1,203 quantity kinds, 270 dimension vectors | CC-BY | no laws |

Three things follow immediately:

- **PDG is your proposal, minus the parts you care about most.** Its FAQ concedes
  the gap in your language: *"Simply carrying out mathematical manipulations of
  expressions does not necessarily lead to physically valid outcomes."* Its
  dimensional analysis is aspirational. That it publishes **no count of
  derivations anywhere**, for a project whose thesis is that a finite graph
  describes all of mathematical physics, is itself the scale answer.
  `derivationmap.net/other_projects` is a ~60-project prior-art survey someone
  already spent a decade assembling — read it before writing another design doc.
- **Modelica is the omission.** "Energy balance + Fourier conduction + convection
  BC" is *literally* `Modelica.Thermal` composition. Acausal components with
  (potential, flow) connectors that auto-enforce conservation is your
  compositional retrieval, running industrially at 100,000+ equations. Import via
  OpenModelica's flattened-model XML dump; never write a `.mo` parser.
- **"Reject x+v" is already done and already installed.** SymPy 1.14
  `physics.units` has 355 unit definitions, 7 base dimensions;
  `check_dimensions(meter + second)` already raises. That is a one-line import,
  not a subsystem. Spend the engineering elsewhere.

Note the realistic scale of hand-curated derivation graphs: Physlib's informal
typed dependency graph is **~90 nodes after 3,419 commits**. Curation, not
algorithms, has been the binding constraint on every prior attempt.

### 3.2 The accuracy claim is inverted — this is the one correction that matters

The proposal says the neural part can be small *because* the operators are exact.
The evidence says the opposite, and says it precisely.

**AlphaGeometry's accuracy comes from soundness, not exactness.** DDAR emits only
deductively-closed consequences plus a checkable proof, so a wrong neural
proposal costs **time**, not **correctness**. Neural error rate is decoupled from
output error rate. *That decoupling does not transfer to physics.* An exact ODE
integrator handed the wrong governing equation returns a confidently wrong answer
to 1e-12. There is no soundness barrier unless the operator can **refuse** — which
requires exactly the A(E) checking nobody has built.

**The physics error budget is not calculation.** UGPhysics (5,520 problems; best
model 49.78%) analysed 100 errors and found flawed reasoning, knowledge
deficiency and incorrect application dominant, stating explicitly that this
*contrasts with mathematics, where calculation is a major error source.*
PhysReason names four bottlenecks; three are model-selection/assumption errors.
PAL's +15pp on GSM8K worked precisely because GSM8K's residual error *was*
arithmetic. Physics' is not.

**The strongest published physics agent measures the tool contribution directly.**
Physics Supernova scored 23.5/30 on IPhO 2025 (14th of 406 contestants). Ablated
to the bare LLM: 21.4 ± 1.1. **Tools contribute ~2.1 points, under 10% of the
score; the neural model contributes over 90%** — and the tools that helped were a
vision analyser and a self-critic, not a CAS.

**Tool augmentation raises the floor, not the ceiling.** ASyMOB: augmentation
helps weak models and does nothing or hurts strong ones.

> Corrected claim: exact operators are a **floor-raiser that makes a weak
> controller usable**, not a ceiling-raiser that makes a small controller
> sufficient.

### 3.3 The controller is the measured bottleneck — and it is the part being made small

ToolFailBench across 19 models: Llama-3.1-8B scores 47.32% clean tool-use,
**98.39% unnecessary tool-use**, 0.00% control accuracy. At 70B it still calls
tools on 77.73% of no-tool control tasks. There is a capability cliff around 7B
below which tool-calling essentially does not emerge.

So: set a 7B+ floor for any neural controller — **or eliminate the controller.**

For a small library you can sidestep both Nayak's NP-hardness result and the
controller's selection error entirely: **enumerate every candidate law, execute
each, rank by data residual + A(E) pass/fail.** At N≈20–30 on 4 cores this takes
microseconds, has *zero selection error by construction*, and is the baseline any
future controller must beat to earn its place. ADRN is disqualified for this role
too, on determinism grounds alone.

### 3.4 Dimensional analysis: right idea, wrong justification

The claim was that dimensional typing "could reduce computation enormously."
Measured:

- **AI Feynman rerun with the dimensional-analysis module disabled still solves
  93/100** (vs 100/100 with). The authors write that DA is *"usually not
  necessary for successfully solving the problem."* The real workhorses were
  neural-discovered translational symmetry and separability.
- Pure DA solves 26/117 Feynman equations in constant time — but those same 26
  are solved at 100% hit rate by PySR anyway.
- SOTA is QDSR at 91.6%; ablations give 85.1% (DA, no extra variables) and 74.2%
  (neither). Ordering of value: quality-diversity search > enriched vocabulary >
  dimensional analysis.

But it *is* valuable, for a different reason:

- **PhySO** measured the pruning honestly: 268 candidate expressions collapse to
  6 (97.8%) at expression length 5, growing with length.
- The clean ablation inside one architecture: DSR without units 42% → PhySO with
  units **58.5%, +16.5pp** — and it is specifically about **noise robustness**.
  At 10% noise, AI Feynman 2.0 drops to 0.7% while unit-constrained search holds.

> Reframe: *dimensional structure lets a small model learn from small, noisy
> data.* That is well supported. "It reduces computation enormously" is not.

One design consequence: PhySO's own ablation shows that merely *constraining
token choice* with a units prior is not enough. A hard type system that only
**rejects** ill-dimensioned candidates is the weak version; feeding dimensional
signature into **generation** is the strong one.

A trap to pre-register against: SRSD showed the Feynman benchmark is defective
(~25% of problems have duplicates, no irrelevant variables). With realistic
ranges AI Feynman drops to 30/2.5/2.0%; **adding 1–3 dummy variables takes it to
0%/0%/0%**, and PySR from 60/30/4% to 20/5/0%. Irrelevant-variable robustness
must be a pre-registered control, not an afterthought.

### 3.5 Ancestry as a limit is false for the cases you most want

`L_simple = Limit(L_general, ε → 0)` fails wherever the intertheoretic limit is
**singular** — and that includes the worked example. Geometric optics does not
fail when λ is merely not small; it fails at caustics and edges, where the limit
does not commute. Same for boundary layers, turbulence, WKB. No machine-readable
formalisation of intertheoretic limits exists in any surveyed system.

Encode ancestry instead as an explicitly **non-transitive** edge
`(general_id, simple_id, small_parameter, validity_bound, breaks_at_predicate)`
with separate `valid_if` / `breaks_at` / `degrades_as` fields, and **measure** the
convergence order from data rather than asserting it. In the pilot below, that
auto-fit recovers order 2.0000 for the pendulum (theory: 2) and 1.00 for lumped
capacitance — which lets edges be auto-tagged regular vs singular instead of
silently lying.

### 3.6 What is genuinely new here

**A(E) as a first-class, calibrated, machine-checkable object is a real gap in
every surveyed system**, and it is the most defensible contribution in the
proposal. PDG concedes it. Modelica has no formal semantics. DLMF attaches
constraints but only for special functions. The only place applicability is
machine-checked in production is regime-switching in hybrid DSMC/Navier-Stokes
solvers (Boyd's gradient-length local Knudsen number, critical value 0.05).

And it should be an **error estimate, not a boolean**. Measured during pilot
design: for lumped capacitance, the calibrated bound ε = Bi/6 + Bi²·Fo/3 is
conservative at **100% of grid points** (ratio 1.002–1.341), whereas the textbook
flat rule Bi < 0.1 admits true errors of **1.39–4.73%**, because the real 1%
contour moves with Fo (Bi_crit drifts 0.0721 → 0.0357). The calibrated form is
strictly better than the rule in every engineering textbook, is publishable
standalone, and needs **no neural component at all**.

Two more genuine gaps worth claiming: **derivation templates as parameterised,
executable reasoning programs** (PDG's inference rules are deliberately atomic
single steps, not templates), and **constants carrying declared dimensional
signatures** — PySR's `WildcardQuantity` lets a free constant absorb whatever
units are needed, which its own maintainer describes as a hole.

---

## Part 4 — what to build: the CCS-1 pilot

Smallest experiment that can genuinely refute the architecture. Verified runnable
here; ~6 hours of engineering, **under 10 minutes wall-clock**, peak RAM <500 MB.

**Scope.** One system family: 1-D transient conduction in a symmetric plane slab
with convective (Robin) boundaries. Library = 6 nodes: 3 primitives
(`energy_balance`, `fourier_conduction`, `robin_bc`), 1 exact parent
(`slab_series`), 2 children (`lumped_capacitance` = Bi→0 limit, `semi_infinite` =
Fo→0 limit). Plus a 2-node pendulum domain whose *only* purpose is to prove the
engine is not hand-fitted: passing requires adding node JSON with **zero** engine
code changes.

**Pipeline.** type-check → compose (substituting Fourier into the energy balance
*eliminates q* and yields the heat equation — genuine assembly, not retrieval) →
nondimensionalise (6 inputs → 3 groups, assert count = Buckingham N−r) →
**enumerate and verify, no neural net** → estimate parameters by least squares →
solve, returning a three-valued result `{value, INVALID_ASSUMPTION,
OUT_OF_DOMAIN}`.

**Pre-registered criteria** (all anchored to numbers measured during design):

- **P1 exactness** — median relative error <1e-9, p99 <1e-7. Measured basis: the
  symbolic arm returned exactly 0.0000% at every Bi ∈ {0.05, 0.5, 2, 10}.
- **P2 neural gap** — no NN arm reaches median <1e-6 at any budget.
- **P3 assumption checking** (load-bearing) — on the trap stratum Bi ∈ [1,50],
  naive retrieval must produce >10% error and every case must be caught.
  Measured: 31.09% at Bi=1 rising to 100.00%.

**A pre-registered partial refutation of the original claim, which must be
reported.** The claim "a controller composing exact operators gives <1% where a
pure neural regressor would not" is **already false in-distribution**: a plain
64×64 MLP measured **0.806%** (raw features, N=500) and **0.391%** (Π-groups,
N=50). Both are under 1%. The defensible claim is the ~10⁷ **precision** gap
(machine precision vs a ~0.5% plateau that more data does not move) and the
out-of-distribution gap — *not* the 1% threshold. Writing it up as "we achieved
<1% and the neural net didn't" would be dishonest by the pilot's own design data.

**What it does not prove.** The ground truth *is* one of the library entries, so
the symbolic arm wins on precision by construction. This is a **necessary-condition
test**: failing it is strong evidence against the architecture; passing it is weak
evidence for it. It says nothing about a large library (Nayak's NP-hardness never
activates at N=3), nothing about autoformalisation (25.3% in Wu et al. — the
weakest-measured step in the whole stack, and input here is structured JSON), and
nothing about constructing equations for a novel system (SOTA is 31.5% on
LLM-SRBench).

**Two honesty controls that must ship with it.** M1: force the wrong law through
an exact operator — 99.972% wrong, *no error signal*. M2: truncate the series —
4.12% error, *every check passes*. These are the demonstrations that exactness
alone confers nothing.

---

## Part 5 — what I would actually do

0. **Run the equation-discovery test first.** It is the cheapest and most
   goal-aligned thing here: PDE-FIND on P13's 2-D Schrödinger data — the repo's
   *worst* neural result (43.31% at step 30) and the only ground truth in the
   repo accurate to machine precision, so the label-quality objection does not
   apply. Reuse P13's split-step Fourier generator unchanged but save at
   dt=0.005 rather than 0.05 so the central-difference estimate of ψ_t does not
   alias. Library `[lap(ψ), V·ψ, ψ, |ψ|²ψ]`; truth is
   ψ_t = (i/2)∇²ψ − iVψ. **Pre-registered pass:** both coefficients within 1%
   *and* 30-step rollout on a held-out wavepacket <1% rel-L2. **Then immediately
   re-run with `V·ψ` deleted from the library** — if that still returns a
   confident fit, the silent-misspecification failure is live and gates
   everything downstream. Cost: 3–8 minutes.
1. **Read `derivationmap.net/other_projects` and Falkenhainer & Forbus 1991,
   "Compositional Modeling: Finding the Right Model for the Job"** before writing
   more design. The proposal is a rediscovery of compositional modelling; that
   paper has the assumption-class formalism it needs, and Nayak 1995 has the
   complexity results.
2. **Build CCS-1.** One afternoon, and finishing means something.
3. **Claim A(E)-as-calibrated-bound as the contribution.** It is the real gap, it
   is measurable, and it needs no neural network — which is the strongest thing
   that can be said about it.
4. **Import, don't author.** Modelica MSL via OpenModelica XML for composition;
   QUDT for the type vocabulary; DLMF's constraint schema as the A(E) pattern
   (schema only — NIST copyright); Physlib's `deps : List Lean.Name` pattern for
   linking not-yet-executable nodes. Budget a CAS verification harness from day
   one and assume a few percent of any curated library is wrong — automated
   verification has found real errors in DLMF, the most carefully curated
   reference that exists.
5. **Drop ADRN from the physics path entirely** — as force field and as
   controller. Nothing in Part 1 is fixable by training.

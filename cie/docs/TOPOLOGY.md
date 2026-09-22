# Topological memory bank (Blue Brain cliques and cavities)

The Blue Brain Project's topological framework (Reimann et al., *Frontiers in
Computational Neuroscience*, 2017) describes cortical processing as a cascade of
directed cliques: a stimulus recruits pairs and triples first, then the
mid-dimensional simplices they complete, then the high-dimensional simplices whose
sinks fire when every presynaptic neuron converges, with cavities (cycles of
cliques no clique fills) as the global scaffold; then everything collapses.
Learning (STDP) re-routes the source-to-sink pathways.

This document says how that maps onto the memory bank, what was built, how it is
measured against the standard bank, and what the measurements say. The numbers
are in `docs/BENCHMARKS.md` (section "Topological memory bank"), generated from
`eval_out/topology/bench_topology.json` and the scale benchmark's arms.

## The mapping

| Blue Brain | memory bank |
|---|---|
| neuron | memory record (typed, versioned, bitemporal) |
| synapse (directed, weighted) | record link (`relates_to`, `mentions`, `part_of`, `derived_from`, `depends_on`, `contradicts`, ...) with a weight |
| directed n-simplex (n+1 all-to-all neurons, one source, one sink) | n+1 records all-to-all linked with a consistent direction; `cie.topology.cliques.directed_flag_complex` |
| dimension of a clique | `clique_dim` of a record: the highest simplex it belongs to inside the activated tissue |
| cavity (Betti numbers) | `betti1` of the activated tissue: cycles of links no directed triangle fills |
| stimulus | the records the lexical, vector and exact stages activate (the fusion seeds) |
| tissue | the seeds' one-hop neighbourhood in the record graph, bounded per seed |
| functional clique recruitment (the sandcastle) | `cie.topology.cascade.recruit`: stage 1 seeds sharing a link, stage 2 records completing a simplex with two seeds, stage 3 sinks of the highest simplices holding three activated records; same log(N) budget as the REM expansion |
| collapse / reset | nothing persists after the query except an evidence packet |
| STDP (LTP / LTD) | `cie.topology.plasticity.stdp_update`: links between records the answer used are potentiated, links that recruited unused records are depressed; weights bounded |

Two things do not map. A cavity in the cortex is a transient state of activity;
in a memory bank the graph is static between writes, so a cavity is a property
of the activated tissue, reported per query, not a store. And the direction of a
record link means "detail to context" (a fee derives from a clause, a clause is
part of a document, a record mentions an entity), which is the opposite of
"input to output" in a circuit, so the sinks of record simplices are documents,
clauses and entities rather than answers. The cascade therefore uses direction to
find simplices and their sinks, but the rerank bonus is direction-neutral
(dimension only); sink and source counts are kept as features for the learned
reranker to weigh.

## What is compared

1. **Retrieval arms** on the same questions: `hybrid+graph(bounded)` (standard REM
   expansion) versus `hybrid+cliques(topological)` (the cascade in its place) and
   `hybrid+cliques+bonus` (cascade plus a rerank bonus for records in
   high-dimensional activated simplices). Measured on the in-sample corpus by
   `cie bench retrieval` and at 10k / 100k / 1M records by `bench_scale` (hit@20,
   MRR, latency, and the median topology of the activated tissue: nodes, highest
   dimension, cavities).
2. **Plasticity**: on the 1M tenant, forty documents, three questions each for
   learning (fee, penalty, notice) and three different questions on the same
   documents for testing (signatory, liability, term). Before and after the
   STDP-like update: hit@20, MRR, latency, graph-stage time, for both arms.
   Weights are restored afterwards.
3. **Clique network versus deep network**: a learned reranker over per-candidate
   features from retrieval traces (fusion score, support, source ranks, document
   affinity, graph and clique statistics), labelled by the benchmark's target
   document and type, split by document so test questions concern unseen
   documents. The clique-cascade network (`cie.topology.cliquenet.CliqueNet`:
   linear rods, product-gated coincidence cubes with fan-in 4-6, steep-threshold
   sinks with fan-in 7-12, sparse fixed fan-in) trained by back-propagation and by a
   local reward-modulated Hebbian rule, against a deep MLP (4 x 64, ReLU) trained by
   back-propagation, and against the hand-written reranker. Metrics: AUC, hit@1,
   hit@5, MRR on the test queries; parameters; training time.

## The dynamic bank: forming new connections and shapes

The static bank only gets links at ingest (autolink, entity mentions, versions,
contradictions). `cie.topology.dynamic` lets it form links from its own use,
the structural counterpart of STDP:

* **Fire together, wire together, in context.** When an answer is produced, the
  records it cites and the packet's best-supported records *from the answer's own
  document* (two documents for a conflict answer, three for a comparison) are the
  records that fired. Every pair among them gets a `coactivated` link if none
  exists, oriented from the lower-ranked record to the higher-ranked one, so the
  record that answered is the sink of the simplex the group forms.
* **Potentiation, decay, pruning.** A pair that fires again is potentiated
  towards a cap; the other dynamic links of the fired records decay; links that
  fade below a floor are removed, and a record keeps at most a fixed number of
  dynamic links (the weakest go), so the graph stays sparse.
* **Shapes.** Repeated use turns a frequently co-used group into a full directed
  simplex with the answer as its sink; groups sharing records form larger
  complexes, and cycles no simplex fills are the bank's cavities.
  `GET /memory/shapes` reports the dynamic links, simplices by dimension,
  cavities and the strongest maximal simplices with their sinks;
  `POST /memory/shapes/reset` removes every dynamic link. Every wiring event is
  audited; dynamic links carry `evidence.dynamic`.
* **The document gate matters.** Without it (the first version) a question about
  one supplier's penalty wired the similar penalty clauses of five other
  suppliers into a 5-simplex: shortcuts between companies that have nothing to do
  with each other. What fires together in the answer's context is what is wired.
* Retrieval uses the dynamic links like any other: horizon 1 in the REM expansion
  and as ordinary links for the clique cascade. `CIE_DYNAMIC_MEMORY=true` turns
  wiring on; it is off by default until it wins on measurement.

`python -m cie.eval.bench_dynamic` measures it on the largest loaded tenant:
three question sets on the same documents (the learning questions, the same
questions re-worded, unseen questions), each measured before use, then after the
learning questions have been answered several times with wiring on, for the
standard arm, the clique arm and a deliberately weak reader (vector-only plus
graph); the shapes formed are reported and then removed.

## How to run

```
python -m cie.eval.bench_scale --remeasure 1000000     # retrieval arms incl. cliques, on the loaded 1M tenant
python -m cie.eval.bench_topology                      # plasticity + clique network vs MLP, writes eval_out/topology
python -m cie.eval.bench_dynamic                       # dynamic bank vs static, writes eval_out/dynamic
python -m cie.eval.report                              # regenerates docs/BENCHMARKS.md with the topology section
```

## Reading the results

The result tables and their interpretation are in `docs/BENCHMARKS.md`. The rule
for keeping any of this in the default pipeline is the same as for the glyph
encodings and the expander graph: it stays only if it wins on measurement.

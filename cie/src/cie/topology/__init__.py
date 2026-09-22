"""Topological memory bank: the Blue Brain clique/cavity framework (Reimann et al.,
Front. Comput. Neurosci. 2017) applied to the record graph.

Records are neurons, links are synapses. A directed simplex of dimension n is a
set of n+1 records all-to-all connected with a consistent direction (one source,
one sink); cavities are cycles of simplices that no simplex fills. Retrieval
recruits records the way a stimulus recruits cliques (low dimensions first, sinks
last); plasticity re-weights links by what retrieval actually used.
"""

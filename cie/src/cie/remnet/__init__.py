"""Experimental learned exploration over the REM business graph.

A recurrent graph network learns which memory records to explore and rank for a question. Company knowledge
comes only from company records; Blue Brain data sets the parameters of one experimental variant's synaptic
dynamics (short-term plasticity, release failures, inhibitory relations). That variant is a hypothesis under
test, not a brain simulation, and nothing here claims energy or speed benefits from biological detail.
Permissions are enforced before the network sees anything: it only receives records the requester may read.
"""

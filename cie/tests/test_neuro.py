"""Brain-wired reasoning neurons: opsin kinetics, wiring controls, clique counts, the neurons and the experiment."""

from __future__ import annotations

from collections import Counter

import numpy as np
import torch

from cie.neuro import circuit as C
from cie.neuro import experiment as X
from cie.neuro.neurons import Neurons
from cie.neuro.opsins import CHR2_OPSIN, NPHR_OPSIN, drive, kinetics, photon_flux


def test_opsins_follow_the_published_kinetics():
    assert abs(photon_flux(1.0, 470) - 2.366e15) / 2.366e15 < 1e-3
    k = kinetics(CHR2_OPSIN, mw_per_mm2=10)
    assert k["time_to_peak_ms"] < 10 and 8 < k["off_tau_ms"] < 16, "ChR2 opens within milliseconds and closes in about 10 ms"
    assert k["peak_over_steady"] > 1.5, "and desensitises under steady light"
    on = drive(CHR2_OPSIN, mw_per_mm2=10, pre_ms=500, steps=6, step_ms=20)
    off = drive(NPHR_OPSIN, mw_per_mm2=10, pre_ms=10000, steps=6, step_ms=20)  # NpHR recovers slowly: seconds
    assert np.allclose(on, 1.0, atol=0.02) and np.allclose(off, -1.0, atol=0.02), "relative to the steady current, signed"
    assert drive(CHR2_OPSIN, mw_per_mm2=10, pre_ms=0, steps=6, step_ms=20)[0] > 1.5, "a fresh pulse shows the transient"


def test_wiring_controls_keep_what_they_should():
    c = C.synthetic()
    w = C.cortex(c, C.neighbourhood(c, C.hubs(c, 1)[0], 64))
    r = C.random_like(w, 1)
    d = C.degree_preserving(w, 1)
    for x in (r, d):
        assert len(x.edges) == len(w.edges) and len({tuple(e) for e in x.edges}) == len(x.edges)
        assert all(a != b for a, b in x.edges)
    assert Counter(d.edges[:, 0]) == Counter(w.edges[:, 0]) and Counter(d.edges[:, 1]) == Counter(w.edges[:, 1])
    assert {tuple(e) for e in d.edges} != {tuple(e) for e in w.edges}
    assert w.mask()[w.edges[0, 1], w.edges[0, 0]] == 1 and w.mask().sum() == len(w.edges)
    assert len(C.dense(w).edges) == w.n * (w.n - 1)


def test_directed_cliques_are_counted_by_dimension():
    w = C.Wiring("t", 4, np.array([(a, b) for a in range(4) for b in range(4) if a < b]))
    assert C.simplices(w) == {1: 6, 2: 4, 3: 1}, "a 4-neuron directed clique is one 3-simplex"
    c = C.synthetic()
    w = C.cortex(c, C.neighbourhood(c, C.hubs(c, 1)[0], 64))
    hi = lambda x: sum(v for d, v in C.simplices(x).items() if d >= 3)  # noqa: E731
    assert hi(w) > hi(C.random_like(w, 0)), "distance-dependent wiring is richer in cliques than random wiring"


def test_neurons_follow_their_wiring_and_the_light():
    torch.manual_seed(0)
    x = X.primitives()[0]
    m = Neurons(6, 5, h=16, mask=np.zeros((16, 16), np.float32))
    with torch.no_grad():
        before = m(x)
        m.recurrent.weight.mul_(5)
        assert torch.allclose(before, m(x)), "without connections the recurrent weights do nothing"
        assert torch.allclose(before, m(x, light=torch.zeros(6, 16)))
        units = np.ones(16, bool)
        assert not torch.allclose(before, m(x, light=X.light(units, NPHR_OPSIN)[:, :16]))


def test_held_out_pairs_and_tasks():
    held = X.held_out_pairs()
    assert held == X.held_out_pairs() and len(held) == 7
    comp = X.compositions(held)
    assert comp["train"][0].shape == (486, 19) and comp["test"][0].shape == (189, 19)
    assert X.reference("EXCEPT", X.TRUE, X.UNKNOWN) == X.UNKNOWN and X.reference("AND", X.FALSE, X.UNKNOWN) == X.FALSE


def test_the_experiment_runs_end_to_end():
    res = X.run(C.synthetic(), seeds=(11,), size=24, epochs_primitives=3, epochs_compositions=3, log=lambda *_: None)
    assert {r["arm"] for r in res["runs"]} == set(X.ARMS)
    s = res["summary"]
    assert set(s["means"]) == set(X.ARMS) and "1_cortex_vs_random_held_out" in s["differences"]
    cortex = next(r for r in res["runs"] if r["arm"] == "cortex")
    assert {"random_off", "random_on", "populations"} <= set(cortex["light"])
    assert "# Brain wiring results" in X.report(res)

"""Optogenetic opsins: light-gated currents with published kinetics.

* **ChR2**, channelrhodopsin-2, the light-gated cation channel found by Nagel and Hegemann and made into a tool for
  switching neurons on by Deisseroth's lab (2026 Nobel Prize in Physiology or Medicine). Four-state model
  (C1, O1, O2, C2) with the parameters PyRhO fitted to recorded ChR2 photocurrents (Evans et al. 2016, Front.
  Neuroinform. 10:8; PyRhO 0.9.4, BSD licence).
* **NpHR**, halorhodopsin, the light-driven chloride pump used to switch neurons off. Three-state model (C, O, D) with
  PyRhO's NpHR parameters.

Rates are per millisecond and light is a photon flux density in photons/mm^2/s, as in PyRhO. Within a time step
the light is constant, so the state moves by the exact matrix exponential of the transition matrix.

The network these drive is abstract, so only the time course is taken from the models: ``drive`` is the open
fraction relative to its steady state under the same light, so 1.0 means the opsin's full steady current. How
strong that current is, in multiples of a neuron's threshold, is set by the experiment (as light power is set in a
laboratory), and the sign by the opsin: ChR2 depolarises, NpHR hyperpolarises.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.linalg import expm

PLANCK, LIGHT_SPEED = 6.62607015e-34, 2.99792458e8

# PyRhO 0.9.4 parameters.py: modelFits['4']['ChR2'] and modelFits['3']['NpHR']
CHR2 = {"gam": 0.00742, "phi_m": 2.33e17, "k1": 4.15, "k2": 0.868, "p": 0.833, "Gf0": 0.0373, "k_f": 0.0581, "Gb0": 0.0161,
        "k_b": 0.063, "q": 1.94, "Gd1": 0.105, "Gd2": 0.0138, "Gr0": 0.00033}
NPHR = {"phi_m": 1.32e18, "k_a": 0.01, "k_r": 0.01, "p": 0.793, "q": 0.793, "Gd": 0.1, "Gr0": 0.0002}


def photon_flux(mw_per_mm2: float, wavelength_nm: float) -> float:
    """Light power density as photons/mm^2/s."""
    return mw_per_mm2 * 1e-3 / (PLANCK * LIGHT_SPEED / (wavelength_nm * 1e-9))


def _hill(phi: float, phi_m: float, n: float) -> float:
    return phi ** n / (phi ** n + phi_m ** n) if phi > 0 else 0.0


@dataclass(frozen=True)
class Opsin:
    name: str
    sign: float  # +1 depolarising, -1 hyperpolarising
    wavelength_nm: float

    def generator(self, phi: float) -> np.ndarray:
        """The transition matrix Q (ds/dt = Q s) under light ``phi``."""
        if self.name == "ChR2":
            c = CHR2
            hp, hq = _hill(phi, c["phi_m"], c["p"]), _hill(phi, c["phi_m"], c["q"])
            ga1, ga2 = c["k1"] * hp, c["k2"] * hp
            gf, gb = c["Gf0"] + c["k_f"] * hq, c["Gb0"] + c["k_b"] * hq
            gd1, gd2, gr = c["Gd1"], c["Gd2"], c["Gr0"]
            return np.array([[-ga1, gd1, 0, gr],                 # C1
                             [ga1, -(gd1 + gf), gb, 0],          # O1
                             [0, gf, -(gd2 + gb), ga2],          # O2
                             [0, 0, gd2, -(ga2 + gr)]])          # C2
        c = NPHR
        ga = c["k_a"] * _hill(phi, c["phi_m"], c["p"])
        gr = c["Gr0"] + c["k_r"] * _hill(phi, c["phi_m"], c["q"])
        gd = c["Gd"]
        return np.array([[-ga, 0, gr],   # C
                         [ga, -gd, 0],   # O
                         [0, gd, -gr]])  # D

    def dark(self) -> np.ndarray:
        s = np.zeros(4 if self.name == "ChR2" else 3)
        s[0] = 1.0
        return s

    def open_fraction(self, s: np.ndarray) -> np.ndarray:
        """Conducting fraction: O1 + gamma O2 for ChR2, O for NpHR. ``s`` is (..., states)."""
        if self.name == "ChR2":
            return s[..., 1] + CHR2["gam"] * s[..., 2]
        return s[..., 1]

    def steady_open(self, phi: float) -> float:
        q = self.generator(phi)
        w, v = np.linalg.eig(q)
        s = np.real(v[:, np.argmin(np.abs(w))])
        return float(self.open_fraction(s / s.sum()))

    def trace(self, phi_per_step: np.ndarray, dt_ms: float, substeps: int = 20) -> np.ndarray:
        """Mean open fraction in each step for a light protocol (one photon flux per step), from the dark state."""
        s = self.dark()
        out = np.zeros(len(phi_per_step))
        cache: dict[float, np.ndarray] = {}
        for i, phi in enumerate(phi_per_step):
            phi = float(phi)
            if phi not in cache:
                cache[phi] = expm(self.generator(phi) * dt_ms / substeps)
            m, acc = cache[phi], 0.0
            for _ in range(substeps):
                s = m @ s
                acc += float(self.open_fraction(s))
            out[i] = acc / substeps
        return out


CHR2_OPSIN = Opsin("ChR2", +1.0, 470.0)
NPHR_OPSIN = Opsin("NpHR", -1.0, 590.0)
OPSINS = {"ChR2": CHR2_OPSIN, "NpHR": NPHR_OPSIN}


def drive(opsin: Opsin, *, mw_per_mm2: float, pre_ms: float, steps: int, step_ms: float) -> np.ndarray:
    """The signed drive during ``steps`` steps of ``step_ms`` when the light came on ``pre_ms`` before the first,
    relative to the opsin's steady current under that light (so +1 or -1 at steady state)."""
    phi = photon_flux(mw_per_mm2, opsin.wavelength_nm)
    n_pre = int(round(pre_ms / step_ms))
    f = opsin.trace(np.full(n_pre + steps, phi), step_ms)[n_pre:]
    return opsin.sign * f / opsin.steady_open(phi)


def kinetics(opsin: Opsin, *, mw_per_mm2: float = 10.0, on_ms: float = 500.0, off_ms: float = 200.0, dt_ms: float = 0.1) -> dict:
    """What the model does under a light pulse: time to peak, peak over steady state, decay time after light off."""
    phi = photon_flux(mw_per_mm2, opsin.wavelength_nm)
    n_on, n_off = int(on_ms / dt_ms), int(off_ms / dt_ms)
    f = opsin.trace(np.r_[np.full(n_on, phi), np.zeros(n_off)], dt_ms, substeps=1)
    peak = int(np.argmax(f[:n_on]))
    end = f[n_on - 1]
    after = f[n_on:]
    tau_off = float(np.argmax(after < end / np.e) * dt_ms) if (after < end / np.e).any() else float("nan")
    return {"opsin": opsin.name, "light_mw_mm2": mw_per_mm2, "photons_mm2_s": phi, "time_to_peak_ms": round(peak * dt_ms, 2),
            "peak_over_steady": round(float(f[peak] / max(end, 1e-12)), 3), "off_tau_ms": round(tau_off, 2),
            "steady_open_fraction": round(opsin.steady_open(phi), 5)}

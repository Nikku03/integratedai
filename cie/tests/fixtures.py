"""Test fixtures re-exported from the package so the CLI never depends on the test tree."""

from cie.eval.synth import CONTRACT_SECTIONS, make_pdf, rasterize_pdf

__all__ = ["CONTRACT_SECTIONS", "make_pdf", "rasterize_pdf"]

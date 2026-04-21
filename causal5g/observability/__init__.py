"""
causal5g.observability
======================
Observability surface for the Causal5G pipeline — Prometheus metrics,
structured logging hooks, and exposition-format rendering.

Day 15: Prometheus metrics exporter. The public entrypoint is
``causal5g.observability.metrics``. Importing this package is cheap;
the ``prometheus_client`` dependency is imported lazily inside the
metrics module so environments that do not scrape (patent demo, CI,
unit tests) pay zero import cost.
"""

from causal5g.observability import metrics  # noqa: F401

__all__ = ["metrics"]

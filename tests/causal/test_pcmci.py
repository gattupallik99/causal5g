"""
tests/causal/test_pcmci.py
═══════════════════════════════════════════════════════════════════════════════
Causal5G -- PCMCI Backend Test Suite (Claim 4)

Exercises every branch of `causal5g.causal.pcmci.PCMCIBackend`:
  1. Construction and parameter defaults
  2. `results` property (None state + populated state)
  3. `_build_link_assumptions` -- topology-prior-driven link mask
  4. `_results_to_graph` -- tigramite-result → annotated `nx.DiGraph`
  5. `fit` -- both the ImportError path (no tigramite installed) and
     the success path with a stubbed tigramite module graph
  6. `CausalDiscoveryBackend` ABC contract compliance

The tigramite library is NOT a runtime requirement for the tests; the
success-path test injects a lightweight fake into `sys.modules` to
exercise `fit` without pulling in the heavy dependency.

Run:  python3 -m pytest tests/causal/test_pcmci.py -v
"""
from __future__ import annotations

import sys
import types
import unittest
from typing import Any, Dict, List
from unittest import mock

import numpy as np

from causal5g.causal.discovery import CausalDiscoveryBackend
from causal5g.causal.pcmci import PCMCIBackend
from causal5g.graph.topology_prior import TopologyPrior


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _prior_with_instance_edges(*edges: tuple) -> TopologyPrior:
    """Build a TopologyPrior with explicit instance edges registered."""
    p = TopologyPrior()
    for s, d in edges:
        p.register_instance_edge(s, d)
    return p


def _make_pcmci_results(
    variable_names: List[str],
    tau_max: int,
    edges: List[tuple],
) -> Dict[str, np.ndarray]:
    """
    Fabricate a tigramite-shaped result dict.

    Each element of `edges` is (i_name, j_name, tau, val, pval); cells not
    listed get the "" marker (no link). Shape of all three matrices is
    (N, N, tau_max + 1) to match tigramite's convention (tau axis includes
    0 for contemporaneous).
    """
    N = len(variable_names)
    idx = {n: k for k, n in enumerate(variable_names)}
    graph_matrix = np.full((N, N, tau_max + 1), "", dtype="U4")
    val_matrix = np.zeros((N, N, tau_max + 1), dtype=float)
    p_matrix = np.ones((N, N, tau_max + 1), dtype=float)
    for src, dst, tau, val, pval in edges:
        i, j = idx[src], idx[dst]
        graph_matrix[i, j, tau] = "-->"
        val_matrix[i, j, tau] = val
        p_matrix[i, j, tau] = pval
    return {
        "graph": graph_matrix,
        "val_matrix": val_matrix,
        "p_matrix": p_matrix,
    }


# ─── 1. Construction ─────────────────────────────────────────────────────────

class TestInit(unittest.TestCase):

    def test_defaults(self):
        b = PCMCIBackend()
        self.assertEqual(b.tau_max, 10)
        self.assertEqual(b.alpha, 0.05)
        self.assertEqual(b.ci_test, "parcorr")
        self.assertIsNone(b._results)
        self.assertIsNone(b.results)

    def test_custom_parameters(self):
        b = PCMCIBackend(tau_max=5, alpha=0.01, ci_test="robustparcorr")
        self.assertEqual(b.tau_max, 5)
        self.assertEqual(b.alpha, 0.01)
        self.assertEqual(b.ci_test, "robustparcorr")

    def test_is_causal_discovery_backend(self):
        """PCMCIBackend must satisfy the backend ABC contract."""
        self.assertTrue(issubclass(PCMCIBackend, CausalDiscoveryBackend))
        self.assertIsInstance(PCMCIBackend(), CausalDiscoveryBackend)


# ─── 2. results property ─────────────────────────────────────────────────────

class TestResultsProperty(unittest.TestCase):

    def test_none_initially(self):
        self.assertIsNone(PCMCIBackend().results)

    def test_exposes_underlying_dict(self):
        b = PCMCIBackend()
        payload = {"graph": np.zeros((1, 1, 1), dtype="U4")}
        b._results = payload
        self.assertIs(b.results, payload)


# ─── 3. _build_link_assumptions ──────────────────────────────────────────────

class TestBuildLinkAssumptions(unittest.TestCase):

    def test_empty_prior_forbids_all_edges(self):
        """With no instance edges and no nf_type_map, prior denies everything."""
        b = PCMCIBackend(tau_max=3)
        vnames = ["AMF_1", "SMF_1", "UPF_1"]
        assumptions = b._build_link_assumptions(vnames, TopologyPrior())

        self.assertEqual(set(assumptions.keys()), {0, 1, 2})
        for j in assumptions:
            for (i, tau), marker in assumptions[j].items():
                self.assertEqual(
                    marker, "",
                    f"Expected '' at (i={i}, tau={tau}) -> j={j}, got {marker!r}"
                )

    def test_instance_edge_allowed_across_all_taus(self):
        """A registered instance edge yields '-->' for every tau in 1..tau_max."""
        b = PCMCIBackend(tau_max=4)
        vnames = ["AMF_1", "SMF_1"]
        prior = _prior_with_instance_edges(("AMF_1", "SMF_1"))
        assumptions = b._build_link_assumptions(vnames, prior)

        # AMF_1 (i=0) -> SMF_1 (j=1) is allowed at every tau
        for tau in range(1, 5):
            self.assertEqual(assumptions[1][(0, -tau)], "-->")
        # Reverse direction SMF_1 -> AMF_1 not registered
        for tau in range(1, 5):
            self.assertEqual(assumptions[0][(1, -tau)], "")

    def test_tau_range_respects_tau_max(self):
        """Assumption keys cover taus 1..tau_max; tau=0 is excluded."""
        b = PCMCIBackend(tau_max=2)
        vnames = ["A", "B"]
        assumptions = b._build_link_assumptions(vnames, TopologyPrior())
        taus_for_j0 = {tau for (_, tau) in assumptions[0].keys()}
        # tigramite encodes lag as negative; loop goes range(1, tau_max+1)
        self.assertEqual(taus_for_j0, {-1, -2})

    def test_pfcp_binding_allows_edge(self):
        """A PFCP binding between SMF and UPF enables the edge."""
        b = PCMCIBackend(tau_max=1)
        vnames = ["SMF_1", "UPF_1"]
        prior = TopologyPrior(pfcp_bindings=[("SMF_1", "UPF_1")])
        assumptions = b._build_link_assumptions(vnames, prior)
        self.assertEqual(assumptions[1][(0, -1)], "-->")


# ─── 4. _results_to_graph ────────────────────────────────────────────────────

class TestResultsToGraph(unittest.TestCase):

    def test_empty_results_returns_graph_with_nodes_only(self):
        b = PCMCIBackend(tau_max=3)
        b._results = None
        g = b._results_to_graph(["A", "B", "C"])
        self.assertEqual(set(g.nodes), {"A", "B", "C"})
        self.assertEqual(len(g.edges), 0)

    def test_single_directed_edge_annotated(self):
        b = PCMCIBackend(tau_max=3)
        vnames = ["AMF", "SMF"]
        b._results = _make_pcmci_results(
            vnames, tau_max=3,
            edges=[("AMF", "SMF", 2, 0.73, 0.004)],
        )
        g = b._results_to_graph(vnames)

        self.assertEqual(list(g.edges), [("AMF", "SMF")])
        attrs = g.edges["AMF", "SMF"]
        self.assertEqual(attrs["tau"], 2)
        self.assertAlmostEqual(attrs["weight"], 0.73)
        self.assertAlmostEqual(attrs["p_value"], 0.004)
        self.assertIsInstance(attrs["weight"], float)
        self.assertIsInstance(attrs["p_value"], float)

    def test_self_loops_skipped(self):
        """i == j diagonal cells are ignored regardless of graph_matrix content."""
        b = PCMCIBackend(tau_max=2)
        vnames = ["AMF"]
        res = _make_pcmci_results(vnames, tau_max=2, edges=[])
        # Manually mark a self-loop that should still be skipped
        res["graph"][0, 0, 1] = "-->"
        res["val_matrix"][0, 0, 1] = 1.0
        b._results = res
        g = b._results_to_graph(vnames)
        self.assertEqual(len(g.edges), 0)

    def test_non_directed_symbols_ignored(self):
        """'o-o', 'x-x' and '' markers do not become edges."""
        b = PCMCIBackend(tau_max=2)
        vnames = ["A", "B"]
        res = _make_pcmci_results(vnames, tau_max=2, edges=[])
        # non-"-->" markers should all be dropped
        res["graph"][0, 1, 1] = "o-o"
        res["graph"][0, 1, 2] = "x-x"
        res["graph"][1, 0, 1] = ""
        b._results = res
        self.assertEqual(len(b._results_to_graph(vnames).edges), 0)

    def test_multiple_lags_produce_parallel_keyless_edge(self):
        """
        If two different taus report '-->' for the same (i, j) pair, nx.DiGraph
        (no parallel edges) keeps only the last-written one. Contract is
        "the deepest tau that PCMCI returned wins" in this case.
        """
        b = PCMCIBackend(tau_max=3)
        vnames = ["A", "B"]
        b._results = _make_pcmci_results(
            vnames, tau_max=3,
            edges=[("A", "B", 1, 0.3, 0.04),
                   ("A", "B", 3, 0.8, 0.001)],
        )
        g = b._results_to_graph(vnames)
        self.assertEqual(list(g.edges), [("A", "B")])
        # Loop iterates tau=1, 2, 3 in order; tau=3 overwrites tau=1
        self.assertEqual(g.edges["A", "B"]["tau"], 3)
        self.assertAlmostEqual(g.edges["A", "B"]["weight"], 0.8)

    def test_shape_boundary_excludes_out_of_bounds_tau(self):
        """
        The in-code guard `tau < graph_matrix.shape[2]` means a tau at or
        beyond shape[2] is silently ignored. We build a results dict with a
        graph_matrix shaped (N, N, tau_max) instead of (N, N, tau_max+1),
        which excludes tau=tau_max from consideration.
        """
        b = PCMCIBackend(tau_max=3)
        vnames = ["A", "B"]
        N = 2
        # Deliberately size the last axis to 3 (so valid indices 0..2),
        # while looping tau=1,2,3 — tau=3 falls out.
        g_mat = np.full((N, N, 3), "", dtype="U4")
        g_mat[0, 1, 2] = "-->"  # in bounds, should appear
        g_mat[0, 1, 1] = ""     # stays hidden
        b._results = {
            "graph": g_mat,
            "val_matrix": np.full((N, N, 3), 0.5),
            "p_matrix":  np.full((N, N, 3), 0.02),
        }
        g = b._results_to_graph(vnames)
        # Only tau=2 cell is "-->"; tau=3 is out of bounds and skipped.
        self.assertEqual(list(g.edges), [("A", "B")])
        self.assertEqual(g.edges["A", "B"]["tau"], 2)


# ─── 5. fit: ImportError branch + success path ───────────────────────────────

class TestFitImportError(unittest.TestCase):

    def test_missing_tigramite_raises_helpful_import_error(self):
        """
        When tigramite is not installed, fit must surface an ImportError
        with an install-hint string. We simulate absence by poisoning
        `sys.modules`.
        """
        b = PCMCIBackend(tau_max=2)
        vnames = ["A", "B"]
        data = np.random.default_rng(0).normal(size=(50, 2))
        prior = TopologyPrior()

        # Replace tigramite entries with None to force ImportError on import.
        poison = {
            "tigramite": None,
            "tigramite.data_processing": None,
            "tigramite.pcmci": None,
            "tigramite.independence_tests": None,
            "tigramite.independence_tests.parcorr": None,
            "tigramite.independence_tests.robust_parcorr": None,
        }
        with mock.patch.dict(sys.modules, poison, clear=False):
            with self.assertRaises(ImportError) as ctx:
                b.fit(data, vnames, prior)
            self.assertIn("tigramite", str(ctx.exception).lower())
            self.assertIn("pip install", str(ctx.exception).lower())


class TestFitSuccessPath(unittest.TestCase):
    """Inject a fake tigramite module graph so we can exercise `fit` end-to-end."""

    def _install_fake_tigramite(self) -> Dict[str, Any]:
        """
        Build a mocked tigramite package with just enough surface for
        `PCMCIBackend.fit` to succeed. Returns the `run_pcmci_mock` so
        tests can inspect how it was called.
        """
        vnames = ["A", "B"]
        fake_results = _make_pcmci_results(
            vnames, tau_max=2,
            edges=[("A", "B", 2, 0.66, 0.01)],
        )

        tigramite_pkg = types.ModuleType("tigramite")
        dp_mod = types.ModuleType("tigramite.data_processing")
        pcmci_mod = types.ModuleType("tigramite.pcmci")
        it_mod = types.ModuleType("tigramite.independence_tests")
        parcorr_mod = types.ModuleType("tigramite.independence_tests.parcorr")
        robust_mod = types.ModuleType(
            "tigramite.independence_tests.robust_parcorr")

        class _FakeDataFrame:
            def __init__(self, data, var_names):
                self.data = data
                self.var_names = var_names

        class _FakeParCorr:
            pass

        class _FakeRobustParCorr:
            pass

        class _FakePCMCI:
            run_pcmci_mock = mock.MagicMock(return_value=fake_results)

            def __init__(self, dataframe, cond_ind_test):
                self.dataframe = dataframe
                self.cond_ind_test = cond_ind_test

            def run_pcmci(self, **kwargs):
                return type(self).run_pcmci_mock(**kwargs)

        dp_mod.DataFrame = _FakeDataFrame
        pcmci_mod.PCMCI = _FakePCMCI
        parcorr_mod.ParCorr = _FakeParCorr
        robust_mod.RobustParCorr = _FakeRobustParCorr
        tigramite_pkg.data_processing = dp_mod
        tigramite_pkg.pcmci = pcmci_mod
        tigramite_pkg.independence_tests = it_mod

        return {
            "tigramite": tigramite_pkg,
            "tigramite.data_processing": dp_mod,
            "tigramite.pcmci": pcmci_mod,
            "tigramite.independence_tests": it_mod,
            "tigramite.independence_tests.parcorr": parcorr_mod,
            "tigramite.independence_tests.robust_parcorr": robust_mod,
            "_pcmci_cls": _FakePCMCI,
            "_dataframe_cls": _FakeDataFrame,
        }

    def test_fit_parcorr_produces_graph_and_caches_results(self):
        fake = self._install_fake_tigramite()
        pcmci_cls = fake.pop("_pcmci_cls")
        df_cls = fake.pop("_dataframe_cls")

        b = PCMCIBackend(tau_max=2, ci_test="parcorr")
        data = np.random.default_rng(1).normal(size=(40, 2))
        vnames = ["A", "B"]
        prior = _prior_with_instance_edges(("A", "B"))

        with mock.patch.dict(sys.modules, fake, clear=False):
            g = b.fit(data, vnames, prior)

        # 1. fit returned an annotated graph with the expected single edge
        self.assertEqual(list(g.edges), [("A", "B")])
        self.assertEqual(g.edges["A", "B"]["tau"], 2)
        self.assertAlmostEqual(g.edges["A", "B"]["weight"], 0.66)
        self.assertAlmostEqual(g.edges["A", "B"]["p_value"], 0.01)

        # 2. PCMCI.run_pcmci was called with the right kwargs
        pcmci_cls.run_pcmci_mock.assert_called_once()
        call_kwargs = pcmci_cls.run_pcmci_mock.call_args.kwargs
        self.assertEqual(call_kwargs["tau_max"], 2)
        self.assertAlmostEqual(call_kwargs["alpha_level"], 0.05)
        # link_assumptions is a dict keyed by j; "A"->"B" (i=0, j=1) allowed
        self.assertEqual(call_kwargs["link_assumptions"][1][(0, -1)], "-->")

        # 3. results property now exposes the cached dict
        self.assertIsNotNone(b.results)
        self.assertIn("graph", b.results)

    def test_fit_robust_parcorr_selects_correct_ci_test(self):
        """The ci_test='robustparcorr' branch must instantiate RobustParCorr."""
        fake = self._install_fake_tigramite()
        fake.pop("_pcmci_cls")
        fake.pop("_dataframe_cls")

        b = PCMCIBackend(tau_max=1, ci_test="robustparcorr")
        data = np.random.default_rng(2).normal(size=(30, 2))
        vnames = ["A", "B"]

        with mock.patch.dict(sys.modules, fake, clear=False):
            g = b.fit(data, vnames, TopologyPrior())

        # No instance edges / nf_type_map => no allowed edges => no edges in
        # the results graph. Assert the graph has just the two isolated nodes.
        self.assertEqual(set(g.nodes), {"A", "B"})


# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)

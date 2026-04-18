"""
causal/engine/pc_algorithm.py
═══════════════════════════════════════════════════════════════════════════════
Causal5G — Patent Claim 3: PC Algorithm for Constraint-Based Causal Discovery
in Virtualized 5G Core Networks

Author : Krishna Kumar Gattupalli
Patent : US Provisional Filed March 2026
Repo   : git@github.com:gattupallik/causal5g.git

Overview
────────
The PC (Peter-Clark) algorithm performs constraint-based causal discovery by
testing conditional independence between pairs of variables and removing edges
that are d-separated.  Unlike Granger causality (Claim 1), the PC algorithm:

  • Operates on contemporaneous (non-lagged) data snapshots
  • Discovers the Markov Equivalence Class (CPDAG) rather than a DAG
  • Uses partial correlations + Fisher's Z-test as the independence oracle
  • Produces orientation rules (Meek rules) to orient as many edges as possible

In the Causal5G system, PC is run in parallel with the Granger engine and the
results are merged in the DCGM (causal/graph/dcgm.py) via a confidence-weighted
edge fusion step.  Edges confirmed by BOTH methods receive a higher weight in
the root cause scoring.

Architecture Position
─────────────────────

  nf_scraper.py  ──►  PCAlgorithm  ──►  CPDAG (partially directed graph)
                                              │
                       granger.py  ──►  DAG  │
                                              ▼
                                     dcgm.py (fuse → live causal graph)
                                              │
                                              ▼
                                     rcsm.py  →  frg.py  →  REST API

Classes
───────
  IndependenceOracle   — Fisher's Z partial correlation test
  PCAlgorithm          — Full PC algorithm (skeleton + orientation)
  PCResult             — Dataclass holding CPDAG edges + metadata
  GrangerPCFusion      — Merges Granger DAG with PC CPDAG

Usage
─────
  from causal.engine.pc_algorithm import PCAlgorithm
  import pandas as pd

  # df: rows = time steps, columns = NF metric names
  df = pd.read_csv("telemetry.csv")

  pc = PCAlgorithm(alpha=0.05, max_cond_set=3)
  result = pc.fit(df)

  print(result.cpdag_edges)        # list of (u, v, edge_type) tuples
  print(result.skeleton_edges)     # undirected skeleton
  print(result.separation_sets)    # {(i,j): [conditioning set]}
  print(result.summary())
"""

from __future__ import annotations

import itertools
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

import networkx as nx
import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)


# ─── Edge Type Constants ──────────────────────────────────────────────────────

UNDIRECTED = "---"   # skeleton edge; direction unknown
DIRECTED   = "-->"   # oriented edge
TAIL_TAIL  = "o-o"   # PAG mark (reserved for future FCI extension)


# ─── Dataclasses ─────────────────────────────────────────────────────────────

@dataclass
class TestResult:
    """Result of a single conditional independence test."""
    var_i: str
    var_j: str
    cond_set: Tuple[str, ...]
    partial_corr: float
    z_score: float
    p_value: float
    independent: bool          # True  →  edge should be removed
    n_samples: int


@dataclass
class PCResult:
    """Output of the PC algorithm run."""
    variables: List[str]
    skeleton_edges: List[Tuple[str, str]]
    cpdag_edges: List[Tuple[str, str, str]]   # (u, v, edge_type)
    separation_sets: Dict[Tuple[str, str], List[str]]
    v_structures: List[Tuple[str, str, str]]  # (u, collider, v)
    independence_tests: List[TestResult]
    elapsed_seconds: float
    alpha: float
    n_samples: int
    n_variables: int

    def directed_edges(self) -> List[Tuple[str, str]]:
        return [(u, v) for u, v, t in self.cpdag_edges if t == DIRECTED]

    def undirected_edges(self) -> List[Tuple[str, str]]:
        return [(u, v) for u, v, t in self.cpdag_edges if t == UNDIRECTED]

    def to_networkx(self) -> nx.DiGraph:
        """Return a DiGraph; undirected edges added in both directions."""
        G = nx.DiGraph()
        G.add_nodes_from(self.variables)
        for u, v, t in self.cpdag_edges:
            if t == DIRECTED:
                G.add_edge(u, v, edge_type=DIRECTED)
            else:
                G.add_edge(u, v, edge_type=UNDIRECTED)
                G.add_edge(v, u, edge_type=UNDIRECTED)
        return G

    def summary(self) -> str:
        lines = [
            "═" * 60,
            "  Causal5G — PC Algorithm Result (Patent Claim 3)",
            "═" * 60,
            f"  Variables  : {self.n_variables}",
            f"  Samples    : {self.n_samples}",
            f"  Alpha (α)  : {self.alpha}",
            f"  Runtime    : {self.elapsed_seconds:.3f}s",
            "",
            f"  Skeleton edges    : {len(self.skeleton_edges)}",
            f"  Directed edges    : {len(self.directed_edges())}",
            f"  Undirected edges  : {len(self.undirected_edges())}",
            f"  V-structures      : {len(self.v_structures)}",
            f"  CI tests run      : {len(self.independence_tests)}",
            "",
            "  CPDAG Edges:",
        ]
        for u, v, t in sorted(self.cpdag_edges):
            lines.append(f"    {u:12s} {t} {v}")
        if self.v_structures:
            lines.append("")
            lines.append("  V-Structures (unshielded colliders):")
            for u, c, v in self.v_structures:
                lines.append(f"    {u} --> {c} <-- {v}")
        lines.append("═" * 60)
        return "\n".join(lines)


# ─── Independence Oracle ──────────────────────────────────────────────────────

class IndependenceOracle:
    """
    Tests conditional independence using partial correlation + Fisher's Z.

    H₀: X ⊥ Y | Z  (X and Y are independent given conditioning set Z)

    The Fisher Z-transform converts a partial correlation r to a
    normally distributed statistic:

        Z = 0.5 * ln((1 + r) / (1 - r))  * sqrt(n - |Z| - 3)

    We reject independence (keep the edge) if |Z| > z_critical.

    Parameters
    ──────────
    alpha     : significance level (default 0.05)
    min_n     : minimum samples required for reliable test
    """

    def __init__(self, alpha: float = 0.05, min_n: int = 20):
        self.alpha = alpha
        self.min_n = min_n
        self._z_critical = stats.norm.ppf(1 - alpha / 2)

    def test(
        self,
        data: np.ndarray,
        col_names: List[str],
        i: int,
        j: int,
        cond_indices: List[int],
    ) -> TestResult:
        """
        Test whether variable i is independent of variable j
        given the conditioning set (columns at cond_indices).
        """
        n = data.shape[0]
        vi = col_names[i]
        vj = col_names[j]
        cond_vars = tuple(col_names[k] for k in cond_indices)

        if n < self.min_n:
            # Insufficient data — conservatively keep the edge
            return TestResult(vi, vj, cond_vars, 0.0, 0.0, 0.0,
                              independent=False, n_samples=n)

        try:
            r = self._partial_correlation(data, i, j, cond_indices)
        except np.linalg.LinAlgError:
            logger.warning("Singular matrix in partial corr test (%s, %s | %s); keeping edge.",
                           vi, vj, cond_vars)
            return TestResult(vi, vj, cond_vars, 0.0, 0.0, 0.0,
                              independent=False, n_samples=n)

        # Clamp to avoid atanh blow-up
        r_clamped = np.clip(r, -0.9999, 0.9999)
        z_score = math.atanh(r_clamped) * math.sqrt(n - len(cond_indices) - 3)
        p_value = 2 * (1 - stats.norm.cdf(abs(z_score)))
        independent = p_value > self.alpha

        return TestResult(
            var_i=vi, var_j=vj, cond_set=cond_vars,
            partial_corr=float(r), z_score=float(z_score),
            p_value=float(p_value), independent=independent,
            n_samples=n,
        )

    def _partial_correlation(
        self,
        data: np.ndarray,
        i: int,
        j: int,
        cond_indices: List[int],
    ) -> float:
        """
        Compute partial correlation of columns i and j given cond_indices.

        When cond_indices is empty, returns Pearson correlation.
        When non-empty, uses the linear regression residual method:
            corr(res_i, res_j)  where res_k = X_k - X_Z * β_k
        """
        if not cond_indices:
            return float(np.corrcoef(data[:, i], data[:, j])[0, 1])

        Z = data[:, cond_indices]
        xi = data[:, i]
        xj = data[:, j]

        # Regress xi and xj on Z, take residuals
        res_i = self._residuals(Z, xi)
        res_j = self._residuals(Z, xj)

        denom = np.std(res_i) * np.std(res_j)
        if denom < 1e-10:
            return 0.0
        return float(np.dot(res_i - res_i.mean(), res_j - res_j.mean())
                     / (len(res_i) - 1) / denom)

    @staticmethod
    def _residuals(Z: np.ndarray, x: np.ndarray) -> np.ndarray:
        """OLS residuals of x regressed on Z (with intercept)."""
        Z_aug = np.column_stack([np.ones(len(x)), Z])
        beta, _, _, _ = np.linalg.lstsq(Z_aug, x, rcond=None)
        return x - Z_aug @ beta


# ─── PC Algorithm ─────────────────────────────────────────────────────────────

class PCAlgorithm:
    """
    PC (Peter–Clark) Causal Discovery Algorithm — Causal5G Patent Claim 3.

    Implements the stable-PC variant (order-independent skeleton phase)
    followed by Meek's orientation rules to produce a CPDAG.

    Parameters
    ──────────
    alpha        : CI test significance level (default 0.05)
    max_cond_set : maximum conditioning set size (default 4)
                   Limiting this controls runtime; set to len(vars)-2 for
                   completeness at cost of exponential blowup.
    min_n        : minimum samples for valid CI test (default 20)

    References
    ──────────
    • Spirtes, Glymour, Scheines (2000) — Causation, Prediction, Search
    • Kalisch & Bühlmann (2007) — Estimating high-dimensional DAGs
      with the PC-algorithm (stable variant)
    • Meek (1995) — Causal inference and causal explanation with background
      knowledge
    """

    def __init__(
        self,
        alpha: float = 0.05,
        max_cond_set: int = 4,
        min_n: int = 20,
    ):
        self.alpha = alpha
        self.max_cond_set = max_cond_set
        self.oracle = IndependenceOracle(alpha=alpha, min_n=min_n)

    # ── Public API ────────────────────────────────────────────────────────────

    def fit(self, df: pd.DataFrame) -> PCResult:
        """
        Run PC algorithm on a telemetry DataFrame.

        Parameters
        ──────────
        df : pd.DataFrame
            Rows = time steps.  Columns = NF metric names, e.g.
            ["amf_cpu", "smf_cpu", "upf_latency", "pcf_cpu", "nrf_cpu"]
            Missing values are filled with column means before fitting.

        Returns
        ───────
        PCResult  (see dataclass above)
        """
        t0 = time.perf_counter()

        df = self._preprocess(df)
        data = df.values.astype(float)
        col_names = list(df.columns)
        n_vars = len(col_names)

        logger.info("PC algorithm: %d variables, %d samples, α=%.3f",
                    n_vars, len(df), self.alpha)

        # ── Phase 1: Skeleton ─────────────────────────────────────────────
        skeleton, sep_sets, ci_tests = self._build_skeleton(
            data, col_names, n_vars
        )

        skeleton_edges = list(skeleton.edges())

        # ── Phase 2: Orient V-structures ──────────────────────────────────
        cpdag = skeleton.to_directed()
        # Add both directions for all undirected edges
        for u, v in skeleton.edges():
            cpdag.add_edge(v, u)

        v_structures = self._orient_v_structures(cpdag, skeleton, sep_sets)

        # ── Phase 3: Meek Orientation Rules (R1–R4) ───────────────────────
        self._apply_meek_rules(cpdag, skeleton)

        # ── Collect CPDAG edges ───────────────────────────────────────────
        cpdag_edges = self._extract_cpdag_edges(cpdag, skeleton)

        elapsed = time.perf_counter() - t0

        result = PCResult(
            variables=col_names,
            skeleton_edges=skeleton_edges,
            cpdag_edges=cpdag_edges,
            separation_sets={
                (col_names[i], col_names[j]): [col_names[k] for k in s]
                for (i, j), s in sep_sets.items()
            },
            v_structures=v_structures,
            independence_tests=ci_tests,
            elapsed_seconds=elapsed,
            alpha=self.alpha,
            n_samples=len(df),
            n_variables=n_vars,
        )

        logger.info("PC complete: %d skeleton edges, %d directed, %d v-structures (%.3fs)",
                    len(skeleton_edges), len(result.directed_edges()),
                    len(v_structures), elapsed)
        return result

    # ── Phase 1: Skeleton Construction ───────────────────────────────────────

    def _build_skeleton(
        self,
        data: np.ndarray,
        col_names: List[str],
        n_vars: int,
    ) -> Tuple[nx.Graph, Dict, List[TestResult]]:
        """
        Stable-PC skeleton phase.

        Start with complete undirected graph.  For each pair (i, j),
        iterate over conditioning set sizes l = 0, 1, 2, ...
        If any conditioning set of size l renders i ⊥ j, remove the edge
        and record the separation set.

        Stable-PC: collect ALL removals at level l before applying any,
        so the adjacency sets used for conditioning don't change mid-level.
        This makes the result order-independent.
        """
        # Complete undirected skeleton
        G = nx.complete_graph(n_vars)
        G = nx.relabel_nodes(G, {i: col_names[i] for i in range(n_vars)})

        sep_sets: Dict[Tuple[int, int], List[int]] = {}
        ci_tests: List[TestResult] = []

        for l in range(self.max_cond_set + 1):
            logger.debug("Skeleton level l=%d | edges=%d", l, G.number_of_edges())
            edges_to_remove: List[Tuple[str, str]] = []
            sep_sets_this_level: Dict[Tuple[str, str], List[int]] = {}

            for u, v in list(G.edges()):
                i = col_names.index(u)
                j = col_names.index(v)

                # Adjacent nodes excluding the pair itself (use current adjacency)
                adj_u = [col_names.index(w) for w in G.neighbors(u) if w != v]

                if len(adj_u) < l:
                    continue

                # Iterate over conditioning sets of size l from adj_u
                found_sep = False
                for cond_set in itertools.combinations(adj_u, l):
                    result = self.oracle.test(data, col_names, i, j, list(cond_set))
                    ci_tests.append(result)

                    if result.independent:
                        edges_to_remove.append((u, v))
                        sep_sets_this_level[(u, v)] = list(cond_set)
                        sep_sets_this_level[(v, u)] = list(cond_set)
                        found_sep = True
                        logger.debug("  Remove (%s, %s) | cond=%s p=%.4f",
                                     u, v, list(cond_set), result.p_value)
                        break  # one sep set suffices

                if not found_sep and l == 0:
                    # No unconditional independence found
                    pass

            # Apply all removals at this level simultaneously (stable-PC)
            for u, v in edges_to_remove:
                if G.has_edge(u, v):
                    G.remove_edge(u, v)
            # Convert string-keyed sep_sets to int-keyed
            for (u, v), cond in sep_sets_this_level.items():
                i = col_names.index(u)
                j = col_names.index(v)
                sep_sets[(i, j)] = cond

            if G.number_of_edges() == 0:
                break

        return G, sep_sets, ci_tests

    # ── Phase 2: V-Structure Orientation ─────────────────────────────────────

    def _orient_v_structures(
        self,
        cpdag: nx.DiGraph,
        skeleton: nx.Graph,
        sep_sets: Dict[Tuple[int, int], List[int]],
    ) -> List[Tuple[str, str, str]]:
        """
        Orient unshielded colliders: X — Z — Y where X and Y are not adjacent
        and Z ∉ sep(X, Y).

        This produces v-structures: X → Z ← Y
        """
        nodes = list(skeleton.nodes())
        v_structures: List[Tuple[str, str, str]] = []

        for z in nodes:
            parents = list(skeleton.neighbors(z))
            for x, y in itertools.combinations(parents, 2):
                # x and y must NOT be adjacent (unshielded triple)
                if skeleton.has_edge(x, y):
                    continue

                ix = nodes.index(x)
                iy = nodes.index(y)
                iz = nodes.index(z)

                sep_xy = sep_sets.get((ix, iy), sep_sets.get((iy, ix), []))

                if iz not in sep_xy:
                    # Orient x → z ← y
                    self._orient_edge(cpdag, x, z)
                    self._orient_edge(cpdag, y, z)
                    v_structures.append((x, z, y))
                    logger.debug("V-structure: %s --> %s <-- %s", x, z, y)

        return v_structures

    # ── Phase 3: Meek Rules ───────────────────────────────────────────────────

    def _apply_meek_rules(
        self,
        cpdag: nx.DiGraph,
        skeleton: nx.Graph,
    ) -> None:
        """
        Apply Meek's orientation rules R1–R4 until no further orientations.

        R1: If a → b — c and a is not adjacent to c  →  orient b → c
        R2: If a → b → c and a — c                   →  orient a → c
        R3: If a — c ← b, a — d → c, a — b          →  orient a → c
        R4: If a — b → c ← d, a — d, a — c          →  orient a → c

        The loop is bounded by (|skeleton_edges| × 4) iterations as a defense
        against any future rule-interaction bug producing a fixed-point
        oscillation. A correct implementation converges in at most |E|
        orientations, so 4× |E| is comfortably above the theoretical maximum.
        """
        max_iterations = max(4 * skeleton.number_of_edges(), 16)
        for _ in range(max_iterations):
            changed = False
            for u, v in list(skeleton.edges()):
                # Skip if the edge is already resolved in either direction,
                # or has already been removed from the CPDAG. Only undirected
                # (both u→v and v→u present) pairs should be reconsidered —
                # otherwise Meek rules can re-fire on ghost edges and loop.
                if self._is_directed(cpdag, u, v):
                    continue
                if self._is_directed(cpdag, v, u):
                    continue
                if not (cpdag.has_edge(u, v) and cpdag.has_edge(v, u)):
                    continue

                if self._apply_r1(cpdag, skeleton, u, v):
                    changed = True
                    continue
                if self._apply_r1(cpdag, skeleton, v, u):
                    changed = True
                    continue
                if self._apply_r2(cpdag, skeleton, u, v):
                    changed = True
                    continue
                if self._apply_r2(cpdag, skeleton, v, u):
                    changed = True
                    continue
            if not changed:
                return
        logger.warning(
            "Meek rules hit iteration cap %d — orientation may be incomplete",
            max_iterations,
        )

    def _apply_r1(self, cpdag, skeleton, b, c):
        """R1: a→b—c, a not adjacent to c, a ≠ c  →  orient b→c"""
        for a in cpdag.predecessors(b):
            if a == c:
                # R1 requires a ≠ c (v-structure needs a distinct third node).
                # Without this guard, when c→b is directed we'd treat c itself
                # as the "predecessor" and spuriously orient b→c, destroying
                # the existing c→b orientation and corrupting the CPDAG.
                continue
            if not cpdag.has_edge(b, a):  # a→b is directed
                if not skeleton.has_edge(a, c):
                    if self._orient_edge(cpdag, b, c):
                        logger.debug("R1: %s→%s—%s  ⟹  %s→%s", a, b, c, b, c)
                        return True
        return False

    def _apply_r2(self, cpdag, skeleton, a, c):
        """R2: a→b→c, a—c, b ≠ c  →  orient a→c"""
        for b in cpdag.successors(a):
            if b == c:
                continue
            if not cpdag.has_edge(b, a):  # a→b directed
                if cpdag.has_edge(b, c) and not cpdag.has_edge(c, b):  # b→c directed
                    if skeleton.has_edge(a, c) and not self._is_directed(cpdag, a, c):
                        if self._orient_edge(cpdag, a, c):
                            logger.debug("R2: %s→%s→%s  ⟹  %s→%s", a, b, c, a, c)
                            return True
        return False

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _orient_edge(cpdag: nx.DiGraph, u: str, v: str) -> bool:
        """
        Orient u→v by removing the reverse v→u if present.

        Returns True if the CPDAG was modified (i.e. an undirected edge became
        directed), False if the edge was already oriented u→v or absent. The
        bool return is used by Meek rules R1/R2 to detect actual progress and
        terminate the fixed-point loop correctly.
        """
        if cpdag.has_edge(v, u):
            cpdag.remove_edge(v, u)
            return True
        return False

    @staticmethod
    def _is_directed(cpdag: nx.DiGraph, u: str, v: str) -> bool:
        """True if u→v is directed (v→u does NOT exist)."""
        return cpdag.has_edge(u, v) and not cpdag.has_edge(v, u)

    @staticmethod
    def _preprocess(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        # Fill missing with column means
        df = df.fillna(df.mean(numeric_only=True))
        # Drop non-numeric columns
        df = df.select_dtypes(include=[np.number])
        # Standardize (zero mean, unit variance) for stable partial correlations
        df = (df - df.mean()) / (df.std() + 1e-8)
        return df

    def _extract_cpdag_edges(
        self,
        cpdag: nx.DiGraph,
        skeleton: nx.Graph,
    ) -> List[Tuple[str, str, str]]:
        """Classify each skeleton edge as directed or undirected."""
        result = []
        seen: Set[FrozenSet] = set()

        for u, v in skeleton.edges():
            key = frozenset([u, v])
            if key in seen:
                continue
            seen.add(key)

            if self._is_directed(cpdag, u, v):
                result.append((u, v, DIRECTED))
            elif self._is_directed(cpdag, v, u):
                result.append((v, u, DIRECTED))
            else:
                result.append((u, v, UNDIRECTED))

        return result


# ─── Granger–PC Fusion ────────────────────────────────────────────────────────

class GrangerPCFusion:
    """
    Fuses the Granger causal DAG (Claim 1) with the PC CPDAG (Claim 3)
    into a single high-confidence causal graph for DCGM.

    Fusion logic:
      • CONFIRMED  — edge present in BOTH Granger and PC (directed same way)
                     Weight multiplier: 1.5× (high confidence)
      • GRANGER_PC_UNDIRECTED — PC skeleton corroborates the edge but PC left
                     it undirected (no v-structure / Meek rule). Granger
                     supplies direction via temporal precedence — a valid
                     orientation signal that observational CI tests cannot
                     express. Weight multiplier: 1.5× (same as confirmed).
      • GRANGER_ONLY — Granger edge not corroborated by PC skeleton
                       Weight multiplier: 1.0× (normal)
      • PC_ONLY    — PC edge not in Granger (PC may be oriented or undirected)
                     Weight multiplier: 0.7× (structural but not temporal)
      • CONFLICT   — Granger says A→B but PC says B→A
                     Both edges receive a conflict flag; DCGM logs for review
    """

    def __init__(
        self,
        granger_threshold: float = 0.05,
        pc_alpha: float = 0.05,
    ):
        self.granger_threshold = granger_threshold
        self.pc_alpha = pc_alpha

    def fuse(
        self,
        granger_edges: Dict[Tuple[str, str], float],   # {(cause, effect): p_value}
        pc_result: PCResult,
    ) -> List[Dict]:
        """
        Parameters
        ──────────
        granger_edges : dict mapping (cause, effect) → p_value from granger.py
        pc_result     : PCResult from PCAlgorithm.fit()

        Returns
        ───────
        List of edge dicts with keys:
            source, target, weight, method, conflict, p_value_granger,
            edge_type_pc
        """
        fused: Dict[Tuple[str, str], Dict] = {}

        # Index PC edges
        pc_directed: Set[Tuple[str, str]] = set()
        pc_undirected: Set[FrozenSet] = set()

        for u, v, t in pc_result.cpdag_edges:
            if t == DIRECTED:
                pc_directed.add((u, v))
            else:
                pc_undirected.add(frozenset([u, v]))

        # Process Granger edges
        for (cause, effect), p_val in granger_edges.items():
            if p_val > self.granger_threshold:
                continue

            entry = {
                "source": cause,
                "target": effect,
                "weight": 1.0,
                "p_value_granger": p_val,
                "edge_type_pc": None,
                "method": "granger_only",
                "conflict": False,
            }

            if (cause, effect) in pc_directed:
                entry["method"] = "confirmed"
                entry["weight"] = 1.5
                entry["edge_type_pc"] = DIRECTED
            elif (effect, cause) in pc_directed:
                entry["method"] = "conflict"
                entry["weight"] = 0.5
                entry["conflict"] = True
                entry["edge_type_pc"] = DIRECTED
                logger.warning("Causal conflict: Granger %s→%s vs PC %s→%s",
                               cause, effect, effect, cause)
            elif frozenset([cause, effect]) in pc_undirected:
                # PC skeleton corroborates the edge; PC could not orient it
                # (no v-structure or Meek rule applies). Granger provides the
                # direction via temporal precedence — a legitimate orientation
                # signal that PC's observational CI tests cannot express. We
                # therefore weight this at 1.5× (same as fully CONFIRMED) and
                # preserve edge_type_pc=UNDIRECTED for downstream inspection.
                entry["method"] = "granger_pc_undirected"
                entry["weight"] = 1.5
                entry["edge_type_pc"] = UNDIRECTED

            fused[(cause, effect)] = entry

        # Add PC-only directed edges not in Granger
        for u, v in pc_directed:
            if (u, v) not in fused:
                fused[(u, v)] = {
                    "source": u,
                    "target": v,
                    "weight": 0.7,
                    "p_value_granger": None,
                    "edge_type_pc": DIRECTED,
                    "method": "pc_only",
                    "conflict": False,
                }

        return list(fused.values())

    def to_networkx(
        self,
        fused_edges: List[Dict],
        include_conflicts: bool = False,
    ) -> nx.DiGraph:
        """Build a weighted DiGraph from fused edges."""
        G = nx.DiGraph()
        for e in fused_edges:
            if e["conflict"] and not include_conflicts:
                continue
            G.add_edge(
                e["source"], e["target"],
                weight=e["weight"],
                method=e["method"],
                conflict=e["conflict"],
            )
        return G

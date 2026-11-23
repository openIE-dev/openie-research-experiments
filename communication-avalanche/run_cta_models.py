#!/usr/bin/env python3
"""
Pre-Registered Biological, Stigmergic, and Cultural Ratchet Suite (CA-M1 .. CA-M5)
Study #21: The Communication Tool Avalanche (slug: communication-avalanche)
Fixed seed: 20261123 | board_metered: false (deterministic computational models [M])
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

FIXED_SEED = 20261123


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ============================================================================
# CA-M1: Bacterial Cooperative Quorum Switch vs. Constitutive Expression
# ============================================================================
def run_ca_m1(prereg: dict, rng: np.random.Generator) -> dict:
    cfg = prereg["models"]["CA-M1"]
    g_total = cfg["genome_genes_total"]          # 5000
    g_quorum = cfg["quorum_regulated_genes"]     # 600
    g_house = g_total - g_quorum                 # 4400

    # Housekeeping = 1.0 ATP-equiv/gene; secreted public-good exoproducts = 3.0 ATP-equiv/gene;
    # autoinducer synthase basal signaling cost = 12.0 ATP-equiv (0.67% of max regulon load).
    e_house = float(g_house) * 1.0               # 4400.0
    e_regulon_max = float(g_quorum) * 3.0        # 1800.0
    e_autoinducer = 12.0
    e_constitutive_total = e_house + e_regulon_max

    densities = cfg["density_ratio_grid"]
    diff_losses = cfg["diffusivity_loss_rates"]
    hill_ns = cfg["hill_exponents"]

    sweep_rows = []
    for d_loss in diff_losses:
        for rho in densities:
            # Steady-state normalized autoinducer concentration A/K = rho / (0.5 + d_loss)
            a_over_k = rho / (0.5 + d_loss)
            row = {
                "diffusivity_loss": d_loss,
                "density_ratio": rho,
                "autoinducer_over_K": round(a_over_k, 5),
                "constitutive_cell_atp": e_constitutive_total,
                "constitutive_regulon_atp": e_regulon_max,
                "hill": {},
            }
            for n_h in hill_ns:
                act = (a_over_k ** n_h) / (1.0 + (a_over_k ** n_h))
                e_reg = e_autoinducer + act * e_regulon_max
                e_cell = e_house + e_reg
                reg_saving = 1.0 - (e_reg / e_regulon_max)
                cell_saving = 1.0 - (e_cell / e_constitutive_total)
                row["hill"][f"n{n_h}"] = {
                    "activation": round(act, 6),
                    "regulon_atp": round(e_reg, 3),
                    "cell_atp": round(e_cell, 3),
                    "regulon_saving_frac": round(reg_saving, 6),
                    "whole_cell_saving_frac": round(cell_saving, 6),
                }
            sweep_rows.append(row)

    # Sub-threshold stochastic autoinducer noise vulnerability at mean A/K = 0.25
    trials = cfg["monte_carlo_trials"]
    sigma = cfg["noise_sigma_over_K"]
    noisy_a = np.clip(rng.normal(loc=0.25, scale=sigma, size=trials), 0.0, None)
    noise_audit = {}
    for n_h in hill_ns:
        acts = (noisy_a ** n_h) / (1.0 + (noisy_a ** n_h))
        false_fire_rate = float(np.mean(acts > 0.20))
        mean_leak = float(np.mean(acts))
        noise_audit[f"n{n_h}"] = {
            "mean_subthreshold_activation": round(mean_leak, 6),
            "premature_firing_prob_gt_0p20": round(false_fire_rate, 6),
        }

    # Reference summary at rho = 0.20, d_loss = 0.5 (A/K = 0.20)
    ref_row = next(r for r in sweep_rows if r["diffusivity_loss"] == 0.5 and r["density_ratio"] == 0.2)
    reg_save_n2 = ref_row["hill"]["n2"]["regulon_saving_frac"]
    reg_save_n4 = ref_row["hill"]["n4"]["regulon_saving_frac"]
    ff_ratio_n2 = noise_audit["n1"]["premature_firing_prob_gt_0p20"] / max(
        1e-9, noise_audit["n2"]["premature_firing_prob_gt_0p20"]
    )
    ff_ratio_n4 = noise_audit["n1"]["premature_firing_prob_gt_0p20"] / max(
        1e-9, noise_audit["n4"]["premature_firing_prob_gt_0p20"]
    )

    passed = (
        reg_save_n2 >= cfg["pass_criteria"]["low_density_quorum_regulon_energy_saving_min_frac"]
        and ff_ratio_n2 >= cfg["pass_criteria"]["cooperative_n2_vs_n1_false_fire_reduction_min_ratio"]
    )
    return {
        "passed": passed,
        "reference_low_density_rho_0p20": ref_row,
        "subthreshold_noise_audit": noise_audit,
        "false_fire_reduction_n2_vs_n1": round(ff_ratio_n2, 4),
        "false_fire_reduction_n4_vs_n1": round(ff_ratio_n4, 4),
        "sweep_count": len(sweep_rows),
        "density_curve_dloss_0p5": [r for r in sweep_rows if r["diffusivity_loss"] == 0.5],
    }


# ============================================================================
# CA-M2: Cyanobacterial 20-Cell Filament with Ca2+-Gated SepJ Nanopores
# ============================================================================
def simulate_filament(n_cells: int, dt: float, horizon: float, k_pore: float, tau_close: float | None, thresh: float) -> dict:
    steps = int(round(horizon / dt))
    # State vectors: metabolite M[0..19], Ca2+ injury signal C[0..19], septal conductance G[0..18]
    m = np.ones(n_cells, dtype=np.float64)
    c = np.zeros(n_cells, dtype=np.float64)
    g = np.ones(n_cells - 1, dtype=np.float64)

    # Cell 0 suffers acute membrane lysis at t = 0
    m[0] = 0.0
    c[0] = 1.0

    r_prod = 0.03       # slow basal photosynthetic replenishment (s^-1)
    k_tox = 0.90        # Ca2+-overload catabolic loss (s^-1)
    ca_trig = 0.15      # Ca2+ threshold triggering conformational SepJ plug closure

    def rhs(m_vec: np.ndarray, c_vec: np.ndarray, g_vec: np.ndarray):
        dm = np.zeros_like(m_vec)
        dc = np.zeros_like(c_vec)
        dg = np.zeros_like(g_vec)

        # Flux across junctions j between cell j and j+1
        flux_m = k_pore * g_vec * (m_vec[:-1] - m_vec[1:])
        flux_c = k_pore * g_vec * (c_vec[:-1] - c_vec[1:])

        dm[:-1] -= flux_m
        dm[1:] += flux_m
        dc[:-1] -= flux_c
        dc[1:] += flux_c

        # Intracellular dynamics for non-lysed cells 1..n-1
        dm[1:] += r_prod * (1.0 - m_vec[1:]) - k_tox * c_vec[1:] * m_vec[1:]
        dc[1:] -= 0.05 * c_vec[1:]  # slow intracellular Ca2+ buffering

        # Clamp lysed boundary cell 0
        dm[0] = 0.0
        dc[0] = 0.0

        if tau_close is not None:
            local_ca = np.maximum(c_vec[:-1], c_vec[1:])
            active_close = (local_ca >= ca_trig).astype(np.float64)
            dg = -active_close * (g_vec / tau_close)
        return dm, dc, dg

    for _ in range(steps):
        dm1, dc1, dg1 = rhs(m, c, g)
        dm2, dc2, dg2 = rhs(
            np.clip(m + 0.5 * dt * dm1, 0.0, 1.0),
            np.clip(c + 0.5 * dt * dc1, 0.0, 1.0),
            np.clip(g + 0.5 * dt * dg1, 0.0, 1.0),
        )
        dm3, dc3, dg3 = rhs(
            np.clip(m + 0.5 * dt * dm2, 0.0, 1.0),
            np.clip(c + 0.5 * dt * dc2, 0.0, 1.0),
            np.clip(g + 0.5 * dt * dg2, 0.0, 1.0),
        )
        dm4, dc4, dg4 = rhs(
            np.clip(m + dt * dm3, 0.0, 1.0),
            np.clip(c + dt * dc3, 0.0, 1.0),
            np.clip(g + dt * dg3, 0.0, 1.0),
        )
        m = np.clip(m + (dt / 6.0) * (dm1 + 2 * dm2 + 2 * dm3 + dm4), 0.0, 1.0)
        c = np.clip(c + (dt / 6.0) * (dc1 + 2 * dc2 + 2 * dc3 + dc4), 0.0, 1.0)
        g = np.clip(g + (dt / 6.0) * (dg1 + 2 * dg2 + 2 * dg3 + dg4), 0.0, 1.0)
        m[0] = 0.0
        c[0] = 1.0

    surviving = int(np.sum(m >= thresh))
    return {
        "tau_close_sec": "ungated" if tau_close is None else tau_close,
        "surviving_cells": surviving,
        "surviving_fraction": round(surviving / float(n_cells), 4),
        "retained_metabolic_capacity_frac": round(float(np.sum(m)) / float(n_cells), 5),
        "junction_0_1_final_open_frac": round(float(g[0]), 6),
        "cell_1_final_metabolite": round(float(m[1]), 5),
        "cell_19_final_metabolite": round(float(m[-1]), 5),
    }


def run_ca_m2(prereg: dict) -> dict:
    cfg = prereg["models"]["CA-M2"]
    results = []
    for tau in cfg["closure_latencies_sec"]:
        results.append(
            simulate_filament(
                cfg["filament_cells"],
                cfg["dt_sec"],
                cfg["horizon_sec"],
                cfg["pore_exchange_rate_per_sec"],
                tau,
                cfg["viability_metabolite_threshold"],
            )
        )
    ungated = simulate_filament(
        cfg["filament_cells"],
        cfg["dt_sec"],
        cfg["horizon_sec"],
        cfg["pore_exchange_rate_per_sec"],
        None,
        cfg["viability_metabolite_threshold"],
    )
    results.append(ungated)

    fast = results[0]  # tau_close = 0.05 s
    passed = (
        fast["surviving_fraction"] >= cfg["pass_criteria"]["fast_sepj_surviving_fraction_min"]
        and ungated["surviving_fraction"] <= cfg["pass_criteria"]["ungated_surviving_fraction_max"]
    )
    return {
        "passed": passed,
        "fast_sepj_tau_0p05s": fast,
        "ungated_control": ungated,
        "latency_sweep": results,
    }


# ============================================================================
# CA-M3: 3D Topological k-Neighbor vs. Metric-Radius Flock Under 4x Expansion
# ============================================================================
def largest_component_fraction(adj: np.ndarray) -> Tuple[float, int]:
    n = adj.shape[0]
    visited = np.zeros(n, dtype=bool)
    best = 0
    comp_count = 0
    for start in range(n):
        if visited[start]:
            continue
        comp_count += 1
        stack = [start]
        visited[start] = True
        sz = 0
        while stack:
            u = stack.pop()
            sz += 1
            nbrs = np.flatnonzero(adj[u] & ~visited)
            if nbrs.size:
                visited[nbrs] = True
                stack.extend(nbrs.tolist())
        if sz > best:
            best = sz
    return best / float(n), comp_count


def velocity_correlation_ratio_xi_over_l(pos: np.ndarray, vel: np.ndarray) -> float:
    # Fluctuating velocities delta_v_i = v_i - mean(v) (Cavagna et al. 2010 PNAS)
    dv = vel - np.mean(vel, axis=0, keepdims=True)
    norms = np.linalg.norm(dv, axis=1)
    denom = float(np.mean(norms ** 2))
    if denom < 1e-12:
        return 0.0

    diff = pos[:, None, :] - pos[None, :, :]
    dists = np.linalg.norm(diff, axis=-1)
    flock_l = float(np.max(dists))
    if flock_l < 1e-9:
        return 0.0

    dots = dv @ dv.T
    n_bins = 24
    r_max = flock_l
    edges = np.linspace(0.0, r_max, n_bins + 1)
    triu = np.triu_indices(pos.shape[0], k=1)
    pair_d = dists[triu]
    pair_c = dots[triu] / denom

    centers = 0.5 * (edges[:-1] + edges[1:])
    c_prof = np.zeros(n_bins)
    valid = np.zeros(n_bins, dtype=bool)
    for b in range(n_bins):
        mask = (pair_d >= edges[b]) & (pair_d < edges[b + 1])
        if np.any(mask):
            c_prof[b] = float(np.mean(pair_c[mask]))
            valid[b] = True

    # Find first zero-crossing of C(r)
    prev_r, prev_c = 0.0, 1.0
    for b in range(n_bins):
        if not valid[b]:
            continue
        cur_r, cur_c = float(centers[b]), float(c_prof[b])
        if cur_c <= 0.0:
            frac = prev_c / max(1e-12, prev_c - cur_c)
            xi = prev_r + frac * (cur_r - prev_r)
            return xi / flock_l
        prev_r, prev_c = cur_r, cur_c
    return 0.5


def simulate_flock_trial(n: int, k_topo: int, expansion: float, mode: str, rng: np.random.Generator) -> dict:
    # Initialize in 3D sphere of radius R_init = 0.5 * N^(1/3) (constant initial density)
    r_init = 0.5 * (n ** (1.0 / 3.0))
    u = rng.normal(size=(n, 3))
    u /= np.linalg.norm(u, axis=1, keepdims=True)
    rad = r_init * (rng.random(n) ** (1.0 / 3.0))
    pos = u * rad[:, None]

    # Calibrate metric R0 so average initial degree equals k_topo (~7 neighbors)
    d0 = np.linalg.norm(pos[:, None, :] - pos[None, :, :], axis=-1)
    np.fill_diagonal(d0, np.inf)
    kth_dists = np.partition(d0, k_topo - 1, axis=1)[:, k_topo - 1]
    r_metric = float(np.median(kth_dists))

    # Common flock heading + smooth spatial swirl perturbation (predator-turn wave)
    base_dir = np.array([1.0, 0.0, 0.0])
    vel = np.tile(base_dir, (n, 1)) + 0.18 * rng.normal(size=(n, 3))
    vel /= np.linalg.norm(vel, axis=1, keepdims=True)

    # Predator strike induces 4x radial density expansion + localized boundary turn wave
    pos_exp = pos * expansion
    strike_focus = np.array([r_init * expansion * 0.92, 0.0, 0.0])
    rel_strike = pos_exp - strike_focus[None, :]
    strike_dist = np.linalg.norm(rel_strike, axis=1, keepdims=True) + 1e-6
    # Localized boundary evasion impulse (lateral turn + multi-mode rotational shear, Cavagna et al. 2010)
    lateral_turn = np.stack([-pos_exp[:, 1], pos_exp[:, 0], 0.6 * pos_exp[:, 2] * np.sin(pos_exp[:, 0])], axis=1)
    lateral_turn /= (np.linalg.norm(lateral_turn, axis=1, keepdims=True) + 1e-6)
    strike_env = np.exp(-((strike_dist / (0.38 * r_init * expansion)) ** 2))
    vel = vel + 0.65 * strike_env * lateral_turn + 0.22 * lateral_turn
    vel /= np.linalg.norm(vel, axis=1, keepdims=True)

    # 28 collective alignment steps post-strike
    dt = 0.08
    for _ in range(28):
        dmat = np.linalg.norm(pos_exp[:, None, :] - pos_exp[None, :, :], axis=-1)
        np.fill_diagonal(dmat, np.inf)
        if mode == "topological":
            nbr_idx = np.argpartition(dmat, k_topo, axis=1)[:, :k_topo]
            adj = np.zeros((n, n), dtype=bool)
            rows = np.arange(n)[:, None]
            adj[rows, nbr_idx] = True
        else:
            adj = dmat <= r_metric

        deg = np.sum(adj, axis=1, keepdims=True)
        mean_nbr_vel = np.where(deg > 0, (adj @ vel) / np.maximum(deg, 1), vel)
        noise = 0.085 * rng.normal(size=(n, 3))
        vel_new = 0.45 * vel + 0.55 * mean_nbr_vel + noise
        vel = vel_new / np.linalg.norm(vel_new, axis=1, keepdims=True)
        pos_exp = pos_exp + dt * vel

    # Final interaction graph (symmetrized undirected connectivity for flock cohesion)
    d_final = np.linalg.norm(pos_exp[:, None, :] - pos_exp[None, :, :], axis=-1)
    np.fill_diagonal(d_final, np.inf)
    if mode == "topological":
        nbr_idx = np.argpartition(d_final, k_topo, axis=1)[:, :k_topo]
        adj_dir = np.zeros((n, n), dtype=bool)
        adj_dir[np.arange(n)[:, None], nbr_idx] = True
    else:
        adj_dir = d_final <= r_metric

    adj_sym = adj_dir | adj_dir.T
    lcc_frac, n_comp = largest_component_fraction(adj_sym)
    polarization = float(np.linalg.norm(np.mean(vel, axis=0)))
    xi_over_l = velocity_correlation_ratio_xi_over_l(pos_exp, vel)
    return {
        "lcc_frac": lcc_frac,
        "components": n_comp,
        "polarization": polarization,
        "xi_over_L": xi_over_l,
        "mean_out_degree": float(np.mean(np.sum(adj_dir, axis=1))),
    }


def run_ca_m3(prereg: dict, rng: np.random.Generator) -> dict:
    cfg = prereg["models"]["CA-M3"]
    k_topo = cfg["topological_k"]
    exp_factor = cfg["expansion_factor_linear"]
    trials = cfg["trials_per_size"]

    by_size = []
    for n in cfg["flock_sizes"]:
        topo_runs = [simulate_flock_trial(n, k_topo, exp_factor, "topological", rng) for _ in range(trials)]
        met_runs = [simulate_flock_trial(n, k_topo, exp_factor, "metric", rng) for _ in range(trials)]
        by_size.append(
            {
                "N": n,
                "topological_k7": {
                    "connected_cohesion_frac": round(float(np.mean([r["lcc_frac"] for r in topo_runs])), 5),
                    "mean_components": round(float(np.mean([r["components"] for r in topo_runs])), 3),
                    "polarization": round(float(np.mean([r["polarization"] for r in topo_runs])), 5),
                    "xi_over_L": round(float(np.mean([r["xi_over_L"] for r in topo_runs])), 5),
                    "mean_degree": round(float(np.mean([r["mean_out_degree"] for r in topo_runs])), 3),
                },
                "metric_R0": {
                    "connected_cohesion_frac": round(float(np.mean([r["lcc_frac"] for r in met_runs])), 5),
                    "mean_components": round(float(np.mean([r["components"] for r in met_runs])), 3),
                    "polarization": round(float(np.mean([r["polarization"] for r in met_runs])), 5),
                    "xi_over_L": round(float(np.mean([r["xi_over_L"] for r in met_runs])), 5),
                    "mean_degree": round(float(np.mean([r["mean_out_degree"] for r in met_runs])), 3),
                },
            }
        )

    min_topo_coh = min(row["topological_k7"]["connected_cohesion_frac"] for row in by_size)
    mean_xi = float(np.mean([row["topological_k7"]["xi_over_L"] for row in by_size]))
    max_met_coh = max(row["metric_R0"]["connected_cohesion_frac"] for row in by_size)
    band = cfg["pass_criteria"]["topological_xi_over_L_band"]

    passed = (
        min_topo_coh >= cfg["pass_criteria"]["topological_connected_cohesion_min_frac"]
        and band[0] <= mean_xi <= band[1]
        and max_met_coh <= cfg["pass_criteria"]["metric_post_expansion_largest_component_max_frac"]
    )
    return {
        "passed": passed,
        "min_topological_cohesion_frac": round(min_topo_coh, 5),
        "mean_topological_xi_over_L": round(mean_xi, 5),
        "max_metric_cohesion_frac": round(max_met_coh, 5),
        "size_scaling": by_size,
    }


# ============================================================================
# CA-M4: Physarum Adaptive Poiseuille Tube Network
# ============================================================================
def solve_kirchhoff_flux(n_nodes: int, edges: List[Tuple[int, int, float]], d_vec: np.ndarray, src: int, sink: int, i0: float) -> np.ndarray:
    g_mat = np.zeros((n_nodes, n_nodes), dtype=np.float64)
    for idx, (u, v, length) in enumerate(edges):
        cond = max(1e-12, d_vec[idx]) / length
        g_mat[u, u] += cond
        g_mat[v, v] += cond
        g_mat[u, v] -= cond
        g_mat[v, u] -= cond

    rhs = np.zeros(n_nodes, dtype=np.float64)
    rhs[src] = i0
    rhs[sink] = -i0

    # Ground sink pressure p[sink] = 0
    keep = [i for i in range(n_nodes) if i != sink]
    p = np.zeros(n_nodes, dtype=np.float64)
    p[keep] = np.linalg.solve(g_mat[np.ix_(keep, keep)], rhs[keep])

    q = np.zeros(len(edges), dtype=np.float64)
    for idx, (u, v, length) in enumerate(edges):
        q[idx] = (d_vec[idx] / length) * (p[u] - p[v])
    return q


def mst_length_and_apsp(n_nodes: int, edges: List[Tuple[int, int, float]], active_mask: np.ndarray | None = None) -> Tuple[float, float, bool]:
    INF = 1e12
    dist = np.full((n_nodes, n_nodes), INF, dtype=np.float64)
    np.fill_diagonal(dist, 0.0)
    tot_len = 0.0
    for idx, (u, v, length) in enumerate(edges):
        if active_mask is not None and not active_mask[idx]:
            continue
        tot_len += length
        if length < dist[u, v]:
            dist[u, v] = length
            dist[v, u] = length

    # Floyd-Warshall
    for k in range(n_nodes):
        dist = np.minimum(dist, dist[:, [k]] + dist[[k], :])

    connected = bool(np.all(dist < INF * 0.5))
    triu = np.triu_indices(n_nodes, k=1)
    md = float(np.mean(dist[triu])) if connected else INF
    return tot_len, md, connected


def kruskal_mst(n_nodes: int, edges: List[Tuple[int, int, float]]) -> np.ndarray:
    parent = list(range(n_nodes))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    order = sorted(range(len(edges)), key=lambda idx: edges[idx][2])
    mask = np.zeros(len(edges), dtype=bool)
    for idx in order:
        u, v, _ = edges[idx]
        ru, rv = find(u), find(v)
        if ru != rv:
            parent[ru] = rv
            mask[idx] = True
    return mask


def run_ca_m4(prereg: dict, rng: np.random.Generator) -> dict:
    cfg = prereg["models"]["CA-M4"]

    # Part A: 8-node maze/bridge graph between source 0 and sink 7
    # Unique shortest path: 0 -> 1 -> 4 -> 7 (length = 1.0 + 1.1 + 1.0 = 3.1)
    # Alternative paths have lengths 3.6, 4.1, 4.7
    edges_8 = [
        (0, 1, 1.0), (1, 4, 1.1), (4, 7, 1.0),  # shortest path (indices 0, 1, 2; L = 3.1)
        (0, 2, 1.3), (2, 5, 1.2), (5, 7, 1.1),  # second path (L = 3.6)
        (0, 3, 1.5), (3, 6, 1.4), (6, 7, 1.2),  # third path (L = 4.1)
        (1, 2, 0.9), (4, 5, 0.8), (2, 3, 1.0), (5, 6, 1.0),
    ]
    maze_8_results = []
    for mu in cfg["mu_exponents_8node"]:
        d = np.ones(len(edges_8), dtype=np.float64) * 0.25
        dt = 0.25
        # Operate in unsaturated biological flux regime I0 = 0.32 (< inflection point of |Q|^mu/(1+|Q|^mu))
        # using exact Physarum ODE dD/dt = |Q|^mu / (1 + |Q|^mu) - D (Tero et al. 2007, 2010)
        i0 = 0.32
        for _ in range(2800):
            q = solve_kirchhoff_flux(8, edges_8, d, 0, 7, i0)
            aq = np.abs(q)
            f_q = (aq ** mu) / (1.0 + (aq ** mu))
            d = np.clip(d + dt * (f_q - d), 1e-12, None)
        q_final = np.abs(solve_kirchhoff_flux(8, edges_8, d, 0, 7, i0))
        shortest_share = float(np.mean(q_final[:3]) / i0)
        alt_max_d = float(np.max(d[3:]))
        maze_8_results.append(
            {
                "mu": mu,
                "shortest_path_flux_share": round(shortest_share, 6),
                "shortest_path_mean_D": round(float(np.mean(d[:3])), 5),
                "max_non_shortest_D": round(alt_max_d, 6),
            }
        )

    # Part B: 16-node multi-source regional transport graph (central hub 0 + two concentric rings)
    coords = [(0.0, 0.0)]
    for k in range(5):
        ang = 2.0 * math.pi * k / 5.0
        coords.append((1.0 * math.cos(ang), 1.0 * math.sin(ang)))
    for k in range(10):
        ang = 2.0 * math.pi * k / 10.0 + 0.15
        r = 2.05 + 0.12 * math.sin(3 * k)
        coords.append((r * math.cos(ang), r * math.sin(ang)))
    coords_arr = np.array(coords)

    # Proximity candidate mesh (connect pairs within Euclidean distance <= 1.42)
    edges_16: List[Tuple[int, int, float]] = []
    for u in range(16):
        for v in range(u + 1, 16):
            dist_uv = float(np.linalg.norm(coords_arr[u] - coords_arr[v]))
            if dist_uv <= 1.42:
                edges_16.append((u, v, dist_uv))

    mst_mask = kruskal_mst(16, edges_16)
    l_mst, md_mst, _ = mst_length_and_apsp(16, edges_16, mst_mask)

    regional_16_results = []
    for mu in cfg["mu_exponents_16node"]:
        d = np.ones(len(edges_16), dtype=np.float64) * 0.25
        dt = 0.12
        # Multi-source plasmodium: random hub-to-periphery & peripheral-pair nutrient pulses (Tero et al. 2010)
        for _ in range(420):
            f_acc = np.zeros(len(edges_16), dtype=np.float64)
            n_od = 12
            for _ in range(n_od):
                if rng.random() < 0.55:
                    src = 0
                    sink = int(rng.integers(1, 16))
                else:
                    u_p, v_p = rng.choice(16, size=2, replace=False)
                    src, sink = int(u_p), int(v_p)
                q = np.abs(solve_kirchhoff_flux(16, edges_16, d, src, sink, 0.95))
                f_acc += (q ** mu) / (1.0 + (q ** mu))
            d = np.clip(d + dt * ((f_acc / n_od) - d), 1e-10, None)

        # Core structural tubes retain >= 15% of peak network conductivity
        d_thresh = 0.15 * float(np.max(d))
        active = d >= d_thresh
        # Ensure connected evaluation; if overly pruned at very high mu, check connectivity honestly
        l_net, md_net, is_conn = mst_length_and_apsp(16, edges_16, active)
        active_indices = np.flatnonzero(active).tolist()
        if is_conn and len(active_indices) > 0:
            survive_cuts = 0
            for cut_idx in active_indices:
                pert = active.copy()
                pert[cut_idx] = False
                _, _, ok = mst_length_and_apsp(16, edges_16, pert)
                if ok:
                    survive_cuts += 1
            ft = survive_cuts / float(len(active_indices))
            tl_norm = l_net / l_mst
            md_norm = md_net / md_mst
            bc_ratio = ft / tl_norm
        else:
            ft = 0.0
            tl_norm = l_net / l_mst
            md_norm = None
            bc_ratio = 0.0

        regional_16_results.append(
            {
                "mu": mu,
                "active_tubes": int(np.sum(active)),
                "total_candidate_tubes": len(edges_16),
                "connected": is_conn,
                "TL_norm_vs_MST": round(tl_norm, 4),
                "MD_norm_vs_MST": None if md_norm is None else round(md_norm, 4),
                "fault_tolerance_FT": round(ft, 4),
                "FT_over_TL_norm": round(bc_ratio, 4),
            }
        )

    super_share = min(r["shortest_path_flux_share"] for r in maze_8_results if r["mu"] > 1.0)
    bio_row = next(r for r in regional_16_results if r["mu"] == 1.4)
    passed = (
        super_share >= cfg["pass_criteria"]["superlinear_shortest_path_flux_min"]
        if "superlinear_shortest_path_flux_min" in cfg["pass_criteria"]
        else super_share >= cfg["pass_criteria"]["superlinear_shortest_path_flux_share_min"]
    ) and (bio_row["connected"] and bio_row["TL_norm_vs_MST"] < 2.5 and bio_row["fault_tolerance_FT"] > 0.60)

    return {
        "passed": passed,
        "maze_8node": maze_8_results,
        "mst_16node_reference": {
            "candidate_edges": len(edges_16),
            "mst_length": round(l_mst, 4),
            "mst_mean_distance": round(md_mst, 4),
        },
        "regional_16node_pareto": regional_16_results,
    }


# ============================================================================
# CA-M5: 20-Generation Cultural/Machine Ratchet After Demonstrator Removal
# ============================================================================
def evaluate_sequence_policy(seq: np.ndarray) -> Tuple[float, bool]:
    """
    6-step non-myopic task on alphabet {0, 1, 2}^6:
      - Optimal counterintuitive sequence (2, 0, 2, 2, 0, 2) yields exact reward 1.00 (valid contract).
      - Greedy myopic trap (1, 1, 1, 1, 1, 1) yields 0.40 (each '1' gives +0.40/6 immediately,
        whereas '2' or '0' in isolation gives only 0.05 unless the full 6-step parity/valley constraint holds).
    """
    opt = np.array([2, 0, 2, 2, 0, 2], dtype=np.int64)
    matches_opt = int(np.sum(seq == opt))
    if matches_opt == 6:
        return 1.00, True
    if matches_opt == 5:
        return 0.72, False
    # Myopic partial payoff for '1' choices + small exploratory noise floor
    ones = int(np.sum(seq == 1))
    score = 0.0666667 * ones + 0.015 * matches_opt
    return min(0.45, score), False


def run_ca_m5(prereg: dict, rng: np.random.Generator) -> dict:
    cfg = prereg["models"]["CA-M5"]
    n_agents = cfg["agents_per_generation"]       # 32
    n_gens = cfg["generations"]                   # 20 (Gen 0 .. Gen 20 inclusive -> 21 snapshots)
    n_mach = cfg["machine_demonstrator_count"]    # 4
    rem_gen = cfg["machine_removal_generation"]   # 5
    n_lin = cfg["independent_lineages"]           # 30

    opt_seq = np.array([2, 0, 2, 2, 0, 2], dtype=np.int64)
    myopic_seq = np.array([1, 1, 1, 1, 1, 1], dtype=np.int64)

    regimes = {}
    for regime in cfg["regimes"]:
        gen_mean_scores = np.zeros((n_lin, n_gens + 1), dtype=np.float64)
        gen_opt_fracs = np.zeros((n_lin, n_gens + 1), dtype=np.float64)

        for lin in range(n_lin):
            # Initialize Gen 0: naive learners cluster near myopic trap; machine demonstrators find opt_seq
            pop = np.tile(myopic_seq, (n_agents, 1))
            for i in range(n_agents):
                for pos in range(6):
                    if rng.random() < 0.20:
                        pop[i, pos] = int(rng.integers(0, 3))

            if regime != "no_machine_baseline":
                for m_idx in range(n_mach):
                    pop[m_idx] = opt_seq.copy()

            # Content-addressed externalized artifact library (only active in attested_externalized_library)
            library_best_seq = None
            library_best_digest = None
            library_best_score = -1.0

            for g in range(n_gens + 1):
                # Enforce synthetic demonstrator presence in Gen 0..4, complete removal from Gen 5..20
                if regime != "no_machine_baseline" and g < rem_gen:
                    for m_idx in range(n_mach):
                        pop[m_idx] = opt_seq.copy()

                scores = np.zeros(n_agents, dtype=np.float64)
                opt_flags = np.zeros(n_agents, dtype=bool)
                for i in range(n_agents):
                    sc, is_opt = evaluate_sequence_policy(pop[i])
                    scores[i] = sc
                    opt_flags[i] = is_opt

                    if regime == "attested_externalized_library":
                        digest = hashlib.blake2s(pop[i].tobytes()).hexdigest()
                        # Deterministic contract verifier gate: accepts valid/strictly better artifacts
                        if (is_opt or sc > library_best_score) and sc >= library_best_score:
                            if sc > library_best_score:
                                library_best_score = sc
                                library_best_seq = pop[i].copy()
                                library_best_digest = digest

                gen_mean_scores[lin, g] = float(np.mean(scores))
                gen_opt_fracs[lin, g] = float(np.mean(opt_flags))

                if g == n_gens:
                    break

                # Produce Generation g + 1 of 32 learners
                next_pop = np.zeros_like(pop)
                for i in range(n_agents):
                    if regime == "attested_externalized_library" and library_best_seq is not None:
                        # Ingest verified artifact with content-hash check (zero copy corruption)
                        recomputed = hashlib.blake2s(library_best_seq.tobytes()).hexdigest()
                        assert recomputed == library_best_digest
                        cand = library_best_seq.copy()
                        # Local exploration attempted, but agent retains verified artifact unless local trial beats it
                        trial = cand.copy()
                        if rng.random() < 0.15:
                            idx_mut = int(rng.integers(0, 6))
                            trial[idx_mut] = int(rng.integers(0, 3))
                        sc_trial, _ = evaluate_sequence_policy(trial)
                        next_pop[i] = trial if sc_trial >= library_best_score else cand
                    elif regime == "prestige_biased_imitation":
                        # Softmax prestige selection (beta = 11.0) + social copy noise + myopic pull
                        logits = 11.0 * (scores - np.max(scores))
                        probs = np.exp(logits)
                        probs /= np.sum(probs)
                        role_idx = int(rng.choice(n_agents, p=probs))
                        child = pop[role_idx].copy()
                        for pos in range(6):
                            if rng.random() < 0.045:
                                # Myopic bias pulls learners toward locally safe '1'
                                child[pos] = 1 if rng.random() < 0.70 else int(rng.integers(0, 3))
                        next_pop[i] = child
                    else:
                        # Unverified random peer imitation (or no-machine baseline with weak prestige)
                        logits = (3.0 if regime == "no_machine_baseline" else 1.5) * (scores - np.max(scores))
                        probs = np.exp(logits)
                        probs /= np.sum(probs)
                        role_idx = int(rng.choice(n_agents, p=probs))
                        child = pop[role_idx].copy()
                        for pos in range(6):
                            if rng.random() < 0.08:
                                child[pos] = 1 if rng.random() < 0.70 else int(rng.integers(0, 3))
                        next_pop[i] = child

                pop = next_pop

        lineage_survival_g20 = float(np.mean(gen_opt_fracs[:, -1] >= 0.50))
        regimes[regime] = {
            "gen0_mean_score": round(float(np.mean(gen_mean_scores[:, 0])), 5),
            "gen4_last_machine_score": round(float(np.mean(gen_mean_scores[:, rem_gen - 1])), 5),
            "gen5_first_post_removal_score": round(float(np.mean(gen_mean_scores[:, rem_gen])), 5),
            "gen10_mean_score": round(float(np.mean(gen_mean_scores[:, 10])), 5),
            "gen20_mean_score": round(float(np.mean(gen_mean_scores[:, 20])), 5),
            "gen4_optimal_agent_frac": round(float(np.mean(gen_opt_fracs[:, rem_gen - 1])), 5),
            "gen20_optimal_agent_frac": round(float(np.mean(gen_opt_fracs[:, 20])), 5),
            "gen20_majority_optimal_lineages_frac": round(lineage_survival_g20, 5),
            "trajectory_mean_score": [round(float(x), 5) for x in np.mean(gen_mean_scores, axis=0)],
            "trajectory_optimal_frac": [round(float(x), 5) for x in np.mean(gen_opt_fracs, axis=0)],
        }

    att_g20 = regimes["attested_externalized_library"]["gen20_optimal_agent_frac"]
    unv_g20 = regimes["unverified_imitation"]["gen20_optimal_agent_frac"]
    passed = (
        att_g20 >= cfg["pass_criteria"]["attested_gen20_skill_retention_min"]
        and att_g20 > unv_g20
    )
    return {
        "passed": passed,
        "machine_removed_at_generation": rem_gen,
        "regimes": regimes,
    }


def main() -> None:
    here = Path(__file__).resolve().parent
    prereg_path = here / "PREREG_cta_models.json"
    sha_path = here / "PREREG_cta_models.json.sha256"

    prereg_digest = sha256_file(prereg_path)
    expected_line = sha_path.read_text(encoding="utf-8").strip().split()[0]
    if prereg_digest != expected_line:
        raise RuntimeError(f"Pre-registration SHA-256 mismatch: {prereg_digest} != {expected_line}")

    prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
    assert prereg["fixed_seed"] == FIXED_SEED

    rng = np.random.default_rng(FIXED_SEED)
    t0 = time.perf_counter()

    m1 = run_ca_m1(prereg, rng)
    m2 = run_ca_m2(prereg)
    m3 = run_ca_m3(prereg, rng)
    m4 = run_ca_m4(prereg, rng)
    m5 = run_ca_m5(prereg, rng)

    elapsed = time.perf_counter() - t0
    all_passed = all(x["passed"] for x in (m1, m2, m3, m4, m5))

    results = {
        "study_id": prereg["study_id"],
        "fixed_seed": FIXED_SEED,
        "prereg_sha256": prereg_digest,
        "board_metered": False,
        "evidence_class": "M (Deterministic Computational Model)",
        "all_models_passed": all_passed,
        "elapsed_seconds": round(elapsed, 4),
        "CA-M1": m1,
        "CA-M2": m2,
        "CA-M3": m3,
        "CA-M4": m4,
        "CA-M5": m5,
    }

    out_path = here / "cta_models_results.json"
    out_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    manifest = {
        "study_id": prereg["study_id"],
        "executed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "hostname": platform.node(),
        "os_kernel": f"{platform.system()} {platform.release()}",
        "arch": platform.machine(),
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "fixed_seed": FIXED_SEED,
        "prereg_sha256": prereg_digest,
        "script_sha256": sha256_file(Path(__file__).resolve()),
        "results_sha256": sha256_file(out_path),
        "elapsed_seconds": round(elapsed, 4),
        "all_models_passed": all_passed,
        "board_metered": False,
    }
    (here / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"all_models_passed": all_passed, "elapsed_seconds": round(elapsed, 4)}, indent=2))


if __name__ == "__main__":
    main()

"""
HESS economic calculations — NPV, LCOH, annual cash flows.

Follows Equations 7.1–7.3 and the incremental cash-flow definition (Eq 7.2):
    CF_t = (R_t − C_t)_storage  −  (R_t − C_t)_base

NPV = Σ CF_t / (1+r)^t  for t = 0 … 25
CF_0 = −CAPEX_total  (capital investment at year 0)

Stack replacements occur every 60 000 EL operating hours and add a large
negative cash flow in the replacement year.

LCOH = (CAPEX + Σ discounted OPEX + stack replacements) / Σ discounted H2 produced
       (Eq 7.3)
"""

from __future__ import annotations

import numpy as np

from .config import HESSConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _annual_sum(arr: np.ndarray, project_years: int = 25) -> np.ndarray:
    """
    Sum an hourly array into annual totals (shape: project_years).
    Assumes exactly 8760 hours per year.
    """
    hours_per_year = 8760
    n = project_years * hours_per_year
    return arr[:n].reshape(project_years, hours_per_year).sum(axis=1)


def _discount_factor(r: float, years: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + r) ** years


# ---------------------------------------------------------------------------
# Incremental NPV
# ---------------------------------------------------------------------------

def calc_npv_incremental(
    hess_result: dict,
    base_result: dict,
    cfg: HESSConfig,
) -> float:
    """
    Compute incremental NPV [€] for the HESS configuration vs the base case.

    Stack replacement events are determined from cumulative EL operating hours.

    Parameters
    ----------
    hess_result : output of simulate_hess()
    base_result : output of simulate_base_case()
    cfg         : HESSConfig

    Returns
    -------
    npv : float  [€]
    """
    n_years = cfg.project_life_years
    r = cfg.discount_rate

    # ── Annual revenues ────────────────────────────────────────────────────
    ann_r_h2 = _annual_sum(hess_result["r_h2_eur"], n_years)
    ann_r_grid_hess = _annual_sum(hess_result["r_grid_eur"], n_years)
    ann_r_grid_base = _annual_sum(base_result["r_grid_eur"], n_years)

    # ── Annual costs ───────────────────────────────────────────────────────
    ann_opex_wfa_hess = _annual_sum(hess_result["opex_wfa_eur"], n_years)
    ann_opex_wfa_base = _annual_sum(base_result["opex_wfa_eur"], n_years)

    # Fixed annual HESS OPEX (EL + compressor + tanks)
    fixed_hess_opex = cfg.annual_opex_eur()

    # Water cost
    water_cost_per_kg = cfg.water_l_per_kg * cfg.water_cost_eur_per_l
    ann_h2_produced = _annual_sum(hess_result["m_h2_produced_kg"], n_years)
    ann_water_cost = ann_h2_produced * water_cost_per_kg

    # ── Incremental annual cash flows (years 1 … N) ────────────────────────
    ann_cf = (
        (ann_r_h2 + ann_r_grid_hess - ann_opex_wfa_hess - fixed_hess_opex - ann_water_cost)
        - (ann_r_grid_base - ann_opex_wfa_base)
    )

    # ── Stack replacement events ────────────────────────────────────────────
    cum_el_h = np.cumsum(_annual_sum(hess_result["el_running_h"], n_years))
    replacement_cost = cfg.stack_replacement_cost_eur()
    stack_events = _stack_replacement_years(cum_el_h, cfg.stack_lifetime_h)

    for yr in stack_events:
        ann_cf[yr] -= replacement_cost

    # ── Discount and sum ────────────────────────────────────────────────────
    years = np.arange(1, n_years + 1, dtype=float)
    df = _discount_factor(r, years)
    npv = -cfg.capex_total_eur + np.sum(ann_cf * df)
    return float(npv)


def _stack_replacement_years(
    cum_el_hours: np.ndarray, stack_lifetime_h: float
) -> list[int]:
    """Return 0-indexed year indices where the EL stack is replaced."""
    replacements = []
    next_threshold = stack_lifetime_h
    for yr, cum_h in enumerate(cum_el_hours):
        if cum_h >= next_threshold:
            replacements.append(yr)
            next_threshold += stack_lifetime_h
    return replacements


# ---------------------------------------------------------------------------
# Annual cash-flow breakdown (for plotting)
# ---------------------------------------------------------------------------

def annual_cashflows(
    hess_result: dict,
    base_result: dict,
    cfg: HESSConfig,
) -> dict[str, np.ndarray]:
    """
    Return a dict of annual arrays (EUR) for detailed cash-flow analysis.

    Keys: 'r_h2', 'r_grid_hess', 'r_grid_base', 'opex_wfa_hess', 'opex_wfa_base',
          'opex_hess_fixed', 'water_cost', 'stack_replacement',
          'incremental_cf', 'cumulative_npv'
    """
    n_years = cfg.project_life_years
    r = cfg.discount_rate

    ann_r_h2 = _annual_sum(hess_result["r_h2_eur"], n_years)
    ann_r_grid_hess = _annual_sum(hess_result["r_grid_eur"], n_years)
    ann_r_grid_base = _annual_sum(base_result["r_grid_eur"], n_years)
    ann_opex_wfa_hess = _annual_sum(hess_result["opex_wfa_eur"], n_years)
    ann_opex_wfa_base = _annual_sum(base_result["opex_wfa_eur"], n_years)
    fixed_hess_opex = cfg.annual_opex_eur()

    water_cost_per_kg = cfg.water_l_per_kg * cfg.water_cost_eur_per_l
    ann_h2_produced = _annual_sum(hess_result["m_h2_produced_kg"], n_years)
    ann_water_cost = ann_h2_produced * water_cost_per_kg

    ann_stack_replacement = np.zeros(n_years)
    cum_el_h = np.cumsum(_annual_sum(hess_result["el_running_h"], n_years))
    for yr in _stack_replacement_years(cum_el_h, cfg.stack_lifetime_h):
        ann_stack_replacement[yr] = cfg.stack_replacement_cost_eur()

    ann_cf = (
        (ann_r_h2 + ann_r_grid_hess - ann_opex_wfa_hess - fixed_hess_opex
         - ann_water_cost - ann_stack_replacement)
        - (ann_r_grid_base - ann_opex_wfa_base)
    )

    years = np.arange(1, n_years + 1, dtype=float)
    df = _discount_factor(r, years)
    disc_cf = ann_cf * df
    cum_npv = np.cumsum(disc_cf) - cfg.capex_total_eur

    return {
        "r_h2": ann_r_h2,
        "r_grid_hess": ann_r_grid_hess,
        "r_grid_base": ann_r_grid_base,
        "opex_wfa_hess": ann_opex_wfa_hess,
        "opex_wfa_base": ann_opex_wfa_base,
        "opex_hess_fixed": np.full(n_years, fixed_hess_opex),
        "water_cost": ann_water_cost,
        "stack_replacement": ann_stack_replacement,
        "incremental_cf": ann_cf,
        "discounted_cf": disc_cf,
        "cumulative_npv": cum_npv,
    }


# ---------------------------------------------------------------------------
# LCOH — Levelized Cost of Hydrogen (Eq 7.3)
# ---------------------------------------------------------------------------

def calc_lcoh(hess_result: dict, cfg: HESSConfig) -> float:
    """
    LCOH = (CAPEX + Σ discounted OPEX + stack replacements) / Σ discounted H2 produced
    Units: €/kg
    """
    n_years = cfg.project_life_years
    r = cfg.discount_rate
    years = np.arange(1, n_years + 1, dtype=float)
    df = _discount_factor(r, years)

    # Annual H2 produced
    ann_h2 = _annual_sum(hess_result["m_h2_produced_kg"], n_years)
    disc_h2 = np.sum(ann_h2 * df)

    if disc_h2 <= 0:
        return float("inf")

    # Annual OPEX (fixed + water)
    fixed_opex = cfg.annual_opex_eur()
    water_cost_per_kg = cfg.water_l_per_kg * cfg.water_cost_eur_per_l
    ann_water = ann_h2 * water_cost_per_kg
    ann_opex = ann_water + fixed_opex

    # Stack replacements
    ann_replacement = np.zeros(n_years)
    cum_el_h = np.cumsum(_annual_sum(hess_result["el_running_h"], n_years))
    for yr in _stack_replacement_years(cum_el_h, cfg.stack_lifetime_h):
        ann_replacement[yr] = cfg.stack_replacement_cost_eur()

    total_cost = cfg.capex_total_eur + np.sum((ann_opex + ann_replacement) * df)
    return float(total_cost / disc_h2)

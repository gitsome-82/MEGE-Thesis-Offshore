"""
HybESS economic calculations.

NPV combines incremental revenues from H2 sales and grid sales relative
to the base case, minus all CAPEX and OPEX.

Includes:
  - Battery replacement at year bess_lifetime_years (75 % of battery CAPEX)
  - EL stack replacements every stack_lifetime_h operating hours

LCOH is computed for the H2 component.
LCOS is computed for the BESS component.
"""

from __future__ import annotations

import numpy as np

from .config import HybESSConfig


def _annual_sum(arr: np.ndarray, n_years: int) -> np.ndarray:
    return arr[: n_years * 8760].reshape(n_years, 8760).sum(axis=1)


def _discount_factor(r: float, years: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + r) ** years


def _stack_replacement_years(cum_el_hours: np.ndarray, lifetime_h: float) -> list[int]:
    """Return 0-indexed project years in which a stack replacement occurs."""
    years = []
    threshold = lifetime_h
    for yr in range(len(cum_el_hours)):
        if cum_el_hours[yr] >= threshold:
            years.append(yr)
            threshold += lifetime_h
    return years


def calc_npv_incremental(
    hybess_result: dict,
    base_result: dict,
    cfg: HybESSConfig,
) -> float:
    """Incremental NPV [€] for the HybESS system."""
    n = cfg.project_life_years
    r = cfg.discount_rate
    years = np.arange(1, n + 1, dtype=float)
    df = _discount_factor(r, years)

    # Annual revenues and WFA OPEX
    ann_r_h2 = _annual_sum(hybess_result["r_h2_eur"], n)
    ann_r_grid_hyb = _annual_sum(hybess_result["r_grid_eur"], n)
    ann_opex_wfa_hyb = _annual_sum(hybess_result["opex_wfa_eur"], n)

    ann_r_grid_base = _annual_sum(base_result["r_grid_eur"], n)
    ann_opex_wfa_base = _annual_sum(base_result["opex_wfa_eur"], n)

    # Fixed OPEX
    ann_hess_opex = np.full(n, cfg.annual_opex_hess_eur())
    ann_bess_om = np.full(n, cfg.annual_bess_om_eur())

    # Battery replacement
    bess_repl = np.zeros(n)
    if cfg.bess_lifetime_years <= n:
        bess_repl[cfg.bess_lifetime_years - 1] = cfg.bess_replacement_cost_eur()

    # EL stack replacements
    ann_el_hours = _annual_sum(hybess_result["el_running_h"], n)
    cum_el_hours = np.cumsum(ann_el_hours)
    stack_years = _stack_replacement_years(cum_el_hours, cfg.stack_lifetime_h)
    stack_repl = np.zeros(n)
    for yr in stack_years:
        if yr < n:
            stack_repl[yr] += cfg.el_stack_replacement_cost_eur()

    ann_cf = (
        (ann_r_h2 + ann_r_grid_hyb - ann_opex_wfa_hyb - ann_hess_opex - ann_bess_om - bess_repl - stack_repl)
        - (ann_r_grid_base - ann_opex_wfa_base)
    )

    return float(-cfg.capex_total_eur + np.sum(ann_cf * df))


def annual_cashflows(
    hybess_result: dict,
    base_result: dict,
    cfg: HybESSConfig,
) -> dict[str, np.ndarray]:
    """Detailed annual cash-flow breakdown."""
    n = cfg.project_life_years
    r = cfg.discount_rate
    years = np.arange(1, n + 1, dtype=float)
    df = _discount_factor(r, years)

    ann_r_h2 = _annual_sum(hybess_result["r_h2_eur"], n)
    ann_r_grid_hyb = _annual_sum(hybess_result["r_grid_eur"], n)
    ann_opex_wfa_hyb = _annual_sum(hybess_result["opex_wfa_eur"], n)
    ann_r_grid_base = _annual_sum(base_result["r_grid_eur"], n)
    ann_opex_wfa_base = _annual_sum(base_result["opex_wfa_eur"], n)

    ann_hess_opex = np.full(n, cfg.annual_opex_hess_eur())
    ann_bess_om = np.full(n, cfg.annual_bess_om_eur())

    bess_repl = np.zeros(n)
    if cfg.bess_lifetime_years <= n:
        bess_repl[cfg.bess_lifetime_years - 1] = cfg.bess_replacement_cost_eur()

    ann_el_hours = _annual_sum(hybess_result["el_running_h"], n)
    cum_el_hours = np.cumsum(ann_el_hours)
    stack_years = _stack_replacement_years(cum_el_hours, cfg.stack_lifetime_h)
    stack_repl = np.zeros(n)
    for yr in stack_years:
        if yr < n:
            stack_repl[yr] += cfg.el_stack_replacement_cost_eur()

    ann_cf = (
        (ann_r_h2 + ann_r_grid_hyb - ann_opex_wfa_hyb - ann_hess_opex - ann_bess_om - bess_repl - stack_repl)
        - (ann_r_grid_base - ann_opex_wfa_base)
    )

    disc_cf = ann_cf * df
    cum_npv = np.cumsum(disc_cf) - cfg.capex_total_eur

    return {
        "r_h2": ann_r_h2,
        "r_grid_hyb": ann_r_grid_hyb,
        "r_grid_base": ann_r_grid_base,
        "opex_wfa_hyb": ann_opex_wfa_hyb,
        "opex_wfa_base": ann_opex_wfa_base,
        "hess_fixed_opex": ann_hess_opex,
        "bess_om": ann_bess_om,
        "bess_replacement": bess_repl,
        "stack_replacement": stack_repl,
        "incremental_cf": ann_cf,
        "discounted_cf": disc_cf,
        "cumulative_npv": cum_npv,
    }


def calc_lcoh(hybess_result: dict, cfg: HybESSConfig) -> float:
    """LCOH [€/kg] for the H2 component."""
    n = cfg.project_life_years
    r = cfg.discount_rate
    years = np.arange(1, n + 1, dtype=float)
    df = _discount_factor(r, years)

    ann_h2_kg = _annual_sum(hybess_result["m_h2_released_kg"], n)
    disc_h2 = np.sum(ann_h2_kg * df)
    if disc_h2 <= 0:
        return float("inf")

    ann_el_hours = _annual_sum(hybess_result["el_running_h"], n)
    cum_el_hours = np.cumsum(ann_el_hours)
    stack_years = _stack_replacement_years(cum_el_hours, cfg.stack_lifetime_h)
    stack_repl = np.zeros(n)
    for yr in stack_years:
        if yr < n:
            stack_repl[yr] += cfg.el_stack_replacement_cost_eur()

    hess_capex = (
        cfg.capex_el_eur + cfg.capex_comp_eur + cfg.capex_tanks_eur + cfg.capex_epc_eur
    )
    ann_opex_h2 = np.full(n, cfg.annual_opex_hess_eur()) + stack_repl
    total_cost = hess_capex + np.sum(ann_opex_h2 * df)
    return float(total_cost / disc_h2)


def calc_lcos(hybess_result: dict, cfg: HybESSConfig) -> float:
    """LCOS [€/MWh] for the BESS component."""
    n = cfg.project_life_years
    r = cfg.discount_rate
    years = np.arange(1, n + 1, dtype=float)
    df = _discount_factor(r, years)

    ann_discharge_mwh = _annual_sum(hybess_result["p_bess_out_mw"], n)
    disc_discharge = np.sum(ann_discharge_mwh * df)
    if disc_discharge <= 0:
        return float("inf")

    bess_capex = cfg.capex_bess_battery_eur + cfg.capex_bess_inverter_eur + cfg.capex_bess_bop_eur
    ann_om = np.full(n, cfg.annual_bess_om_eur())
    repl = np.zeros(n)
    if cfg.bess_lifetime_years <= n:
        repl[cfg.bess_lifetime_years - 1] = cfg.bess_replacement_cost_eur()
    total_cost = bess_capex + np.sum((ann_om + repl) * df)
    return float(total_cost / disc_discharge)

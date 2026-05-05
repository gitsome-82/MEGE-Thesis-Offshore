"""
BESS economic calculations — NPV (Eq 7.1–7.2) and LCOS (Eq 7.4).

LCOS = (CAPEX + Σ discounted O&M + battery replacement at yr 15) / Σ discounted energy discharged
"""

from __future__ import annotations

import numpy as np

from .config import BESSConfig


def _annual_sum(arr: np.ndarray, n_years: int) -> np.ndarray:
    return arr[: n_years * 8760].reshape(n_years, 8760).sum(axis=1)


def _discount_factor(r: float, years: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + r) ** years


def calc_npv_incremental(
    bess_result: dict,
    base_result: dict,
    cfg: BESSConfig,
) -> float:
    """
    Incremental NPV [€]:  CF_t = (R_t − C_t)_BESS  −  (R_t − C_t)_base
    Battery replacement cash flow applied at year cfg.lifetime_years.
    """
    n = cfg.project_life_years
    r = cfg.discount_rate

    ann_r_grid_bess = _annual_sum(bess_result["r_grid_eur"], n)
    ann_opex_wfa_bess = _annual_sum(bess_result["opex_wfa_eur"], n)

    ann_r_grid_base = _annual_sum(base_result["r_grid_eur"], n)
    ann_opex_wfa_base = _annual_sum(base_result["opex_wfa_eur"], n)

    ann_om = np.full(n, cfg.annual_om_eur())

    ann_cf = (
        (ann_r_grid_bess - ann_opex_wfa_bess - ann_om)
        - (ann_r_grid_base - ann_opex_wfa_base)
    )

    # Battery replacement at year lifetime_years (if within project life)
    if cfg.lifetime_years <= n:
        ann_cf[cfg.lifetime_years - 1] -= cfg.replacement_cost_eur()

    years = np.arange(1, n + 1, dtype=float)
    df = _discount_factor(r, years)
    return float(-cfg.capex_total_eur + np.sum(ann_cf * df))


def annual_cashflows(
    bess_result: dict,
    base_result: dict,
    cfg: BESSConfig,
) -> dict[str, np.ndarray]:
    """Detailed annual cash-flow breakdown."""
    n = cfg.project_life_years
    r = cfg.discount_rate

    ann_r_grid_bess = _annual_sum(bess_result["r_grid_eur"], n)
    ann_opex_wfa_bess = _annual_sum(bess_result["opex_wfa_eur"], n)
    ann_r_grid_base = _annual_sum(base_result["r_grid_eur"], n)
    ann_opex_wfa_base = _annual_sum(base_result["opex_wfa_eur"], n)
    ann_om = np.full(n, cfg.annual_om_eur())

    ann_replacement = np.zeros(n)
    if cfg.lifetime_years <= n:
        ann_replacement[cfg.lifetime_years - 1] = cfg.replacement_cost_eur()

    ann_cf = (
        (ann_r_grid_bess - ann_opex_wfa_bess - ann_om - ann_replacement)
        - (ann_r_grid_base - ann_opex_wfa_base)
    )

    years = np.arange(1, n + 1, dtype=float)
    df = _discount_factor(r, years)
    disc_cf = ann_cf * df
    cum_npv = np.cumsum(disc_cf) - cfg.capex_total_eur

    return {
        "r_grid_bess": ann_r_grid_bess,
        "r_grid_base": ann_r_grid_base,
        "opex_wfa_bess": ann_opex_wfa_bess,
        "opex_wfa_base": ann_opex_wfa_base,
        "om_bess": ann_om,
        "battery_replacement": ann_replacement,
        "incremental_cf": ann_cf,
        "discounted_cf": disc_cf,
        "cumulative_npv": cum_npv,
    }


def calc_lcos(bess_result: dict, cfg: BESSConfig) -> float:
    """
    LCOS [€/MWh] — Levelized Cost of Storage (Eq 7.4).
    LCOS = (CAPEX + Σ discounted O&M + replacement at yr15) / Σ discounted energy discharged
    """
    n = cfg.project_life_years
    r = cfg.discount_rate
    years = np.arange(1, n + 1, dtype=float)
    df_arr = _discount_factor(r, years)

    ann_discharge_mwh = _annual_sum(bess_result["p_bess_out_ac_mw"], n)  # MWh/yr
    disc_discharge = np.sum(ann_discharge_mwh * df_arr)

    if disc_discharge <= 0:
        return float("inf")

    ann_om = np.full(n, cfg.annual_om_eur())
    ann_replacement = np.zeros(n)
    if cfg.lifetime_years <= n:
        ann_replacement[cfg.lifetime_years - 1] = cfg.replacement_cost_eur()

    total_cost = cfg.capex_total_eur + np.sum((ann_om + ann_replacement) * df_arr)
    return float(total_cost / disc_discharge)

"""
HESS hourly dispatch simulation — implements Figure 6.5 of the thesis.

Decision logic (per hour)
--------------------------
1. H2 withdrawal: always release withdraw_rate_daily/24 × cap_tanks from the tank
   (if SOC < 5 %, release everything remaining).

2. Dispatch decision tree (Figure 6.5):

   IF price < p_storage:                    ← hydrogen production mode
       IF SOC_H2 < 1:                       ← tank not full
           Produce H2 (P_EL = min(P_onshore, P_EL_cap, P_allowed))
           IF price > OPEX_WFA → also sell remainder to grid  [H2+Grid]
           ELSE                → curtail remainder             [H2]
       ELSE (tank full):
           IF price > OPEX_WFA → grid                         [Grid]
           ELSE                → curtail                      [Curtailment]
   ELSE (price ≥ p_storage):               ← prefer grid
       IF price > OPEX_WFA → grid                             [Grid]
       ELSE                → curtail                          [Curtailment]

3. Revenue: R_H2 = m_released × p_H2 ;  R_grid = P_grid × price × dt
4. OPEX_WFA accrues every hour based on wind farm output (before tx loss).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import HESSConfig


# ---------------------------------------------------------------------------
# Base case dispatch (no storage) — reference for incremental NPV
# ---------------------------------------------------------------------------

def simulate_base_case(
    wind_mw: np.ndarray,
    prices: np.ndarray,
    cfg: HESSConfig,
) -> dict[str, np.ndarray]:
    """
    Base case: inject to grid if price > OPEX_WFA, else curtail (Figure 6.2).

    Parameters
    ----------
    wind_mw : hourly wind farm output BEFORE transmission losses [MW]
    prices  : hourly electricity prices [EUR/MWh]
    cfg     : HESSConfig

    Returns
    -------
    dict with arrays: p_grid_mw, p_curtailed_mw, r_grid_eur, opex_wfa_eur
    """
    n = len(wind_mw)
    p_onshore = wind_mw * (1.0 - cfg.tx_loss)

    inject = prices > cfg.opex_wfa_mwh
    p_grid = np.where(inject, p_onshore, 0.0)
    p_curtailed = np.where(inject, 0.0, p_onshore)

    r_grid = p_grid * prices * 1.0  # dt = 1 h
    opex_wfa = cfg.opex_wfa_mwh * wind_mw * 1.0

    return {
        "p_grid_mw": p_grid,
        "p_curtailed_mw": p_curtailed,
        "r_grid_eur": r_grid,
        "opex_wfa_eur": opex_wfa,
    }


# ---------------------------------------------------------------------------
# HESS dispatch
# ---------------------------------------------------------------------------

def simulate_hess(
    wind_mw: np.ndarray,
    prices: np.ndarray,
    cfg: HESSConfig,
    p_storage: float | None = None,
    initial_soc: float = 0.0,
) -> dict[str, np.ndarray]:
    """
    Run full HESS hourly dispatch simulation (Figure 6.5).

    Parameters
    ----------
    wind_mw     : hourly wind farm output BEFORE tx losses [MW], shape (N,)
    prices      : hourly day-ahead electricity prices [EUR/MWh], shape (N,)
    cfg         : HESSConfig
    p_storage   : control threshold [EUR/MWh]; if None, uses cfg.p_storage
    initial_soc : initial H2 tank state-of-charge [0–1]

    Returns
    -------
    dict with hourly result arrays (length N):
        p_el_mw, p_grid_mw, p_curtailed_mw,
        m_h2_produced_kg, m_h2_released_kg, m_h2_tank_kg, soc_h2,
        r_h2_eur, r_grid_eur, opex_wfa_eur, el_running_h,
        actions (str array: 'H2', 'H2+Grid', 'Grid', 'Curtailment')
    """
    if p_storage is None:
        p_storage = cfg.p_storage

    n = len(wind_mw)
    dt = 1.0  # 1-hour timestep

    # Onshore power after transmission loss
    p_onshore = wind_mw * (1.0 - cfg.tx_loss)

    # Tank parameters
    cap_kg = cfg.cap_h2_tanks_kg
    withdraw_per_hour = (cfg.withdraw_rate_daily / 24.0) * cap_kg
    soc_floor = cfg.withdraw_rate_daily  # 5 %

    # EL capacity in MW
    p_el_cap_mw = cfg.p_el_mw

    # Output arrays
    p_el_mw = np.zeros(n)
    p_grid_mw = np.zeros(n)
    p_curtailed_mw = np.zeros(n)
    m_h2_produced = np.zeros(n)
    m_h2_released = np.zeros(n)
    m_h2_tank = np.zeros(n)
    r_h2_eur = np.zeros(n)
    r_grid_eur = np.zeros(n)
    opex_wfa_eur = np.zeros(n)
    el_running = np.zeros(n)  # 1 if EL is operating this hour
    actions = np.empty(n, dtype=object)

    m_tank = initial_soc * cap_kg  # initial stored hydrogen [kg]

    for t in range(n):
        pw = p_onshore[t]
        p = prices[t]

        # ── Step 1: H2 withdrawal ──────────────────────────────────────────
        soc = m_tank / cap_kg if cap_kg > 0 else 0.0
        if soc <= soc_floor:
            release = m_tank  # release all if nearly empty
        else:
            release = min(withdraw_per_hour, m_tank)
        m_h2_released[t] = release
        r_h2_eur[t] = release * cfg.p_h2_eur_per_kg
        # Update tank after withdrawal (before production)
        m_tank = max(0.0, m_tank - release)

        # ── Step 2: Power budget for EL (won't exceed tank capacity) ──────
        m_available = cap_kg - m_tank
        p_allowed_mw = (m_available * cfg.e_pem_kwh_per_kg) / (dt * 1_000.0)  # MW

        # ── Step 3: Dispatch decision (Figure 6.5) ────────────────────────
        soc_after_withdraw = m_tank / cap_kg if cap_kg > 0 else 0.0

        if p < p_storage:
            # Hydrogen production mode
            if soc_after_withdraw < 1.0:
                # Produce H2
                p_el = min(pw, p_el_cap_mw, p_allowed_mw)
                p_el_mw[t] = p_el
                m_produced = (p_el * 1_000.0 * dt) / cfg.e_pem_kwh_per_kg  # kg
                m_h2_produced[t] = m_produced
                el_running[t] = 1.0 if p_el > 0 else 0.0

                p_rem = pw - p_el
                if p > cfg.opex_wfa_mwh:
                    p_grid_mw[t] = p_rem
                    r_grid_eur[t] = p_rem * p * dt
                    actions[t] = "H2+Grid"
                else:
                    p_curtailed_mw[t] = p_rem
                    actions[t] = "H2"
            else:
                # Tank full → no H2 production
                if p > cfg.opex_wfa_mwh:
                    p_grid_mw[t] = pw
                    r_grid_eur[t] = pw * p * dt
                    actions[t] = "Grid"
                else:
                    p_curtailed_mw[t] = pw
                    actions[t] = "Curtailment"
        else:
            # Prefer grid injection
            if p > cfg.opex_wfa_mwh:
                p_grid_mw[t] = pw
                r_grid_eur[t] = pw * p * dt
                actions[t] = "Grid"
            else:
                p_curtailed_mw[t] = pw
                actions[t] = "Curtailment"

        # ── Step 4: Wind farm OPEX (based on total wind output) ───────────
        opex_wfa_eur[t] = cfg.opex_wfa_mwh * wind_mw[t] * dt

        # ── Step 5: Update tank ───────────────────────────────────────────
        m_tank = min(cap_kg, max(0.0, m_tank + m_h2_produced[t]))
        m_h2_tank[t] = m_tank

    return {
        "p_el_mw": p_el_mw,
        "p_grid_mw": p_grid_mw,
        "p_curtailed_mw": p_curtailed_mw,
        "m_h2_produced_kg": m_h2_produced,
        "m_h2_released_kg": m_h2_released,
        "m_h2_tank_kg": m_h2_tank,
        "soc_h2": m_h2_tank / cap_kg if cap_kg > 0 else np.zeros(n),
        "r_h2_eur": r_h2_eur,
        "r_grid_eur": r_grid_eur,
        "opex_wfa_eur": opex_wfa_eur,
        "el_running_h": el_running,
        "actions": actions,
    }


# ---------------------------------------------------------------------------
# Threshold optimiser — maximise NPV over single p_storage value
# ---------------------------------------------------------------------------

def optimise_p_storage(
    wind_mw: np.ndarray,
    prices: np.ndarray,
    cfg: HESSConfig,
    price_percentiles: np.ndarray | None = None,
) -> tuple[float, float]:
    """
    Grid-search over candidate p_storage values to maximise NPV.

    Parameters
    ----------
    price_percentiles : candidate threshold values [EUR/MWh].
                        Defaults to 5th–95th percentile range (50 values).

    Returns
    -------
    (best_p_storage, best_npv)
    """
    from .economics import calc_npv_incremental

    if price_percentiles is None:
        price_percentiles = np.percentile(prices[prices > 0], np.linspace(5, 95, 50))

    best_ps, best_npv = cfg.p_storage, -np.inf
    for ps in price_percentiles:
        res = simulate_hess(wind_mw, prices, cfg, p_storage=ps)
        base = simulate_base_case(wind_mw, prices, cfg)
        npv = calc_npv_incremental(res, base, cfg)
        if npv > best_npv:
            best_npv = npv
            best_ps = ps

    return float(best_ps), float(best_npv)

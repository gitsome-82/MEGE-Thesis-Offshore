"""
BESS hourly dispatch — implements Figure 6.7 of the thesis.

Three operating regimes per hour (determined by price vs thresholds):

  CHARGING  (price < p_charge):
    SOC < SOCmax:
      price > OPEX_WFA → Charge Batteries + Wind Power to Grid  [ChargeLIB+Grid]
      price ≤ OPEX_WFA → Charge Batteries + Partial Curtailment [ChargeLIB]
    SOC = SOCmax (battery full):
      price > OPEX_WFA → Wind Power to Grid                     [Grid]
      price ≤ OPEX_WFA → Economic Curtailment                   [Curtailment]

  NEUTRAL  (p_charge ≤ price ≤ p_discharge):
    price > OPEX_WFA → Wind Power to Grid                       [Grid]
    price ≤ OPEX_WFA → Economic Curtailment                     [Curtailment]

  DISCHARGING  (price > p_discharge):
    SOC > SOCmin → Discharge Batteries + Wind Power to Grid     [DischargeLIB+Grid]
    SOC = SOCmin → Grid (or curtail if price ≤ OPEX)            [Grid / Curtailment]

Control thresholds (p_charge, p_discharge) are optimised daily to maximise
daily operational profit, following Section 7.2.2 of the thesis.

Battery energy update (Eq 3.31, r_SD = 0):
    E_new = E_old + (η_in_total × P_in_AC − P_out_DC / η_out_total) × dt
where:
    η_in_total  = η_inverter × η_lib_in   (AC → battery)
    η_out_total = η_lib_out × η_inverter  (battery → AC)
"""

from __future__ import annotations

import numpy as np

from .config import BESSConfig


# ---------------------------------------------------------------------------
# Single-hour BESS step
# ---------------------------------------------------------------------------

def _bess_step(
    p_wind_onshore: float,
    price: float,
    e_lib: float,
    cfg: BESSConfig,
    p_charge: float,
    p_discharge: float,
) -> tuple[float, float, float, float, float, str]:
    """
    Compute one BESS hour.

    Returns
    -------
    (p_grid, p_curtailed, p_bess_in_ac, p_bess_out_ac, e_lib_new, action)
    All power in MW, energy in MWh.
    """
    cap = cfg.cap_lib_mwh
    eta_in = cfg.eta_inverter * cfg.eta_lib_in     # AC → stored
    eta_out = cfg.eta_lib_out * cfg.eta_inverter   # stored → AC
    dt = 1.0

    p_grid = 0.0
    p_curtailed = 0.0
    p_bess_in_ac = 0.0
    p_bess_out_ac = 0.0
    action = "Grid"

    if price < p_charge:
        # ── Charging regime ──────────────────────────────────────────
        if e_lib < cfg.soc_max * cap:
            # Max AC input limited by: inverter cap, battery cap, SOC headroom
            p_in_ac_max_inv = cfg.rated_power_mw
            p_in_ac_max_soc = (cfg.soc_max * cap - e_lib) / (eta_in * dt)
            p_in_ac = min(p_wind_onshore, p_in_ac_max_inv, p_in_ac_max_soc)
            p_in_ac = max(0.0, p_in_ac)

            p_bess_in_ac = p_in_ac
            e_lib_new = e_lib + p_in_ac * eta_in * dt

            p_rem = p_wind_onshore - p_in_ac
            if price > cfg.opex_wfa_mwh:
                p_grid = p_rem
                action = "ChargeLIB+Grid"
            else:
                p_curtailed = p_rem
                action = "ChargeLIB"
        else:
            # Battery full — fall through to neutral logic
            if price > cfg.opex_wfa_mwh:
                p_grid = p_wind_onshore
                action = "Grid"
            else:
                p_curtailed = p_wind_onshore
                action = "Curtailment"
            e_lib_new = e_lib

    elif price > p_discharge:
        # ── Discharging regime ────────────────────────────────────────
        if e_lib > cfg.soc_min * cap:
            # Max DC output: power cap, SOC floor
            p_out_dc_max_cap = cfg.rated_power_mw / eta_out  # DC power needed for rated AC output
            p_out_dc_max_soc = (e_lib - cfg.soc_min * cap) / dt
            p_out_dc = min(p_out_dc_max_cap, p_out_dc_max_soc)
            p_out_dc = max(0.0, p_out_dc)

            p_bess_out_ac = p_out_dc * eta_out
            e_lib_new = e_lib - p_out_dc * dt
            p_grid = p_wind_onshore + p_bess_out_ac
            action = "DischargeLIB+Grid"
        else:
            # Battery empty
            if price > cfg.opex_wfa_mwh:
                p_grid = p_wind_onshore
                action = "Grid"
            else:
                p_curtailed = p_wind_onshore
                action = "Curtailment"
            e_lib_new = e_lib

    else:
        # ── Neutral regime ────────────────────────────────────────────
        if price > cfg.opex_wfa_mwh:
            p_grid = p_wind_onshore
            action = "Grid"
        else:
            p_curtailed = p_wind_onshore
            action = "Curtailment"
        e_lib_new = e_lib

    # Apply self-discharge (r_SD = 0, but keep for completeness)
    e_lib_new *= (1.0 - cfg.r_sd)
    e_lib_new = max(cfg.soc_min * cap, min(cfg.soc_max * cap, e_lib_new))

    return p_grid, p_curtailed, p_bess_in_ac, p_bess_out_ac, e_lib_new, action


# ---------------------------------------------------------------------------
# Full simulation (fixed thresholds — for use during daily optimisation)
# ---------------------------------------------------------------------------

def simulate_bess_fixed(
    wind_onshore: np.ndarray,
    prices: np.ndarray,
    cfg: BESSConfig,
    p_charge: float,
    p_discharge: float,
    initial_e: float = 0.0,
) -> dict[str, np.ndarray]:
    """Run BESS dispatch with fixed thresholds (no daily optimisation)."""
    n = len(wind_onshore)
    p_grid = np.zeros(n)
    p_curtailed = np.zeros(n)
    p_in_ac = np.zeros(n)
    p_out_ac = np.zeros(n)
    e_lib = np.zeros(n)
    actions = np.empty(n, dtype=object)

    e = initial_e
    for t in range(n):
        g, c, pi, po, e, act = _bess_step(
            wind_onshore[t], prices[t], e, cfg, p_charge, p_discharge
        )
        p_grid[t] = g
        p_curtailed[t] = c
        p_in_ac[t] = pi
        p_out_ac[t] = po
        e_lib[t] = e
        actions[t] = act

    return {
        "p_grid_mw": p_grid,
        "p_curtailed_mw": p_curtailed,
        "p_bess_in_ac_mw": p_in_ac,
        "p_bess_out_ac_mw": p_out_ac,
        "e_lib_mwh": e_lib,
        "soc": e_lib / cfg.cap_lib_mwh,
        "actions": actions,
    }


# ---------------------------------------------------------------------------
# Daily-optimised simulation (Section 7.2.2)
# ---------------------------------------------------------------------------

def simulate_bess(
    wind_mw: np.ndarray,
    prices: np.ndarray,
    cfg: BESSConfig,
    n_grid: int = 10,
) -> dict[str, np.ndarray]:
    """
    Run 25-year BESS dispatch with daily optimisation of (p_charge, p_discharge).

    For each calendar day, a grid search over n_grid × n_grid threshold combinations
    (based on price percentiles of that day) is used to maximise the day's operational
    profit. The winning thresholds are then used to simulate that day.

    Parameters
    ----------
    wind_mw : hourly wind farm output BEFORE tx losses [MW]
    prices  : hourly electricity prices [EUR/MWh]
    cfg     : BESSConfig
    n_grid  : number of percentile steps per threshold dimension (default 10)

    Returns
    -------
    dict with hourly result arrays + 'r_grid_eur', 'opex_wfa_eur'
    """
    n = len(wind_mw)
    p_onshore = wind_mw * (1.0 - cfg.tx_loss)

    p_grid = np.zeros(n)
    p_curtailed = np.zeros(n)
    p_in_ac = np.zeros(n)
    p_out_ac = np.zeros(n)
    e_lib_arr = np.zeros(n)
    r_grid = np.zeros(n)
    opex_wfa = np.zeros(n)
    actions = np.empty(n, dtype=object)

    hours_per_day = 24
    e_lib = 0.0  # initial state of charge

    for day_start in range(0, n, hours_per_day):
        day_end = min(day_start + hours_per_day, n)
        day_prices = prices[day_start:day_end]
        day_wind = p_onshore[day_start:day_end]

        # Candidate threshold values: percentiles of today's prices
        if len(day_prices) < 4 or np.all(day_prices == day_prices[0]):
            pc_cands = [day_prices[0] * 0.9]
            pd_cands = [day_prices[0] * 1.1]
        else:
            pc_cands = np.percentile(day_prices, np.linspace(5, 50, n_grid))
            pd_cands = np.percentile(day_prices, np.linspace(50, 95, n_grid))

        # Grid search: maximise daily operational profit
        best_profit = -np.inf
        best_pc, best_pd = cfg.p_charge, cfg.p_discharge

        for pc in pc_cands:
            for pd in pd_cands:
                if pc >= pd:
                    continue
                profit = _daily_profit(day_wind, day_prices, cfg, pc, pd, e_lib)
                if profit > best_profit:
                    best_profit = profit
                    best_pc = pc
                    best_pd = pd

        # Simulate day with best thresholds
        d_len = day_end - day_start
        e_day = e_lib
        for i in range(d_len):
            t = day_start + i
            g, c, pi, po, e_day, act = _bess_step(
                p_onshore[t], prices[t], e_day, cfg, best_pc, best_pd
            )
            p_grid[t] = g
            p_curtailed[t] = c
            p_in_ac[t] = pi
            p_out_ac[t] = po
            e_lib_arr[t] = e_day
            r_grid[t] = g * prices[t] * 1.0
            opex_wfa[t] = cfg.opex_wfa_mwh * wind_mw[t] * 1.0
            actions[t] = act
        e_lib = e_day

    return {
        "p_grid_mw": p_grid,
        "p_curtailed_mw": p_curtailed,
        "p_bess_in_ac_mw": p_in_ac,
        "p_bess_out_ac_mw": p_out_ac,
        "e_lib_mwh": e_lib_arr,
        "soc": e_lib_arr / cfg.cap_lib_mwh,
        "r_grid_eur": r_grid,
        "opex_wfa_eur": opex_wfa,
        "actions": actions,
    }


def _daily_profit(
    day_wind: np.ndarray,
    day_prices: np.ndarray,
    cfg: BESSConfig,
    p_charge: float,
    p_discharge: float,
    e_initial: float,
) -> float:
    """Fast evaluation of daily operational profit for given thresholds."""
    e = e_initial
    profit = 0.0
    for i in range(len(day_wind)):
        g, _, pi, _, e, _ = _bess_step(day_wind[i], day_prices[i], e, cfg, p_charge, p_discharge)
        profit += g * day_prices[i]  # revenue
    return profit

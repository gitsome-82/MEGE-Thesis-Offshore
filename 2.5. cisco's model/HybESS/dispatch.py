"""
HybESS hourly dispatch — implements Figures 6.9, 6.10 and Section 6.5.1.

===========================================================================
BASIC HybESS strategy (enhanced=False)
===========================================================================
Three price regimes (same BESS thresholds p_charge / p_discharge):

  CHARGING (price < p_charge):
    SOC_BESS < SOCmax:
      → Charge BESS; remainder → Grid if price>OPEX, else curtail
    SOC_BESS = SOCmax AND SOC_H2 < 1:
      → Produce H2 (EL at rated power, capped by available wind);
        remainder → Grid if price>OPEX, else curtail
    Both full:
      → Grid if price>OPEX, else curtail

  NEUTRAL (p_charge ≤ price ≤ p_discharge):
    → Grid if price>OPEX, else curtail  (no storage action)

  DISCHARGING (price > p_discharge):
    SOC_BESS > 0: Discharge BESS + wind → Grid
    SOC_BESS = 0: Grid if price>OPEX, else curtail
    (H2 tank is managed by fixed daily withdrawal, independent of price)

===========================================================================
ENHANCED HybESS strategy (enhanced=True) — Section 6.5.1
===========================================================================
  CHARGING (price < p_charge):
    → BESS charges (up to rated power)
    → SIMULTANEOUSLY: remaining excess → H2 production if SOC_H2 < 1
    → Any residual → Grid if price>OPEX, else curtail

  NEUTRAL & DISCHARGING: identical to basic strategy.

===========================================================================
H2 tank withdrawal logic (same as HESS):
  Each hour BEFORE the dispatch decision:
    if SOC_H2 ≤ 5%: release all remaining H2
    else: release min(daily_rate/24, m_tank)
  The H2 revenue is then credited regardless of price.
===========================================================================
"""

from __future__ import annotations

import numpy as np

from .config import HybESSConfig


# ---------------------------------------------------------------------------
# Battery step (same as BESS dispatch, isolated here for clarity)
# ---------------------------------------------------------------------------

def _bess_in_step(
    p_available: float,
    e_lib: float,
    cfg: HybESSConfig,
) -> tuple[float, float]:
    """Charge BESS as much as possible. Returns (p_consumed_ac, e_lib_new)."""
    cap = cfg.cap_lib_mwh
    eta_in = cfg.eta_inverter * cfg.eta_lib_in
    p_in_ac_max_inv = cfg.rated_power_mw
    p_in_ac_max_soc = (cfg.soc_max_bess * cap - e_lib) / (eta_in * 1.0)
    p_in_ac = min(p_available, p_in_ac_max_inv, max(0.0, p_in_ac_max_soc))
    e_new = e_lib + p_in_ac * eta_in
    e_new = max(cfg.soc_min_bess * cap, min(cfg.soc_max_bess * cap, e_new))
    return p_in_ac, e_new


def _bess_out_step(
    e_lib: float,
    cfg: HybESSConfig,
) -> tuple[float, float]:
    """Discharge BESS as much as possible. Returns (p_out_ac, e_lib_new)."""
    cap = cfg.cap_lib_mwh
    eta_out = cfg.eta_lib_out * cfg.eta_inverter
    p_out_dc_max_cap = cfg.rated_power_mw / eta_out
    p_out_dc_max_soc = (e_lib - cfg.soc_min_bess * cap) / 1.0
    p_out_dc = min(p_out_dc_max_cap, max(0.0, p_out_dc_max_soc))
    p_out_ac = p_out_dc * eta_out
    e_new = e_lib - p_out_dc
    e_new = max(cfg.soc_min_bess * cap, min(cfg.soc_max_bess * cap, e_new))
    return p_out_ac, e_new


# ---------------------------------------------------------------------------
# H2 withdrawal (pre-dispatch)
# ---------------------------------------------------------------------------

def _h2_withdrawal(m_tank: float, cap_h2: float, withdraw_daily: float) -> float:
    soc_h2 = m_tank / cap_h2 if cap_h2 > 0 else 0.0
    if soc_h2 <= 0.05:
        return m_tank
    return min(withdraw_daily / 24.0, m_tank)


# ---------------------------------------------------------------------------
# Full simulation
# ---------------------------------------------------------------------------

def simulate_hybess(
    wind_mw: np.ndarray,
    prices: np.ndarray,
    cfg: HybESSConfig,
    n_grid: int = 10,
    initial_soc_bess: float = 0.0,
    initial_h2_kg: float = 0.0,
) -> dict[str, np.ndarray]:
    """
    Run 25-year HybESS dispatch with daily BESS threshold optimisation.

    Parameters
    ----------
    wind_mw : hourly wind farm output BEFORE tx losses [MW]
    prices  : hourly electricity prices [EUR/MWh]
    cfg     : HybESSConfig (enhanced flag respected)
    n_grid  : grid resolution for daily threshold optimisation
    """
    n = len(wind_mw)
    p_onshore = wind_mw * (1.0 - cfg.tx_loss)

    # Output arrays
    p_grid = np.zeros(n)
    p_curtailed = np.zeros(n)
    p_el = np.zeros(n)
    p_bess_in = np.zeros(n)
    p_bess_out = np.zeros(n)
    m_h2_prod = np.zeros(n)
    m_h2_released = np.zeros(n)
    m_h2_tank = np.zeros(n)
    soc_h2 = np.zeros(n)
    soc_bess = np.zeros(n)
    r_h2 = np.zeros(n)
    r_grid = np.zeros(n)
    opex_wfa = np.zeros(n)
    el_running_h = np.zeros(n)
    actions = np.empty(n, dtype=object)

    # Derived constants
    h2_rate_max_kg_per_h = (cfg.p_el_mw * 1_000.0) / cfg.e_pem_kwh_per_kg  # kg/h at full EL power

    e_lib = initial_soc_bess * cfg.cap_lib_mwh
    m_tank = initial_h2_kg

    hours_per_day = 24

    for day_start in range(0, n, hours_per_day):
        day_end = min(day_start + hours_per_day, n)
        day_prices = prices[day_start:day_end]
        day_wind = p_onshore[day_start:day_end]

        # --- Daily threshold optimisation (BESS thresholds only) ---
        if len(day_prices) < 4 or np.all(day_prices == day_prices[0]):
            best_pc, best_pd = cfg.p_charge, cfg.p_discharge
        else:
            pc_cands = np.percentile(day_prices, np.linspace(5, 50, n_grid))
            pd_cands = np.percentile(day_prices, np.linspace(50, 95, n_grid))
            best_profit = -np.inf
            best_pc, best_pd = cfg.p_charge, cfg.p_discharge
            for pc in pc_cands:
                for pd in pd_cands:
                    if pc >= pd:
                        continue
                    profit = _daily_profit(
                        day_wind, day_prices, cfg, pc, pd, e_lib, m_tank
                    )
                    if profit > best_profit:
                        best_profit = profit
                        best_pc, best_pd = pc, pd

        # --- Simulate day hour by hour ---
        for i in range(day_end - day_start):
            t = day_start + i
            pw = p_onshore[t]
            price = prices[t]

            # 1. H2 tank withdrawal (pre-dispatch)
            m_released = _h2_withdrawal(m_tank, cfg.cap_h2_tanks_kg, cfg.withdraw_rate_daily)
            m_tank -= m_released
            r_h2[t] = m_released * cfg.p_h2_eur_per_kg
            m_h2_released[t] = m_released

            # 2. Dispatch decision
            if price < best_pc:
                # ── CHARGING REGIME ───────────────────────────────────
                if cfg.enhanced:
                    # Enhanced: BESS charges first, remaining → H2
                    p_in_ac, e_lib = _bess_in_step(pw, e_lib, cfg)
                    p_rem_bess = pw - p_in_ac
                    p_bess_in[t] = p_in_ac

                    # H2 production from remainder
                    p_el_t = 0.0
                    m_prod = 0.0
                    soc_h2_now = m_tank / cfg.cap_h2_tanks_kg if cfg.cap_h2_tanks_kg > 0 else 1.0
                    if soc_h2_now < 1.0 and p_rem_bess > 0:
                        p_el_t = min(p_rem_bess, cfg.p_el_mw)
                        m_prod = p_el_t * 1_000.0 / cfg.e_pem_kwh_per_kg  # kg/h
                        m_tank_cap_room = (1.0 - soc_h2_now) * cfg.cap_h2_tanks_kg
                        m_prod = min(m_prod, m_tank_cap_room)
                        p_el_t = m_prod * cfg.e_pem_kwh_per_kg / 1_000.0
                    p_el[t] = p_el_t
                    m_h2_prod[t] = m_prod
                    m_tank += m_prod
                    el_running_h[t] = 1.0 if p_el_t > 0 else 0.0

                    p_rem2 = pw - p_in_ac - p_el_t
                    if price > cfg.opex_wfa_mwh:
                        p_grid[t] = p_rem2
                        action = "Enhanced:ChargeBESS+H2+Grid"
                    else:
                        p_curtailed[t] = p_rem2
                        action = "Enhanced:ChargeBESS+H2"

                else:
                    # Basic: BESS priority; if full → H2
                    soc_bess_now = e_lib / cfg.cap_lib_mwh if cfg.cap_lib_mwh > 0 else 1.0
                    soc_h2_now = m_tank / cfg.cap_h2_tanks_kg if cfg.cap_h2_tanks_kg > 0 else 1.0

                    if soc_bess_now < cfg.soc_max_bess:
                        p_in_ac, e_lib = _bess_in_step(pw, e_lib, cfg)
                        p_bess_in[t] = p_in_ac
                        p_rem = pw - p_in_ac
                        if price > cfg.opex_wfa_mwh:
                            p_grid[t] = p_rem
                            action = "ChargeBESS+Grid"
                        else:
                            p_curtailed[t] = p_rem
                            action = "ChargeBESS"
                    elif soc_h2_now < 1.0:
                        p_el_t = min(pw, cfg.p_el_mw)
                        m_prod = p_el_t * 1_000.0 / cfg.e_pem_kwh_per_kg
                        m_tank_room = (1.0 - soc_h2_now) * cfg.cap_h2_tanks_kg
                        m_prod = min(m_prod, m_tank_room)
                        p_el_t = m_prod * cfg.e_pem_kwh_per_kg / 1_000.0
                        p_el[t] = p_el_t
                        m_h2_prod[t] = m_prod
                        m_tank += m_prod
                        el_running_h[t] = 1.0 if p_el_t > 0 else 0.0
                        p_rem = pw - p_el_t
                        if price > cfg.opex_wfa_mwh:
                            p_grid[t] = p_rem
                            action = "ProduceH2+Grid"
                        else:
                            p_curtailed[t] = p_rem
                            action = "ProduceH2"
                    else:
                        # Both full
                        if price > cfg.opex_wfa_mwh:
                            p_grid[t] = pw
                            action = "Grid"
                        else:
                            p_curtailed[t] = pw
                            action = "Curtailment"

            elif price > best_pd:
                # ── DISCHARGING REGIME ────────────────────────────────
                soc_bess_now = e_lib / cfg.cap_lib_mwh if cfg.cap_lib_mwh > 0 else 0.0
                if soc_bess_now > cfg.soc_min_bess:
                    p_out_ac, e_lib = _bess_out_step(e_lib, cfg)
                    p_bess_out[t] = p_out_ac
                    p_grid[t] = pw + p_out_ac
                    action = "DischargeBESS+Grid"
                else:
                    if price > cfg.opex_wfa_mwh:
                        p_grid[t] = pw
                        action = "Grid"
                    else:
                        p_curtailed[t] = pw
                        action = "Curtailment"

            else:
                # ── NEUTRAL REGIME ────────────────────────────────────
                if price > cfg.opex_wfa_mwh:
                    p_grid[t] = pw
                    action = "Grid"
                else:
                    p_curtailed[t] = pw
                    action = "Curtailment"

            r_grid[t] = p_grid[t] * price
            opex_wfa[t] = cfg.opex_wfa_mwh * wind_mw[t]
            m_h2_tank[t] = m_tank
            soc_h2[t] = m_tank / cfg.cap_h2_tanks_kg if cfg.cap_h2_tanks_kg > 0 else 0.0
            soc_bess[t] = e_lib / cfg.cap_lib_mwh if cfg.cap_lib_mwh > 0 else 0.0
            actions[t] = action

    return {
        "p_grid_mw": p_grid,
        "p_curtailed_mw": p_curtailed,
        "p_el_mw": p_el,
        "p_bess_in_mw": p_bess_in,
        "p_bess_out_mw": p_bess_out,
        "m_h2_prod_kg": m_h2_prod,
        "m_h2_released_kg": m_h2_released,
        "m_h2_tank_kg": m_h2_tank,
        "soc_h2": soc_h2,
        "soc_bess": soc_bess,
        "r_h2_eur": r_h2,
        "r_grid_eur": r_grid,
        "opex_wfa_eur": opex_wfa,
        "el_running_h": el_running_h,
        "actions": actions,
    }


def _daily_profit(
    day_wind: np.ndarray,
    day_prices: np.ndarray,
    cfg: HybESSConfig,
    p_charge: float,
    p_discharge: float,
    e_lib: float,
    m_tank: float,
) -> float:
    """Fast daily profit evaluation for threshold optimisation (no H2 update)."""
    e = e_lib
    m = m_tank
    profit = 0.0
    for i in range(len(day_wind)):
        pw = day_wind[i]
        price = day_prices[i]
        if price < p_charge:
            if cfg.enhanced:
                p_in_ac, e = _bess_in_step(pw, e, cfg)
                p_rem = pw - p_in_ac
                profit += max(0.0, p_rem) * price if price > cfg.opex_wfa_mwh else 0.0
            else:
                soc_b = e / cfg.cap_lib_mwh if cfg.cap_lib_mwh > 0 else 1.0
                if soc_b < cfg.soc_max_bess:
                    p_in_ac, e = _bess_in_step(pw, e, cfg)
                    p_rem = pw - p_in_ac
                    profit += p_rem * price if price > cfg.opex_wfa_mwh else 0.0
                else:
                    profit += pw * price if price > cfg.opex_wfa_mwh else 0.0
        elif price > p_discharge:
            soc_b = e / cfg.cap_lib_mwh if cfg.cap_lib_mwh > 0 else 0.0
            if soc_b > cfg.soc_min_bess:
                p_out_ac, e = _bess_out_step(e, cfg)
                profit += (pw + p_out_ac) * price
            else:
                profit += pw * price if price > cfg.opex_wfa_mwh else 0.0
        else:
            profit += pw * price if price > cfg.opex_wfa_mwh else 0.0
    return profit

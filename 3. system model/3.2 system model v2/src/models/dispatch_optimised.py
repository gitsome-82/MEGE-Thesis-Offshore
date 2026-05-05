"""
dispatch_optimised.py — Day-ahead LP dispatch optimiser.

Replaces the rule-based dispatch engine (dispatch.py) with a linear programme
that finds the globally-optimal hourly decisions over a rolling horizon.

TWO OBJECTIVES
──────────────
  "revenue"  Maximise electricity revenue + H₂ offtake revenue, minus battery
             cycling costs (energy-trader / arbitrage strategy).
             Charges battery / electrolyser when prices are low; sells when
             prices are high.  Electrolyser vs grid decision is determined by
             the LP based on relative values — no hard priority rule needed.

  "h2"       Maximise total H₂ production volume (green-H₂ producer strategy).
             Runs electrolyser as hard as wind and tank allow; grid absorbs
             surplus when the tank is full.  Useful for industrial H₂ supply
             contracts where volume matters more than price arbitrage.

SOLVER ABSTRACTION
──────────────────
All LP calls go through _solve_lp().  To swap in a more powerful solver
(Gurobi, CPLEX, HiGHS via PuLP, Pyomo + SCIP, OR-Tools):
  1. Replace _solve_lp() — that is the only function you need to change.
  2. The LP arrays (c, A_eq, b_eq, bounds) built by _build_lp() are
     standard and compatible with any LP/MILP solver.

ROLLING HORIZON
───────────────
  horizon_hours = 24 (default) — solve one 24-h window at a time.
  step_hours    = 24 (default) — apply all 24 h, then advance.
                  Matches the day-ahead electricity market structure.
  step_hours    = 1            — MPC-style receding-horizon control:
                  solve 24 h, apply only the first hour, re-optimise.
                  Slower but avoids end-of-horizon artefacts.

OUTPUT
──────
Same column names as run_dispatch() → drop-in replacement in run_scenario.py.
Two extra columns added: fc_power_mwh, fc_h2_consumed_kg.

PLOTS
─────
plot_optimised_dispatch(df, day="YYYY-MM-DD") → 4-panel matplotlib figure:
  Panel 1 : H₂ Tank State of Charge [kg]
  Panel 2 : Power flows [MW]
  Panel 3 : Electricity price [€/MWh]
  Panel 4 : Cumulative revenue [k€]
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from scipy.optimize import linprog

from src.scenarios.config import ScenarioConfig


# ─────────────────────────────────────────────────────────────────────────────
# Variable layout
# ─────────────────────────────────────────────────────────────────────────────
# For a horizon of T timesteps, all decision variables are stacked in contiguous
# blocks of length T inside a single flat vector x of length 9×T.
#
#   Block 0  p_grid     power exported to grid               [MW]
#   Block 1  p_el       power consumed by electrolyser        [MW]
#   Block 2  p_fc       power produced by fuel cell           [MW]
#   Block 3  p_bc       battery charge power                  [MW]
#   Block 4  p_bd       battery discharge power               [MW]
#   Block 5  soc_h2     H₂ tank SoC (end-of-hour)            [kg]
#   Block 6  soc_batt   battery SoC (end-of-hour)            [MWh]
#   Block 7  curtail    curtailed wind power                  [MWh]
#   Block 8  h2_offtake H₂ withdrawn from tank (sold)        [kg]
# ─────────────────────────────────────────────────────────────────────────────

_VARS = [
    "p_grid", "p_el", "p_fc", "p_bc", "p_bd",
    "soc_h2", "soc_batt", "curtail", "h2_offtake",
]
_BLK = {v: i for i, v in enumerate(_VARS)}


def _s(var: str, T: int) -> slice:
    """Return the slice for variable block *var* in a length-9T vector."""
    b = _BLK[var]
    return slice(b * T, (b + 1) * T)


def _i(var: str, t: int, T: int) -> int:
    """Return the scalar index for variable *var* at timestep *t*."""
    return _BLK[var] * T + t


# ─────────────────────────────────────────────────────────────────────────────
# LP builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_lp(
    gen: np.ndarray,
    price: np.ndarray,
    cfg: ScenarioConfig,
    soc_h2_init: float,
    soc_batt_init: float,
    objective: str,
    battery_cycling_penalty: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list]:
    """
    Construct the LP in scipy linprog standard form for a T-step horizon.

    Decision variables
    ------------------
    See variable layout section above.  Total: 9 × T variables.

    Equality constraints  (A_eq @ x = b_eq)
    ----------------------------------------
    Rows  0 ..  T-1 : Power balance at each timestep
    Rows  T .. 2T-1 : H₂ tank state dynamics
    Rows 2T .. 3T-1 : Battery state dynamics

    Returns
    -------
    c      : objective coefficient vector (linprog minimises c @ x)
    A_eq   : equality constraint matrix  (3T × 9T)
    b_eq   : RHS for equality constraints (3T,)
    bounds : list of (lo, hi) pairs, one per variable
    """
    T = len(gen)

    # ── Physical conversion factors ─────────────────────────────────────
    el_rate = 1000.0 / cfg.electrolyser_efficiency_kwh_per_kg  # kg H₂ / MWh_elec (produced)
    fc_rate = 1000.0 / cfg.fuel_cell_efficiency_kwh_per_kg     # kg H₂ / MWh_elec (consumed)
    eta_c   = cfg.battery_efficiency ** 0.5   # √η : charge-leg efficiency
    eta_d   = cfg.battery_efficiency ** 0.5   # √η : discharge-leg efficiency
    h_offt  = cfg.h2_daily_offtake_kg / 24.0 # max H₂ offtake per hour [kg]

    # ── Objective vector c  (linprog minimises, so negate to maximise) ──
    c = np.zeros(9 * T)

    if objective == "revenue":
        # Maximise: Σ_t [ price[t]*(p_grid[t] + p_fc[t])
        #               + h2_price * h2_offtake[t]
        #               - λ * (p_bc[t] + p_bd[t]) ]
        c[_s("p_grid",     T)] = -price
        c[_s("p_fc",       T)] = -price
        c[_s("h2_offtake", T)] = -cfg.h2_selling_price_eur_per_kg
        c[_s("p_bc",       T)] = +battery_cycling_penalty
        c[_s("p_bd",       T)] = +battery_cycling_penalty

    elif objective == "h2":
        # Maximise: Σ_t el_rate * p_el[t]  (total H₂ produced [kg])
        # Penalise fuel-cell H₂ consumption (burns stored H₂).
        # Tiny grid bonus (1/1000 of price) to prefer grid over curtailment.
        c[_s("p_el",   T)] = -el_rate
        c[_s("p_fc",   T)] = +fc_rate
        c[_s("p_grid", T)] = -price * 1e-3   # tiebreaker: grid > curtail

    else:
        raise ValueError(f"objective must be 'revenue' or 'h2', got '{objective}'.")

    # ── Equality constraints ─────────────────────────────────────────────
    A_eq = np.zeros((3 * T, 9 * T))
    b_eq = np.zeros(3 * T)

    for t in range(T):

        # Power balance (row t):
        #   p_grid + p_el + p_bc + curtail = gen + p_fc + p_bd
        #   (left side: power sinks; right side: sources)
        r = t
        A_eq[r, _i("p_grid",  t, T)] = +1.0
        A_eq[r, _i("p_el",    t, T)] = +1.0
        A_eq[r, _i("p_bc",    t, T)] = +1.0
        A_eq[r, _i("curtail", t, T)] = +1.0
        A_eq[r, _i("p_fc",    t, T)] = -1.0
        A_eq[r, _i("p_bd",    t, T)] = -1.0
        b_eq[r] = gen[t]

        # H₂ tank dynamics (row T + t):
        #   soc_h2[t] = soc_h2[t-1] + el_rate*p_el[t]
        #             - fc_rate*p_fc[t] - h2_offtake[t]
        #   ⟹  soc_h2[t] - el_rate*p_el[t] + fc_rate*p_fc[t] + h2_offtake[t]
        #       = soc_h2[t-1]
        r = T + t
        A_eq[r, _i("soc_h2",    t, T)] = +1.0
        A_eq[r, _i("p_el",      t, T)] = -el_rate
        A_eq[r, _i("p_fc",      t, T)] = +fc_rate
        A_eq[r, _i("h2_offtake",t, T)] = +1.0
        if t == 0:
            b_eq[r] = soc_h2_init
        else:
            A_eq[r, _i("soc_h2", t - 1, T)] = -1.0
            b_eq[r] = 0.0

        # Battery dynamics (row 2T + t):
        #   soc_batt[t] = soc_batt[t-1] + η_c*p_bc[t] - (1/η_d)*p_bd[t]
        #   ⟹  soc_batt[t] - η_c*p_bc[t] + (1/η_d)*p_bd[t] = soc_batt[t-1]
        r = 2 * T + t
        A_eq[r, _i("soc_batt", t, T)] = +1.0
        A_eq[r, _i("p_bc",     t, T)] = -eta_c
        A_eq[r, _i("p_bd",     t, T)] = +1.0 / eta_d
        if t == 0:
            b_eq[r] = soc_batt_init
        else:
            A_eq[r, _i("soc_batt", t - 1, T)] = -1.0
            b_eq[r] = 0.0

    # ── Variable bounds ──────────────────────────────────────────────────
    # Default: all variables ≥ 0, no upper bound.
    bounds = [(0.0, None)] * (9 * T)

    for t in range(T):
        bounds[_i("p_el",      t, T)] = (0.0, cfg.electrolyser_capacity_mw)
        bounds[_i("p_fc",      t, T)] = (0.0, cfg.fuel_cell_capacity_mw)
        bounds[_i("p_bc",      t, T)] = (0.0, cfg.battery_power_mw)
        bounds[_i("p_bd",      t, T)] = (0.0, cfg.battery_power_mw)
        bounds[_i("soc_h2",    t, T)] = (0.0, cfg.tank_capacity_kg)
        bounds[_i("soc_batt",  t, T)] = (0.0, cfg.battery_capacity_mwh)
        bounds[_i("h2_offtake",t, T)] = (0.0, h_offt)
        # p_grid ≥ 0, curtail ≥ 0 — already the default

    return c, A_eq, b_eq, bounds


# ─────────────────────────────────────────────────────────────────────────────
# Solver abstraction  ← SWAP POINT for advanced solvers
# ─────────────────────────────────────────────────────────────────────────────

def _solve_lp(
    c: np.ndarray,
    A_eq: np.ndarray,
    b_eq: np.ndarray,
    bounds: list,
) -> np.ndarray:
    """
    Solve the LP and return the optimal variable vector x.

    Uses scipy HiGHS (open-source, interior-point + simplex).
    For a 24-h horizon (216 variables, 72 constraints) this takes < 5 ms.

    ┌─ SWAP POINT ────────────────────────────────────────────────────────┐
    │  To use a more powerful solver, replace this function.              │
    │  The arrays (c, A_eq, b_eq, bounds) are standard LP format.        │
    │                                                                     │
    │  Options:                                                           │
    │    PuLP + CBC/HiGHS  pip install pulp       (MILP capable)         │
    │    Gurobi            pip install gurobipy   (academic free licence) │
    │    OR-Tools          pip install ortools                            │
    │    Pyomo + GLPK      pip install pyomo                              │
    └─────────────────────────────────────────────────────────────────────┘
    """
    result = linprog(c, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
    if not result.success:
        raise RuntimeError(
            f"LP solver failed: {result.message}\n"
            "Check that tank capacity, offtake rate, and electrolyser size are "
            "mutually consistent (e.g. tank ≥ hourly_offtake * horizon_hours)."
        )
    return result.x


# ─────────────────────────────────────────────────────────────────────────────
# Main dispatch function
# ─────────────────────────────────────────────────────────────────────────────

def run_dispatch_optimised(
    df: pd.DataFrame,
    cfg: ScenarioConfig,
    horizon_hours: int = 24,
    step_hours: int | None = None,
    objective: str = "revenue",
    battery_cycling_penalty: float = 1.0,
) -> pd.DataFrame:
    """
    Run LP-optimised dispatch over the full timeseries in *df*.

    Parameters
    ----------
    df          : input timeseries with columns:
                  timestamp, gen_scaled_mwh, load_mwh, price_eur_per_mwh
    cfg         : ScenarioConfig (reads electrolyser, tank, battery, fuel-cell
                  and H₂ price from cfg)
    horizon_hours : length of each LP optimisation window [h].
                    24  = day-ahead (default).
                    168 = weekly lookahead.
    step_hours  : hours to advance after each solve.
                  None  → equal to horizon_hours (open-loop, day-ahead).
                  1     → MPC receding-horizon (re-optimise every hour).
    objective   : "revenue" — maximise grid + H₂ revenue minus cycling cost.
                  "h2"      — maximise total H₂ production volume.
    battery_cycling_penalty : extra cost [€/MWh] for each MWh of battery
                              throughput.  Prevents unrealistic cycling when
                              round-trip efficiency is close to 1.

    Returns
    -------
    pd.DataFrame  — one row per timestep.
    Columns match run_dispatch() exactly, plus:
        fc_power_mwh      : electricity generated by fuel cell [MWh]
        fc_h2_consumed_kg : H₂ consumed by fuel cell [kg]

    Notes
    -----
    Drop-in replacement for run_dispatch() in run_scenario.py.
    Enable fuel cell with cfg.fuel_cell_capacity_mw > 0.
    Battery disabled by default (cfg.battery_capacity_mwh = 0).
    """
    if step_hours is None:
        step_hours = horizon_hours

    df = df.reset_index(drop=True)
    n_steps = len(df)

    soc_h2   = float(cfg.tank_initial_soc_kg)
    soc_batt = float(cfg.battery_initial_soc_mwh)
    el_rate  = 1000.0 / cfg.electrolyser_efficiency_kwh_per_kg
    fc_rate  = 1000.0 / cfg.fuel_cell_efficiency_kwh_per_kg

    results: list[dict] = []

    start = 0
    while start < n_steps:
        end = min(start + horizon_hours, n_steps)
        T   = end - start

        window = df.iloc[start:end]
        gen    = window["gen_scaled_mwh"].to_numpy(dtype=float)
        price  = window["price_eur_per_mwh"].to_numpy(dtype=float)

        # Build and solve LP
        c, A_eq, b_eq, bounds = _build_lp(
            gen=gen, price=price, cfg=cfg,
            soc_h2_init=soc_h2, soc_batt_init=soc_batt,
            objective=objective,
            battery_cycling_penalty=battery_cycling_penalty,
        )
        x = _solve_lp(c, A_eq, b_eq, bounds)

        # Unpack solution blocks
        p_grid_v   = x[_s("p_grid",    T)]
        p_el_v     = x[_s("p_el",      T)]
        p_fc_v     = x[_s("p_fc",      T)]
        p_bc_v     = x[_s("p_bc",      T)]
        p_bd_v     = x[_s("p_bd",      T)]
        soc_h2_v   = x[_s("soc_h2",    T)]
        soc_batt_v = x[_s("soc_batt",  T)]
        curtail_v  = x[_s("curtail",   T)]
        offtake_v  = x[_s("h2_offtake",T)]

        # Record only the first `apply` hours (= step_hours, or remainder)
        apply = min(step_hours, T)
        for i in range(apply):
            row = window.iloc[i]
            results.append({
                "timestamp":               row["timestamp"],
                "action":                  _action_label(
                                               p_grid_v[i], p_el_v[i], p_fc_v[i],
                                               p_bc_v[i],   p_bd_v[i], curtail_v[i]
                                           ),
                "generation_mwh":          gen[i],
                "demand_mwh":              float(row["load_mwh"]),
                "price_eur_per_mwh":       price[i],
                "to_grid_mwh":             p_grid_v[i],
                "to_electrolyser_mwh":     p_el_v[i],
                "h2_produced_kg":          p_el_v[i] * el_rate,
                "tank_soc_kg":             soc_h2_v[i],
                "energy_flux_battery_kwh": (p_bc_v[i] - p_bd_v[i]) * 1000.0,
                "curtailed_mwh":           curtail_v[i],
                "battery_soc_mwh":         soc_batt_v[i],
                "h2_offtake_kg":           offtake_v[i],
                "fc_power_mwh":            p_fc_v[i],
                "fc_h2_consumed_kg":       p_fc_v[i] * fc_rate,
            })

        # Carry state forward from the last applied step
        soc_h2   = float(soc_h2_v[apply - 1])
        soc_batt = float(soc_batt_v[apply - 1])
        start   += apply

    return pd.DataFrame(results)


def _action_label(
    p_grid: float, p_el: float, p_fc: float,
    p_bc: float,   p_bd: float, curtail: float,
    tol: float = 1e-3,
) -> str:
    parts = []
    if p_grid  > tol: parts.append("grid")
    if p_el    > tol: parts.append("electrolyse")
    if p_fc    > tol: parts.append("fuel_cell")
    if p_bc    > tol: parts.append("batt_charge")
    if p_bd    > tol: parts.append("batt_discharge")
    if curtail > tol: parts.append("curtail")
    return " + ".join(parts) if parts else "idle"


# ─────────────────────────────────────────────────────────────────────────────
# 4-panel visualisation  (BESS scheduling demo style)
# ─────────────────────────────────────────────────────────────────────────────

def plot_optimised_dispatch(
    df: pd.DataFrame,
    day: str | None = None,
    title: str | None = None,
    h2_price_eur_per_kg: float = 5.0,
    figsize: tuple[float, float] = (12, 10),
    tank_capacity_kg: float | None = None,
) -> plt.Figure:
    """
    4-panel optimisation results figure.

    Panels (top → bottom):
        1. H₂ Tank State of Charge [kg]
        2. Power flows: wind gen, grid export, electrolyser, fuel cell, curtailment
        3. Electricity price [€/MWh] with mean dashed line
        4. Cumulative revenue [k€]

    Parameters
    ----------
    df                  : output of run_dispatch_optimised() or run_dispatch()
    day                 : "YYYY-MM-DD" to plot a single day.
                          None → use first 24 rows.
    title               : figure suptitle override
    h2_price_eur_per_kg : used to compute revenue when economics.py has not
                          been run (i.e. grid_revenue_eur column absent)
    figsize             : figure size in inches
    """
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    if day is not None:
        mask = df["timestamp"].dt.date == pd.Timestamp(day).date()
        pf = df[mask].reset_index(drop=True)
        if pf.empty:
            raise ValueError(f"No rows found for day='{day}'.")
    else:
        pf = df.iloc[:24].reset_index(drop=True)

    n = len(pf)
    hours = np.arange(n)

    # Cumulative revenue: use pre-computed columns if available
    if "grid_revenue_eur" in pf.columns:
        cum_rev = (pf["grid_revenue_eur"] + pf["h2_revenue_eur"]).cumsum() / 1000.0
    else:
        cum_rev = (
            pf["to_grid_mwh"] * pf["price_eur_per_mwh"]
            + pf["h2_offtake_kg"] * h2_price_eur_per_kg
        ).cumsum() / 1000.0

    # ── Style constants (dark theme matching BESS demo) ─────────────────
    BG   = "#0d0d1a"
    LINE = "#c8e64c"   # yellow-green
    GRID = "#2a2a3d"
    TEXT = "#cccccc"
    BLUE = "#5599ff"
    ORNG = "#ff7733"
    PINK = "#ff44aa"
    RED  = "#ff3333"

    fig = plt.figure(figsize=figsize, facecolor=BG)
    gs  = gridspec.GridSpec(4, 1, figure=fig, hspace=0.55)
    axs = [fig.add_subplot(gs[i]) for i in range(4)]

    for ax in axs:
        ax.set_facecolor(BG)
        ax.tick_params(colors=TEXT, labelsize=9)
        ax.yaxis.label.set_color(TEXT)
        ax.xaxis.label.set_color(TEXT)
        ax.title.set_color(TEXT)
        for sp in ax.spines.values():
            sp.set_edgecolor(GRID)
        ax.grid(True, color=GRID, linewidth=0.6, zorder=0)

    # ── Panel 1 — H₂ Tank SoC ───────────────────────────────────────────
    ax = axs[0]
    ax.plot(hours, pf["tank_soc_kg"], color=LINE, linewidth=2.0, zorder=3)
    ax.fill_between(hours, pf["tank_soc_kg"], alpha=0.15, color=LINE)
    ax.set_title("H₂ Tank State of Charge")
    ax.set_ylabel("SoC (kg)")
    ax.set_xlim(0, n - 1)

    # Right y-axis: % of tank capacity
    if tank_capacity_kg is not None and tank_capacity_kg > 0:
        ax2 = ax.twinx()
        ax2.set_ylim(ax.get_ylim()[0] / tank_capacity_kg * 100,
                     ax.get_ylim()[1] / tank_capacity_kg * 100)
        ax2.set_ylabel("SoC (%)", color=TEXT)
        ax2.tick_params(colors=TEXT, labelsize=9)
        ax2.yaxis.label.set_color(TEXT)
        for sp in ax2.spines.values():
            sp.set_edgecolor(GRID)

    # ── Panel 2 — Power flows ────────────────────────────────────────────
    ax = axs[1]
    ax.fill_between(hours, pf["generation_mwh"], alpha=0.15, color=BLUE,
                    label="Wind gen", zorder=1)
    ax.plot(hours, pf["to_grid_mwh"],         color=LINE, lw=1.8,
            label="Grid export", zorder=3)
    ax.plot(hours, pf["to_electrolyser_mwh"], color=ORNG, lw=1.8,
            label="Electrolyser",  zorder=3)
    if "fc_power_mwh" in pf.columns and pf["fc_power_mwh"].max() > 1e-3:
        ax.plot(hours, pf["fc_power_mwh"], color=PINK, lw=1.5,
                label="Fuel cell", zorder=3)
    # Battery charge/discharge bars
    flux = pf.get("energy_flux_battery_kwh", pd.Series(0.0, index=pf.index)) / 1000.0
    discharge = (-flux).clip(lower=0)
    charge    = flux.clip(lower=0)
    if discharge.max() > 1e-3:
        ax.bar(hours, discharge, width=0.8, color=LINE, alpha=0.55,
               label="Batt discharge", zorder=2)
    if charge.max() > 1e-3:
        ax.bar(hours, -charge, width=0.8, color=RED, alpha=0.55,
               label="Batt charge", zorder=2)
    if pf["curtailed_mwh"].max() > 0.01:
        ax.fill_between(hours, -pf["curtailed_mwh"], alpha=0.3, color=RED,
                        label="Curtailed", zorder=1)
    ax.axhline(0, color=GRID, linewidth=0.8)
    ax.set_title("Power Flows")
    ax.set_ylabel("Power (MW)")
    ax.legend(loc="upper right", fontsize=7, facecolor=BG, labelcolor=TEXT,
              framealpha=0.7)
    ax.set_xlim(0, n - 1)

    # ── Panel 3 — Electricity price ──────────────────────────────────────
    ax = axs[2]
    ax.plot(hours, pf["price_eur_per_mwh"], color=LINE, linewidth=1.8)
    mean_p = pf["price_eur_per_mwh"].mean()
    ax.axhline(mean_p, color="#888888", linestyle="--", linewidth=1.0,
               label=f"Mean: {mean_p:.1f} €/MWh")
    ax.axhline(0, color=GRID, linewidth=0.6)
    ax.set_title("Electricity Price")
    ax.set_ylabel("Price (€/MWh)")
    ax.legend(loc="upper right", fontsize=7, facecolor=BG, labelcolor=TEXT,
              framealpha=0.7)
    ax.set_xlim(0, n - 1)

    # ── Panel 4 — Cumulative revenue ─────────────────────────────────────
    ax = axs[3]
    ax.plot(hours, cum_rev, color=LINE, linewidth=2.0)
    ax.fill_between(hours, cum_rev, alpha=0.15, color=LINE)
    ax.set_title("Cumulative Revenue")
    ax.set_ylabel("Revenue (k€)")
    ax.set_xlabel("Time (hours)")
    ax.set_xlim(0, n - 1)

    # ── Suptitle ─────────────────────────────────────────────────────────
    if title is None:
        date_str = pf["timestamp"].dt.date.iloc[0].isoformat() if n > 0 else ""
        title = f"LP-Optimised Dispatch  ·  {date_str}"
    fig.suptitle(title, color=TEXT, fontsize=13, y=0.995)

    plt.tight_layout(rect=[0, 0, 1, 0.975])
    return fig

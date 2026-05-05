"""
BESS runner — loads data, runs 25-year dispatch with daily threshold optimisation,
prints key results.

Usage (from repo root):
    python "2.5. cisco's model/BESS/run_bess.py"

Edit PARAMS below to change configuration.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_MODEL_ROOT = Path(__file__).resolve().parent.parent
if str(_MODEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_MODEL_ROOT))

from common.loaders import build_simulation_df
from BESS.config import BESSConfig
from BESS.dispatch import simulate_bess
from BESS.economics import calc_npv_incremental, calc_lcos, annual_cashflows

# ── Import base case from HESS module ─────────────────────────────────────
from HESS.config import HESSConfig as _HCfg
from HESS.dispatch import simulate_base_case

# ── User-editable parameters ──────────────────────────────────────────────
AUTONOMY_H = 2.0      # [h] — 2 or 4
RATED_POWER_MW = 100.0
BASE_YEARS = [2023, 2024]
N_GRID = 10           # grid resolution for daily threshold optimisation
# ─────────────────────────────────────────────────────────────────────────


def main() -> None:
    print("=" * 60)
    print("  BESS — Battery Energy Storage System")
    print("  WindFloat Atlantic 1 GW expansion, Portugal")
    print("=" * 60)

    # ── 1. Load data ───────────────────────────────────────────────────
    print(f"\nLoading data for years {BASE_YEARS} …")
    t0 = time.time()
    df = build_simulation_df(years=BASE_YEARS, n_project_years=25, farm_capacity_mw=1000.0)
    wind_mw = df["wind_mw"].values
    prices = df["price"].values
    print(f"  Loaded {len(df):,} hourly timesteps ({time.time()-t0:.1f} s)")

    # ── 2. Configure BESS ─────────────────────────────────────────────
    cfg = BESSConfig(rated_power_mw=RATED_POWER_MW, autonomy_h=AUTONOMY_H)
    print(f"\nBESS Configuration:")
    print(f"  Rated power     : {cfg.rated_power_mw:.0f} MW")
    print(f"  Autonomy        : {cfg.autonomy_h:.0f} h → {cfg.cap_lib_mwh:.0f} MWh")
    print(f"  CAPEX total     : {cfg.capex_total_eur/1e6:.1f} M€")
    print(f"    Battery DC    : {cfg.capex_battery_eur/1e6:.1f} M€")
    print(f"    Inverter AC   : {cfg.capex_inverter_eur/1e6:.1f} M€")
    print(f"    BoP           : {cfg.capex_bop_eur/1e6:.1f} M€")
    print(f"  Annual O&M      : {cfg.annual_om_eur()/1e6:.2f} M€/yr")
    print(f"  Replacement yr  : {cfg.lifetime_years}  ({cfg.replacement_cost_eur()/1e6:.1f} M€)")

    # ── 3. Run simulation (with daily optimisation) ───────────────────
    print(f"\nRunning 25-year BESS dispatch (daily threshold optimisation, n_grid={N_GRID}) …")
    print("  (This may take a few minutes)")
    t1 = time.time()
    bess_res = simulate_bess(wind_mw, prices, cfg, n_grid=N_GRID)
    print(f"  Done in {time.time()-t1:.1f} s")

    # ── 4. Base case ──────────────────────────────────────────────────
    h_cfg = _HCfg(farm_capacity_mw=1000.0)
    base_res = simulate_base_case(wind_mw, prices, h_cfg)

    # Also compute base grid revenue for BESS economics
    # (re-use the HESS base_case output)
    base_r_grid = base_res["r_grid_eur"]
    base_opex = base_res["opex_wfa_eur"]
    # Attach to bess_res for economics module compatibility
    bess_res["_base_r_grid_eur"] = base_r_grid
    bess_res["_base_opex_wfa_eur"] = base_opex

    # ── 5. Economic results ───────────────────────────────────────────
    npv = calc_npv_incremental(bess_res, base_res, cfg)
    lcos = calc_lcos(bess_res, cfg)
    cfs = annual_cashflows(bess_res, base_res, cfg)

    print(f"\n{'─'*50}")
    print(f"  NPV   = {npv/1e6:+.1f} M€")
    print(f"  LCOS  = {lcos:.2f} €/MWh")
    print(f"{'─'*50}")

    # ── 6. Operational results ────────────────────────────────────────
    n_h = cfg.project_life_years * 8760
    total_grid_bess_twh = bess_res["p_grid_mw"][:n_h].sum() / 1e6
    total_curtailed_twh = bess_res["p_curtailed_mw"][:n_h].sum() / 1e6
    total_discharged_mwh = bess_res["p_bess_out_ac_mw"][:n_h].sum()

    grid_base_twh = base_res["p_grid_mw"][:n_h].sum() / 1e6
    curtailed_base_twh = base_res["p_curtailed_mw"][:n_h].sum() / 1e6

    print(f"\nOperational summary (25 years):")
    print(f"  [Base case] Grid: {grid_base_twh:.2f} TWh  Curtailment: {curtailed_base_twh:.2f} TWh")
    print(f"  [BESS]      Grid: {total_grid_bess_twh:.2f} TWh  Curtailment: {total_curtailed_twh:.2f} TWh")
    print(f"  Battery discharged : {total_discharged_mwh/1e6:.2f} TWh")
    print(f"  Avg SOC            : {bess_res['soc'][:n_h].mean()*100:.1f} %")

    actions = bess_res["actions"][:n_h]
    for label in ("ChargeLIB+Grid", "ChargeLIB", "DischargeLIB+Grid", "Grid", "Curtailment"):
        pct = 100.0 * np.sum(actions == label) / n_h
        if pct > 0.1:
            print(f"  Action '{label}': {pct:.1f}%")

    # ── 7. Save results ───────────────────────────────────────────────
    out_dir = _MODEL_ROOT / "BESS" / "outputs"
    out_dir.mkdir(exist_ok=True)

    cf_df = pd.DataFrame(cfs)
    cf_df.index = pd.RangeIndex(stop=len(cf_df), name="year")
    cf_path = out_dir / f"bess_annual_cashflows_{cfg.autonomy_h:.0f}h.csv"
    cf_df.to_csv(cf_path)
    print(f"\nAnnual cash flows saved → {cf_path.relative_to(_MODEL_ROOT)}")

    hourly_df = pd.DataFrame({
        "wind_mw": wind_mw[:2 * 8760],
        "price": prices[:2 * 8760],
        "p_grid_mw": bess_res["p_grid_mw"][:2 * 8760],
        "soc_pct": bess_res["soc"][:2 * 8760] * 100,
        "action": bess_res["actions"][:2 * 8760],
    })
    hourly_path = out_dir / "bess_hourly_yr1_2.csv"
    hourly_df.to_csv(hourly_path, index=False)
    print(f"First 2-yr hourly data saved → {hourly_path.relative_to(_MODEL_ROOT)}")


if __name__ == "__main__":
    main()

"""
HESS runner — loads data, optionally optimises p_storage, runs 25-yr simulation,
prints key results.

Usage (from repo root):
    python "2.5. cisco's model/HESS/run_hess.py"

Optional flags (edit PARAMS below or override via config):
    OPTIMISE    = True   → grid-search for best p_storage (takes ~1-2 min)
    P_STORAGE   = 144.23 → fixed threshold if OPTIMISE=False (thesis default)
    P_H2        = 8.0    → H2 selling price [€/kg]
    VT_HOURS    = 264    → tank volume in full-load hours
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

# Add model root to path so 'common' and 'HESS' are importable
_MODEL_ROOT = Path(__file__).resolve().parent.parent
if str(_MODEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_MODEL_ROOT))

from common.loaders import build_simulation_df
from HESS.config import HESSConfig
from HESS.dispatch import simulate_hess, simulate_base_case, optimise_p_storage
from HESS.economics import calc_npv_incremental, calc_lcoh, annual_cashflows

# ── User-editable parameters ──────────────────────────────────────────────
OPTIMISE = True       # True = grid-search for best p_storage
P_STORAGE = 144.23    # [€/MWh] used only if OPTIMISE=False
P_H2 = 8.0           # [€/kg]
VT_HOURS = 264.0      # tank volume [full-load hours]
BASE_YEARS = [2023, 2024]
# ─────────────────────────────────────────────────────────────────────────


def main() -> None:
    print("=" * 60)
    print("  HESS — Hydrogen Energy Storage System")
    print("  WindFloat Atlantic 1 GW expansion, Portugal")
    print("=" * 60)

    # ── 1. Load data ───────────────────────────────────────────────────
    print(f"\nLoading data for years {BASE_YEARS} …")
    t0 = time.time()
    df = build_simulation_df(years=BASE_YEARS, n_project_years=25, farm_capacity_mw=1000.0)
    wind_mw = df["wind_mw"].values
    prices = df["price"].values
    print(f"  Loaded {len(df):,} hourly timesteps ({time.time()-t0:.1f} s)")
    print(f"  Wind:  mean {np.nanmean(wind_mw):.1f} MW, max {np.nanmax(wind_mw):.1f} MW")
    print(f"  Price: mean {np.nanmean(prices):.2f} €/MWh, max {np.nanmax(prices):.1f} €/MWh")

    # ── 2. Configure HESS ─────────────────────────────────────────────
    cfg = HESSConfig(
        vt_hours=VT_HOURS,
        p_h2_eur_per_kg=P_H2,
        p_storage=P_STORAGE,
    )
    print(f"\nHESS Configuration:")
    print(f"  EL capacity       : {cfg.p_el_mw:.0f} MW (PPR={cfg.p_el_mw/cfg.farm_capacity_mw*100:.0f}%)")
    print(f"  Tank VT           : {cfg.vt_hours:.0f} h → {cfg.cap_h2_tanks_kg/1000:.0f} t H2")
    print(f"  H2 selling price  : {cfg.p_h2_eur_per_kg} €/kg")
    print(f"  CAPEX total       : {cfg.capex_total_eur/1e6:.1f} M€")
    print(f"    EL              : {cfg.capex_el_eur/1e6:.1f} M€")
    print(f"    Compressor      : {cfg.capex_comp_eur/1e6:.2f} M€")
    print(f"    Tanks           : {cfg.capex_tanks_eur/1e6:.1f} M€")
    print(f"    EPC             : {cfg.capex_epc_eur/1e6:.1f} M€")
    print(f"  Annual fixed OPEX : {cfg.annual_opex_eur()/1e6:.1f} M€/yr")

    # ── 3. Optimise p_storage ─────────────────────────────────────────
    if OPTIMISE:
        print(f"\nOptimising p_storage (grid search over price percentiles) …")
        t1 = time.time()
        best_ps, best_npv = optimise_p_storage(wind_mw, prices, cfg)
        cfg.p_storage = best_ps
        print(f"  Best p_storage = {best_ps:.2f} €/MWh  →  NPV = {best_npv/1e6:.1f} M€  ({time.time()-t1:.1f} s)")
    else:
        print(f"\nUsing fixed p_storage = {cfg.p_storage:.2f} €/MWh")

    # ── 4. Run full simulation ────────────────────────────────────────
    print("\nRunning 25-year HESS dispatch …")
    t2 = time.time()
    hess_res = simulate_hess(wind_mw, prices, cfg)
    base_res = simulate_base_case(wind_mw, prices, cfg)
    print(f"  Done in {time.time()-t2:.1f} s")

    # ── 5. Economic results ───────────────────────────────────────────
    npv = calc_npv_incremental(hess_res, base_res, cfg)
    lcoh = calc_lcoh(hess_res, cfg)
    cfs = annual_cashflows(hess_res, base_res, cfg)

    print(f"\n{'─'*50}")
    print(f"  NPV   = {npv/1e6:+.1f} M€")
    print(f"  LCOH  = {lcoh:.2f} €/kg")
    print(f"{'─'*50}")

    # ── 6. Operational results ────────────────────────────────────────
    n_years = cfg.project_life_years
    hours_per_year = 8760
    n_h = n_years * hours_per_year

    total_wind_mwh = wind_mw[:n_h].sum() / 1e6              # TWh
    total_grid_mwh = hess_res["p_grid_mw"][:n_h].sum() / 1e6
    total_curtailed_mwh = hess_res["p_curtailed_mw"][:n_h].sum() / 1e6
    total_h2_twh = hess_res["m_h2_produced_kg"][:n_h].sum() * cfg.e_pem_kwh_per_kg / 1e9
    total_h2_released_twh = hess_res["m_h2_released_kg"][:n_h].sum() * cfg.e_pem_kwh_per_kg / 1e9

    grid_base_mwh = base_res["p_grid_mw"][:n_h].sum() / 1e6
    curtailed_base_mwh = base_res["p_curtailed_mw"][:n_h].sum() / 1e6

    print(f"\nOperational summary (25 years):")
    print(f"  Total wind output      : {total_wind_mwh*(1-cfg.tx_loss):.2f} TWh (onshore)")
    print(f"  [Base case]  Grid      : {grid_base_mwh:.2f} TWh   Curtailment: {curtailed_base_mwh:.2f} TWh")
    print(f"  [HESS]       Grid      : {total_grid_mwh:.2f} TWh   Curtailment: {total_curtailed_mwh:.2f} TWh")
    print(f"               H2 gas grid: {total_h2_released_twh:.2f} TWh-equiv")

    # Action distribution
    actions = hess_res["actions"][:n_h]
    for label in ("H2+Grid", "H2", "Grid", "Curtailment"):
        pct = 100.0 * np.sum(actions == label) / n_h
        print(f"  Action '{label}': {pct:.1f}%")

    # ── 7. Save results ───────────────────────────────────────────────
    out_dir = _MODEL_ROOT / "HESS" / "outputs"
    out_dir.mkdir(exist_ok=True)

    # Annual cash flows
    cf_df = pd.DataFrame(cfs)
    cf_df.index = pd.RangeIndex(stop=len(cf_df), name="year")
    cf_path = out_dir / f"hess_annual_cashflows_VT{VT_HOURS:.0f}h_pH2{P_H2}.csv"
    cf_df.to_csv(cf_path)
    print(f"\nAnnual cash flows saved → {cf_path.relative_to(_MODEL_ROOT)}")

    # First 2 years hourly (for SOC / price plots)
    hourly_df = pd.DataFrame({
        "wind_mw": wind_mw[:2 * 8760],
        "price": prices[:2 * 8760],
        "p_grid_mw": hess_res["p_grid_mw"][:2 * 8760],
        "soc_h2_pct": hess_res["soc_h2"][:2 * 8760] * 100,
        "m_h2_tank_kg": hess_res["m_h2_tank_kg"][:2 * 8760],
        "action": hess_res["actions"][:2 * 8760],
    })
    hourly_path = out_dir / "hess_hourly_yr1_2.csv"
    hourly_df.to_csv(hourly_path, index=False)
    print(f"First 2-yr hourly data saved → {hourly_path.relative_to(_MODEL_ROOT)}")


if __name__ == "__main__":
    main()

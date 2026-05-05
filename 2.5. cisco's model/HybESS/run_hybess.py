"""
HybESS runner — runs both basic and enhanced strategies, compares with thesis
reference results (Table 7.1):
  Basic    NPV ≈ -104.4 M€
  Enhanced NPV ≈  +4.69 M€, LCOH ≈ 4.60 €/kg

Usage (from repo root):
    python "2.5. cisco's model/HybESS/run_hybess.py"
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
from HybESS.config import HybESSConfig
from HybESS.dispatch import simulate_hybess
from HybESS.economics import calc_npv_incremental, calc_lcoh, calc_lcos, annual_cashflows
from HESS.config import HESSConfig as _HCfg
from HESS.dispatch import simulate_base_case

# ── User-editable parameters ──────────────────────────────────────────────
BASE_YEARS = [2023, 2024]
VT_HOURS = 216.0      # Tank volume [h] — thesis uses 216 for HybESS
P_H2 = 8.0            # H2 sale price [€/kg]
N_GRID = 10           # Daily threshold optimisation grid resolution
# ─────────────────────────────────────────────────────────────────────────


def run_strategy(
    wind_mw: np.ndarray,
    prices: np.ndarray,
    cfg: HybESSConfig,
    base_res: dict,
    label: str,
) -> None:
    print(f"\n{'='*60}")
    print(f"  Strategy: {label}")
    print(f"{'='*60}")
    t0 = time.time()
    res = simulate_hybess(wind_mw, prices, cfg, n_grid=N_GRID)
    print(f"  Simulation done in {time.time()-t0:.1f} s")

    npv = calc_npv_incremental(res, base_res, cfg)
    lcoh = calc_lcoh(res, cfg)
    lcos = calc_lcos(res, cfg)

    print(f"\n  NPV    = {npv/1e6:+.2f} M€")
    print(f"  LCOH   = {lcoh:.2f} €/kg")
    print(f"  LCOS   = {lcos:.2f} €/MWh")

    n = cfg.project_life_years
    n_h = n * 8760
    total_h2_t = res["m_h2_released_kg"][:n_h].sum() / 1_000.0
    total_grid_twh = res["p_grid_mw"][:n_h].sum() / 1e6
    total_curtailed_twh = res["p_curtailed_mw"][:n_h].sum() / 1e6
    bess_discharged_twh = res["p_bess_out_mw"][:n_h].sum() / 1e6
    el_h_total = res["el_running_h"][:n_h].sum()

    print(f"\n  H2 delivered  : {total_h2_t:.0f} t  ({total_h2_t/1000:.1f} kt)")
    print(f"  Grid output   : {total_grid_twh:.2f} TWh")
    print(f"  Curtailed     : {total_curtailed_twh:.2f} TWh")
    print(f"  BESS discharged: {bess_discharged_twh:.2f} TWh")
    print(f"  EL running    : {el_h_total:.0f} h  ({el_h_total/n_h*100:.1f}%)")

    # Action distribution
    actions = res["actions"][:n_h]
    unique, counts = np.unique(actions, return_counts=True)
    print(f"\n  Action distribution:")
    for u, c in sorted(zip(unique, counts), key=lambda x: -x[1]):
        print(f"    {u:<35s}: {c/n_h*100:.1f}%")

    # Save outputs
    out_dir = _MODEL_ROOT / "HybESS" / "outputs"
    out_dir.mkdir(exist_ok=True)

    cfs = annual_cashflows(res, base_res, cfg)
    cf_df = pd.DataFrame(cfs)
    cf_path = out_dir / f"hybess_cashflows_{label.lower().replace(' ', '_')}.csv"
    cf_df.to_csv(cf_path)
    print(f"\n  Cashflows saved → {cf_path.relative_to(_MODEL_ROOT)}")

    return res


def main() -> None:
    print("=" * 60)
    print("  HybESS — Hybrid Battery+Hydrogen Energy Storage")
    print("  WindFloat Atlantic 1 GW expansion, Portugal")
    print("=" * 60)

    # ── Load data ──────────────────────────────────────────────────────
    print(f"\nLoading data for years {BASE_YEARS} …")
    df = build_simulation_df(years=BASE_YEARS, n_project_years=25, farm_capacity_mw=1000.0)
    wind_mw = df["wind_mw"].values
    prices = df["price"].values
    print(f"  {len(df):,} hourly timesteps loaded")

    # ── Base case ──────────────────────────────────────────────────────
    h_cfg = _HCfg(farm_capacity_mw=1000.0)
    base_res = simulate_base_case(wind_mw, prices, h_cfg)

    # ── Print CAPEX breakdown ──────────────────────────────────────────
    cfg_basic = HybESSConfig(vt_hours=VT_HOURS, p_h2_eur_per_kg=P_H2, enhanced=False)
    print(f"\nHybESS Configuration (VT={VT_HOURS:.0f} h):")
    print(f"  EL CAPEX      : {cfg_basic.capex_el_eur/1e6:.1f} M€")
    print(f"  Comp CAPEX    : {cfg_basic.capex_comp_eur/1e6:.1f} M€")
    print(f"  Tank CAPEX    : {cfg_basic.capex_tanks_eur/1e6:.1f} M€")
    print(f"  BESS CAPEX    : {(cfg_basic.capex_bess_battery_eur+cfg_basic.capex_bess_inverter_eur+cfg_basic.capex_bess_bop_eur)/1e6:.1f} M€")
    print(f"  EPC           : {cfg_basic.capex_epc_eur/1e6:.1f} M€")
    print(f"  TOTAL CAPEX   : {cfg_basic.capex_total_eur/1e6:.1f} M€")
    print(f"  Annual HESS OPEX: {cfg_basic.annual_opex_hess_eur()/1e6:.2f} M€/yr")
    print(f"  Annual BESS O&M : {cfg_basic.annual_bess_om_eur()/1e6:.2f} M€/yr")

    # ── Basic strategy ────────────────────────────────────────────────
    run_strategy(wind_mw, prices, cfg_basic, base_res, "Basic")

    # ── Enhanced strategy ─────────────────────────────────────────────
    cfg_enhanced = HybESSConfig(vt_hours=VT_HOURS, p_h2_eur_per_kg=P_H2, enhanced=True)
    run_strategy(wind_mw, prices, cfg_enhanced, base_res, "Enhanced")

    print(f"\n{'='*60}")
    print("  Reference (thesis Table 7.1):")
    print("    Basic    NPV ≈ -104.4 M€")
    print("    Enhanced NPV ≈   +4.69 M€, LCOH ≈ 4.60 €/kg")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

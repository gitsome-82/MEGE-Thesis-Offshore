"""
config.py — Default scenario parameters and system constants.

All values are defaults that can be overridden when calling run_scenario().
"""
from dataclasses import dataclass, field
import pathlib

# ── Paths ──────────────────────────────────────────────────────────────────
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent   # "3.2 system model v2/"
DATA_DIR = PROJECT_ROOT.parent.parent / "DATA" / "Germany Data"
PT_DATA_DIR = PROJECT_ROOT.parent.parent / "DATA" / "Portugal Data"
OUTPUT_DIR = PROJECT_ROOT / "outputs"

# ── Scenario defaults (dataclass so they're easy to override) ─────────────
@dataclass
class ScenarioConfig:
    # --- Wind farm ---
    alpha_ventus_capacity_mw: float = 60.0          # 12 × 5 MW Adwen AD 5-116
    target_farm_capacity_mw: float = 500.0           # hypothetical scaled-up farm
    derate_factor: float = 1.0                        # 1.0 = no derating; 0.9 = 10% availability loss
    smoothing_window: int = 1                         # 1 = no smoothing (hours)

    # --- Turbine power curve (used when use_power_curve=True) ---
    # Defaults represent a modern large offshore turbine
    # (e.g. Vestas V236-15 MW / SGRE SG 14-222 DD class, ~2025 technology)
    # Swap in real supplier specs when available — just change these four numbers.
    use_power_curve: bool = False              # True  = wind speed CSV → power curve → gen
                                               # False = national generation data → scale (default)
    turbine_rated_speed_ms: float = 11.0      # wind speed at rated power [m/s]
    turbine_cut_in_ms: float = 3.0            # cut-in wind speed [m/s]
    turbine_cut_out_ms: float = 25.0          # cut-out wind speed [m/s] (storm protection)
    turbine_hub_height_m: float = 120.0       # hub height [m] — used for wind shear correction
    wind_data_height_m: float = 100.0         # height of wind speed measurement in CSV [m]
                                               # ERA5 actual data = 100 m; ECMWF forecast = 120 m
    z0_roughness_m: float = 0.0002            # surface roughness length z₀ [m] for log-law
                                               # !! REPLACE WITH ACTUAL z₀ FOR YOUR SITE !!
                                               # Alpha Ventus (North Sea, open sea): 0.0001–0.0002 m
                                               # WindFloat Atlantic (Atlantic coast): 0.0002–0.0005 m
                                               # Near-shore / coastal sites:          0.001–0.01   m
                                               # 0.0002 m is a safe generic offshore starting point.

    # --- Electrolyser (PEM reference) ---
    electrolyser_capacity_mw: float = 100.0           # max electrical input [MW]
    electrolyser_efficiency_kwh_per_kg: float = 55.0  # specific energy consumption [kWh / kg H2]
    electrolyser_min_load_frac: float = 0.10          # min partial load (fraction of capacity)

    # --- Hydrogen tank ---
    tank_capacity_kg: float = 10_000.0                # max stored H2 [kg]
    tank_initial_soc_kg: float = 0.0                  # starting state of charge [kg]
    h2_daily_offtake_kg: float = 2_000.0              # kg H2 withdrawn from tank per day
                                                      # DISCHARGE RULE: fixed daily offtake
                                                      # representing a steady industrial buyer
                                                      # (refinery, ammonia plant, transport depot)
                                                      # connected via pipeline.  Applied hourly
                                                      # as offtake/24 each timestep.

    # --- Battery (placeholder for later) ---
    battery_capacity_mwh: float = 0.0                 # 0 = no battery
    battery_power_mw: float = 0.0
    battery_efficiency: float = 0.90                  # round-trip
    battery_initial_soc_mwh: float = 0.0

    # --- Economics ---
    h2_selling_price_eur_per_kg: float = 5.0          # green-H2 offtake price
    discount_rate: float = 0.08                       # for NPV
    project_lifetime_years: int = 25
    opex_eur_per_mwh: float = 23.0                    # operating cost [EUR/MWh generated]
                                                      # ~23 EUR/MWh is a typical offshore wind
                                                      # O&M estimate (maintenance, staff, insurance).
                                                      # Used as the curtailment floor: if spot price
                                                      # is below this, selling to grid loses money.

    # --- Data source ---
    country: str = "Germany"                          # "Germany" or "Portugal"
    data_source: str = "SMARD"                        # "SMARD" or "Frauenhofer" (Germany); "ENTSO-E" (Portugal)
    year: int = 2023

    # --- Fuel cell (PEM, converts stored H₂ back to electricity) ---
    fuel_cell_capacity_mw: float = 0.0               # max electrical output [MW]; 0 = disabled
    fuel_cell_efficiency_kwh_per_kg: float = 16.7    # kWh_elec per kg H₂ consumed (~50 % LHV)

    # --- Curtailment / dispatch rules ---
    curtailment_price_threshold_eur: float | None = None  # curtail when price <= this
                                                          # None = use opex_eur_per_mwh as floor
                                                          # (i.e. don't sell at a loss)
    prioritise_h2: bool = True                        # True = excess goes to electrolyser before grid

    # --- Optimised dispatch (dispatch_optimised.py) ---
    use_optimised_dispatch: bool = False              # True = use LP optimiser instead of rule-based
    dispatch_objective: str = "revenue"              # "revenue" (max profit) or "h2" (max H₂ volume)
    dispatch_horizon_hours: int = 24                  # LP window [h]; 168 = weekly lookahead
    dispatch_step_hours: int | None = None            # hours to advance per solve; None = horizon (no overlap)
    battery_cycling_penalty: float = 1.0             # extra cost [€/MWh] per MWh battery throughput

"""
config.py — Default scenario parameters and system constants.

All values are defaults that can be overridden when calling run_scenario().
"""
from dataclasses import dataclass, field
import pathlib

# ── Paths ──────────────────────────────────────────────────────────────────
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent   # "3. system model/"
DATA_DIR = PROJECT_ROOT.parent / "DATA" / "Germany Data"
OUTPUT_DIR = PROJECT_ROOT / "outputs"


# ── Scenario defaults (dataclass so they're easy to override) ─────────────
@dataclass
class ScenarioConfig:
    # --- Wind farm ---
    alpha_ventus_capacity_mw: float = 60.0          # 12 × 5 MW Adwen AD 5-116
    target_farm_capacity_mw: float = 500.0           # hypothetical scaled-up farm
    derate_factor: float = 1.0                        # 1.0 = no derating; 0.9 = 10% availability loss
    smoothing_window: int = 1                         # 1 = no smoothing (hours)

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
    data_source: str = "SMARD"                        # "SMARD" or "Frauenhofer"
    year: int = 2023

    # --- Curtailment / dispatch rules ---
    curtailment_price_threshold_eur: float | None = None  # curtail when price <= this
                                                          # None = use opex_eur_per_mwh as floor
                                                          # (i.e. don't sell at a loss)
    prioritise_h2: bool = True                        # True = excess goes to electrolyser before grid

"""
BESS techno-economic parameters.

All values taken from Table 6.2 of Francisco's thesis.
'Most optimistic' (2-hour autonomy) CAPEX values used as primary defaults.
"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class BESSConfig:
    # ------------------------------------------------------------------
    # Battery module
    # ------------------------------------------------------------------
    rated_power_mw: float = 100.0     # Rated charge/discharge power [MW]
    autonomy_h: float = 2.0           # Autonomy [h] → capacity = power × autonomy
    eta_lib_in: float = 0.92          # Battery charging efficiency
    eta_lib_out: float = 0.92         # Battery discharging efficiency
    eta_inverter: float = 0.97        # Inverter (AC↔DC) efficiency
    soc_max: float = 1.0              # Maximum SOC
    soc_min: float = 0.0              # Minimum SOC
    r_sd: float = 0.0                 # Self-discharge rate (≈ 0 in thesis)
    lifetime_years: int = 15          # Battery lifetime [years]

    # ------------------------------------------------------------------
    # Economics — battery DC side [$/kWh]  (2h autonomy, optimistic)
    # ------------------------------------------------------------------
    capex_dc_usd_per_kwh: float = 113.0   # Battery module CAPEX
    om_usd_per_kwh: float = 3.0           # O&M [$/kWh of capacity]
    bop_usd_per_kwh: float = 29.0         # Balance of Plant [$/kWh]
    replacement_pct: float = 0.75         # Replacement = 75 % of battery CAPEX

    # Economics — inverter AC side [$/kW]  (2h autonomy, optimistic)
    capex_ac_usd_per_kw: float = 26.0     # Inverter CAPEX

    # ------------------------------------------------------------------
    # System & project
    # ------------------------------------------------------------------
    tx_loss: float = 0.05
    opex_wfa_mwh: float = 30.0
    farm_capacity_mw: float = 1_000.0
    discount_rate: float = 0.07
    project_life_years: int = 25
    usd_to_eur: float = 1.0 / 1.12

    # ------------------------------------------------------------------
    # Control thresholds (optimised daily — these are defaults only)
    # ------------------------------------------------------------------
    p_charge: float = 40.0         # [€/MWh] charge when price < p_charge
    p_discharge: float = 90.0      # [€/MWh] discharge when price > p_discharge

    # ------------------------------------------------------------------
    # Derived
    # ------------------------------------------------------------------
    cap_lib_mwh: float = field(init=False)   # Energy capacity [MWh]
    capex_total_eur: float = field(init=False)
    capex_battery_eur: float = field(init=False)
    capex_inverter_eur: float = field(init=False)
    capex_bop_eur: float = field(init=False)

    def __post_init__(self) -> None:
        self.cap_lib_mwh = self.rated_power_mw * self.autonomy_h

        # CAPEX [€]
        kwh = self.cap_lib_mwh * 1_000.0   # MWh → kWh
        kw = self.rated_power_mw * 1_000.0  # MW → kW

        self.capex_battery_eur = self.capex_dc_usd_per_kwh * kwh * self.usd_to_eur
        self.capex_inverter_eur = self.capex_ac_usd_per_kw * kw * self.usd_to_eur
        self.capex_bop_eur = self.bop_usd_per_kwh * kwh * self.usd_to_eur
        self.capex_total_eur = (
            self.capex_battery_eur + self.capex_inverter_eur + self.capex_bop_eur
        )

    def annual_om_eur(self) -> float:
        """Annual O&M [€/yr]."""
        kwh = self.cap_lib_mwh * 1_000.0
        return self.om_usd_per_kwh * kwh * self.usd_to_eur

    def replacement_cost_eur(self) -> float:
        """Battery replacement cost [€] = 75 % of battery CAPEX."""
        return self.replacement_pct * self.capex_battery_eur

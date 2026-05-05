"""
HybESS configuration — combines HESS (electrolyzer + tank) and BESS (battery)
into a single hybrid system.

Key difference from standalone HESS: VT = 216 h (not 264 h), which is the
tank volume that maximises NPV in the HybESS scenario (Section 7.5).
"""

from __future__ import annotations
from dataclasses import dataclass, field
import math


@dataclass
class HybESSConfig:
    # ------------------------------------------------------------------
    # Electrolyzer
    # ------------------------------------------------------------------
    p_el_mw: float = 350.0            # Rated power [MW]
    e_pem_kwh_per_kg: float = 51.5    # Specific energy consumption [kWh/kg H2]
    stack_lifetime_h: float = 60_000.0
    water_l_per_kg: float = 10.0      # Water consumption [L/kg H2]

    # Compressor
    p_in_bar: float = 30.0
    p_out_bar: float = 200.0
    eta_comp: float = 0.75
    n_stages: int = 2
    gamma: float = 1.4

    # Hydrogen tank
    vt_hours: float = 216.0           # Tank volume expressed in hours of full EL output
    withdraw_rate_daily: float = 0.05 # Daily withdrawal fraction when SOC > 5 %

    # ------------------------------------------------------------------
    # Battery
    # ------------------------------------------------------------------
    rated_power_mw: float = 100.0
    autonomy_h: float = 2.0
    eta_lib_in: float = 0.92
    eta_lib_out: float = 0.92
    eta_inverter: float = 0.97
    soc_max_bess: float = 1.0
    soc_min_bess: float = 0.0
    r_sd: float = 0.0
    bess_lifetime_years: int = 15

    # Battery economics (DC)
    capex_dc_usd_per_kwh: float = 113.0
    om_usd_per_kwh: float = 3.0
    bop_usd_per_kwh: float = 29.0
    capex_ac_usd_per_kw: float = 26.0
    bess_replacement_pct: float = 0.75

    # ------------------------------------------------------------------
    # Electrolyzer economics
    # ------------------------------------------------------------------
    capex_el_usd_per_kw: float = 1_000.0
    opex_el_eur_per_kw_yr: float = 40.0
    stack_replacement_pct: float = 0.32
    epc_pct: float = 0.05

    # Compressor economics
    opex_comp_pct: float = 0.03

    # Tank economics
    capex_tanks_eur_per_kg: float = 225.0
    opex_tanks_pct: float = 0.005

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
    # Revenue
    # ------------------------------------------------------------------
    p_h2_eur_per_kg: float = 8.0

    # ------------------------------------------------------------------
    # Control — BESS thresholds (optimised daily, defaults only)
    # ------------------------------------------------------------------
    p_charge: float = 40.0
    p_discharge: float = 90.0

    # ------------------------------------------------------------------
    # Enhanced strategy toggle
    # ------------------------------------------------------------------
    enhanced: bool = False

    # ------------------------------------------------------------------
    # Derived (computed in __post_init__)
    # ------------------------------------------------------------------
    cap_lib_mwh: float = field(init=False)
    cap_h2_tanks_kg: float = field(init=False)
    capex_el_eur: float = field(init=False)
    capex_comp_eur: float = field(init=False)
    capex_tanks_eur: float = field(init=False)
    capex_bess_battery_eur: float = field(init=False)
    capex_bess_inverter_eur: float = field(init=False)
    capex_bess_bop_eur: float = field(init=False)
    capex_epc_eur: float = field(init=False)
    capex_total_eur: float = field(init=False)

    def __post_init__(self) -> None:
        # Battery capacity
        self.cap_lib_mwh = self.rated_power_mw * self.autonomy_h

        # H2 tank capacity [kg]: VT hours of full EL production
        h2_rate_kg_per_h = (self.p_el_mw * 1_000.0) / self.e_pem_kwh_per_kg
        self.cap_h2_tanks_kg = self.vt_hours * h2_rate_kg_per_h

        # Electrolyzer CAPEX
        kw_el = self.p_el_mw * 1_000.0
        self.capex_el_eur = self.capex_el_usd_per_kw * kw_el * self.usd_to_eur

        # Compressor CAPEX (Eq 3.7)
        comp_kw = self._calc_compressor_power()
        self.capex_comp_eur = self._calc_compressor_capex(comp_kw)

        # Tank CAPEX
        self.capex_tanks_eur = self.capex_tanks_eur_per_kg * self.cap_h2_tanks_kg

        # BESS CAPEX
        kwh = self.cap_lib_mwh * 1_000.0
        kw_bess = self.rated_power_mw * 1_000.0
        self.capex_bess_battery_eur = self.capex_dc_usd_per_kwh * kwh * self.usd_to_eur
        self.capex_bess_inverter_eur = self.capex_ac_usd_per_kw * kw_bess * self.usd_to_eur
        self.capex_bess_bop_eur = self.bop_usd_per_kwh * kwh * self.usd_to_eur

        # EPC on EL + tanks only (BESS has BoP already included)
        self.capex_epc_eur = self.epc_pct * (self.capex_el_eur + self.capex_tanks_eur)

        self.capex_total_eur = (
            self.capex_el_eur
            + self.capex_comp_eur
            + self.capex_tanks_eur
            + self.capex_bess_battery_eur
            + self.capex_bess_inverter_eur
            + self.capex_bess_bop_eur
            + self.capex_epc_eur
        )

    def _calc_compressor_power(self) -> float:
        """Specific compression work [kW] via Eq 3.6."""
        n, g = self.n_stages, self.gamma
        r = (self.p_out_bar / self.p_in_bar) ** (1.0 / n)
        w_spec = (g / (g - 1.0)) * (1.0 / self.eta_comp) * (r ** ((g - 1.0) / g) - 1.0)
        h2_kg_per_s = (self.p_el_mw * 1_000.0) / (self.e_pem_kwh_per_kg * 3_600.0)
        molar_h2 = 2.016e-3  # kg/mol
        R = 8.314
        T_k = 293.15
        return n * w_spec * h2_kg_per_s * (R * T_k / molar_h2) / 1_000.0  # kW

    def _calc_compressor_capex(self, comp_kw: float) -> float:
        """Compressor CAPEX (Eq 3.7) in €."""
        return self.usd_to_eur * 15_000.0 * (comp_kw / 10.0) ** 0.9

    def annual_opex_hess_eur(self) -> float:
        """Annual fixed OPEX for EL + compressor + tanks [€/yr]."""
        kw_el = self.p_el_mw * 1_000.0
        comp_kw = self._calc_compressor_power()
        comp_capex = self._calc_compressor_capex(comp_kw)
        opex_el = self.opex_el_eur_per_kw_yr * kw_el
        opex_comp = self.opex_comp_pct * comp_capex
        opex_tanks = self.opex_tanks_pct * self.capex_tanks_eur
        return opex_el + opex_comp + opex_tanks

    def annual_bess_om_eur(self) -> float:
        kwh = self.cap_lib_mwh * 1_000.0
        return self.om_usd_per_kwh * kwh * self.usd_to_eur

    def bess_replacement_cost_eur(self) -> float:
        return self.bess_replacement_pct * self.capex_bess_battery_eur

    def el_stack_replacement_cost_eur(self) -> float:
        return self.stack_replacement_pct * self.capex_el_eur

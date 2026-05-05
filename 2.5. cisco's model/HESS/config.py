"""
HESS techno-economic parameters.

All values taken directly from Table 6.1 of Francisco's thesis.
USD figures are converted to EUR using factor 1/1.12 (thesis convention).
"""

from __future__ import annotations
from dataclasses import dataclass, field
import math


@dataclass
class HESSConfig:
    # ------------------------------------------------------------------
    # Electrolyzer (PEMEL)
    # ------------------------------------------------------------------
    p_el_mw: float = 350.0           # Rated capacity [MW]  (PPR=35% of 1 GW)
    e_pem_kwh_per_kg: float = 51.5   # Specific energy consumption [kWh/kg H2]
    stack_lifetime_h: float = 60_000.0  # Stack lifetime [operating hours]
    water_l_per_kg: float = 10.0     # Water consumption [L / kg H2]

    # ------------------------------------------------------------------
    # H2 Compressor (30 → 200 bar, 2 stages, γ=1.4, η=75%)
    # ------------------------------------------------------------------
    p_in_bar: float = 30.0
    p_out_bar: float = 200.0
    eta_comp: float = 0.75
    n_stages: int = 2
    gamma: float = 1.4
    # Compressor power [kW] — Eq 3.6; pre-calculated for PPR=35%/1GW (= 6 288.33 kW)
    # Set to None to recalculate automatically from electrolyzer rated power.
    p_comp_kw: float | None = None

    # ------------------------------------------------------------------
    # H2 Storage (Type I compressed tanks at 200 bar)
    # ------------------------------------------------------------------
    vt_hours: float = 264.0          # Tank volume as full-load hours of EL production
    withdraw_rate_daily: float = 0.05  # Daily withdrawal = 5 % of tank capacity

    # ------------------------------------------------------------------
    # Economics — Electrolyzer
    # ------------------------------------------------------------------
    capex_el_usd_per_kw: float = 1_000.0   # CAPEX [$/kW]
    opex_el_eur_per_kw_yr: float = 40.0    # Fixed OPEX [€/kW/yr]
    stack_replacement_pct: float = 0.32    # Stack replacement = 32 % of EL CAPEX
    epc_pct: float = 0.05                  # EPC = 5 % of EL CAPEX

    # ------------------------------------------------------------------
    # Economics — Compressor
    # ------------------------------------------------------------------
    # CAPEX calculated via Eq 3.7 (auto); OPEX = 3% CAPEX
    opex_comp_pct: float = 0.03

    # ------------------------------------------------------------------
    # Economics — H2 Storage
    # ------------------------------------------------------------------
    capex_tanks_eur_per_kg: float = 225.0  # [€/kg H2]
    opex_tanks_pct: float = 0.005          # OPEX = 0.5 % of CAPEX

    # ------------------------------------------------------------------
    # Economics — Water
    # ------------------------------------------------------------------
    water_cost_eur_per_l: float = 0.001    # ~1 €/m³ tap water

    # ------------------------------------------------------------------
    # System & project
    # ------------------------------------------------------------------
    tx_loss: float = 0.05           # HVAC transmission losses [fraction]
    opex_wfa_mwh: float = 30.0      # Wind farm OPEX [€/MWh of wind output]
    farm_capacity_mw: float = 1_000.0  # Total farm rating [MW]
    discount_rate: float = 0.07
    project_life_years: int = 25
    usd_to_eur: float = 1.0 / 1.12  # USD → EUR conversion used in thesis

    # ------------------------------------------------------------------
    # Control threshold (optimised globally over 25 yr)
    # ------------------------------------------------------------------
    p_storage: float = 144.23       # [€/MWh] — default = thesis optimal at 8 €/kg

    # ------------------------------------------------------------------
    # H2 selling price
    # ------------------------------------------------------------------
    p_h2_eur_per_kg: float = 8.0

    # ------------------------------------------------------------------
    # Derived — computed in __post_init__
    # ------------------------------------------------------------------
    cap_h2_tanks_kg: float = field(init=False)
    capex_comp_eur: float = field(init=False)
    capex_el_eur: float = field(init=False)
    capex_tanks_eur: float = field(init=False)
    capex_epc_eur: float = field(init=False)
    capex_total_eur: float = field(init=False)

    def __post_init__(self) -> None:
        # Tank mass capacity [kg] — Eq 3.9
        self.cap_h2_tanks_kg = (
            self.p_el_mw * 1_000.0 * self.vt_hours / self.e_pem_kwh_per_kg
        )

        # Compressor power [kW] — Eq 3.5 & 3.6
        if self.p_comp_kw is None:
            self.p_comp_kw = self._calc_compressor_power()

        # CAPEX breakdown [€]
        self.capex_el_eur = (
            self.capex_el_usd_per_kw * self.p_el_mw * 1_000.0 * self.usd_to_eur
        )
        self.capex_comp_eur = self._calc_compressor_capex()
        self.capex_tanks_eur = self.capex_tanks_eur_per_kg * self.cap_h2_tanks_kg
        self.capex_epc_eur = self.epc_pct * self.capex_el_eur
        self.capex_total_eur = (
            self.capex_el_eur
            + self.capex_comp_eur
            + self.capex_tanks_eur
            + self.capex_epc_eur
        )

    def _calc_compressor_power(self) -> float:
        """Equation 3.6 — isothermal multi-stage compression power [kW]."""
        q_kg_s = (self.p_el_mw * 1_000.0) / (self.e_pem_kwh_per_kg * 3_600.0)
        Z, T, R, M_h2 = 1.0, 278.0, 8.314, 2.016e-3  # compressibility, K, J/mol/K, kg/mol
        ratio = (self.p_out_bar / self.p_in_bar) ** (1.0 / self.n_stages)
        term = (self.n_stages * self.gamma / (self.gamma - 1)) * (ratio ** ((self.gamma - 1) / self.gamma) - 1)
        p_kw = q_kg_s * (Z * T * R / (M_h2 * self.eta_comp)) * term / 1_000.0
        return p_kw

    def _calc_compressor_capex(self) -> float:
        """Equation 3.7 — compressor CAPEX [€]."""
        return (1.0 / 1.12) * 15_000.0 * (self.p_comp_kw / 10.0) ** 0.9

    def annual_opex_eur(self) -> float:
        """Fixed annual OPEX [€/yr] for all HESS components (excluding water & WFA)."""
        opex_el = self.opex_el_eur_per_kw_yr * self.p_el_mw * 1_000.0
        opex_comp = self.opex_comp_pct * self.capex_comp_eur
        opex_tanks = self.opex_tanks_pct * self.capex_tanks_eur
        return opex_el + opex_comp + opex_tanks

    def stack_replacement_cost_eur(self) -> float:
        """Cost of one EL stack replacement [€] = 32 % of EL CAPEX."""
        return self.stack_replacement_pct * self.capex_el_eur

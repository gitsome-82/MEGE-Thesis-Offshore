"""
hydrogen.py — Electrolyser, hydrogen tank, and fuel cell models.

Simple timestep-based state-update models for the HESS (Hydrogen Energy
Storage System).  Start simple; add ramp constraints / degradation later.
"""
from dataclasses import dataclass


@dataclass
class Electrolyser:
    capacity_mw: float          # max electrical input [MW]
    efficiency_kwh_per_kg: float  # specific energy consumption [kWh / kg H2]
    min_load_frac: float = 0.10   # minimum partial load as fraction of capacity

    @property
    def min_power_mw(self) -> float:
        return self.capacity_mw * self.min_load_frac

    def produce(self, power_mw: float) -> tuple[float, float]:
        """
        Given available electrical power [MW], compute actual consumption
        and hydrogen produced in one hour.

        Returns:
            (power_consumed_mw, h2_produced_kg)
        """
        # Clamp to [0, capacity]
        power_mw = max(0.0, min(power_mw, self.capacity_mw))

        # Below minimum load → electrolyser off
        if power_mw < self.min_power_mw:
            return 0.0, 0.0

        # 1 hour of operation: MWh = MW * 1 h
        energy_mwh = power_mw  # * 1 h
        energy_kwh = energy_mwh * 1000.0
        h2_kg = energy_kwh / self.efficiency_kwh_per_kg

        return power_mw, h2_kg


@dataclass
class HydrogenTank:
    capacity_kg: float          # maximum storage [kg]
    soc_kg: float = 0.0        # current state of charge [kg]

    def charge(self, h2_kg: float) -> tuple[float, float]:
        """
        Try to store *h2_kg* in the tank.

        Returns:
            (h2_stored_kg, h2_excess_kg)
        """
        space = self.capacity_kg - self.soc_kg
        stored = min(h2_kg, space)
        excess = h2_kg - stored
        self.soc_kg += stored
        return stored, excess

    def discharge(self, h2_kg: float) -> float:
        """
        Withdraw up to *h2_kg* from the tank.

        Returns:
            h2_withdrawn_kg
        """
        withdrawn = min(h2_kg, self.soc_kg)
        self.soc_kg -= withdrawn
        return withdrawn

    @property
    def soc_fraction(self) -> float:
        return self.soc_kg / self.capacity_kg if self.capacity_kg > 0 else 0.0


@dataclass
class FuelCell:
    """
    Simple PEM fuel cell model.

    Converts H₂ from the tank back into electricity.  Modelled as a fixed
    electrical efficiency (kWh of electricity out per kg of H₂ consumed).

    Typical PEM FC efficiency: 40–60 % (LHV basis).
    At 33.3 kWh/kg LHV for H₂:
        50 % efficiency → 16.65 kWh_elec / kg_H2  (≈ 16.7 kWh/kg)

    Parameters
    ----------
    capacity_mw           : maximum electrical output [MW]
    efficiency_kwh_per_kg : electrical energy produced per kg H₂ consumed
                            [kWh_elec / kg_H2]
    min_load_frac         : minimum partial-load fraction (below this → off)
    """
    capacity_mw: float
    efficiency_kwh_per_kg: float = 16.7   # ~50 % LHV efficiency
    min_load_frac: float = 0.10

    @property
    def min_power_mw(self) -> float:
        return self.capacity_mw * self.min_load_frac

    @property
    def h2_consumption_kg_per_mwh(self) -> float:
        """How much H₂ [kg] is consumed per MWh of electricity produced."""
        return 1000.0 / self.efficiency_kwh_per_kg

    def generate(self, power_requested_mw: float, h2_available_kg: float) -> tuple[float, float]:
        """
        Generate electricity from H₂.

        Parameters
        ----------
        power_requested_mw : desired electrical output [MW]
        h2_available_kg    : H₂ available in the tank [kg]

        Returns
        -------
        (power_output_mw, h2_consumed_kg)
            power_output_mw  : actual electrical output (may be less than
                               requested if H₂ is limited)
            h2_consumed_kg   : H₂ withdrawn from the tank
        """
        power_mw = max(0.0, min(power_requested_mw, self.capacity_mw))

        if power_mw < self.min_power_mw:
            return 0.0, 0.0

        # H₂ required for the requested output (1 hour)
        h2_required_kg = power_mw * self.h2_consumption_kg_per_mwh  # MW * h * kg/MWh

        # Limit by H₂ availability
        h2_consumed = min(h2_required_kg, h2_available_kg)
        actual_power_mw = h2_consumed / self.h2_consumption_kg_per_mwh

        if actual_power_mw < self.min_power_mw:
            return 0.0, 0.0

        return actual_power_mw, h2_consumed

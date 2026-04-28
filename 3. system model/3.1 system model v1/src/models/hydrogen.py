"""
hydrogen.py — Electrolyser and hydrogen tank models.

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

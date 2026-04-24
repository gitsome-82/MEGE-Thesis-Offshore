"""
battery.py — Battery energy storage model (placeholder for future work).

Same interface pattern as hydrogen.py so it can plug into dispatch.py later.
"""
from dataclasses import dataclass


@dataclass
class Battery:
    capacity_mwh: float         # usable energy capacity [MWh]
    power_mw: float             # max charge / discharge power [MW]
    efficiency: float = 0.90    # round-trip efficiency
    soc_mwh: float = 0.0       # current state of charge [MWh]

    def charge(self, power_mw: float) -> tuple[float, float]:
        """
        Charge the battery for 1 hour at *power_mw*.

        Returns:
            (power_consumed_mw, energy_stored_mwh)
        """
        power_mw = max(0.0, min(power_mw, self.power_mw))
        energy_in = power_mw  # * 1 h
        energy_stored = energy_in * (self.efficiency ** 0.5)  # charge-leg loss
        space = self.capacity_mwh - self.soc_mwh
        energy_stored = min(energy_stored, space)
        self.soc_mwh += energy_stored
        # Actual power drawn from supply
        power_consumed = energy_stored / (self.efficiency ** 0.5) if self.efficiency > 0 else 0
        return power_consumed, energy_stored

    def discharge(self, power_mw: float) -> tuple[float, float]:
        """
        Discharge the battery for 1 hour at *power_mw*.

        Returns:
            (power_delivered_mw, energy_withdrawn_mwh)
        """
        power_mw = max(0.0, min(power_mw, self.power_mw))
        energy_out = power_mw  # * 1 h
        available = self.soc_mwh
        energy_withdrawn = min(energy_out, available)
        self.soc_mwh -= energy_withdrawn
        power_delivered = energy_withdrawn * (self.efficiency ** 0.5)  # discharge-leg loss
        return power_delivered, energy_withdrawn

    @property
    def soc_fraction(self) -> float:
        return self.soc_mwh / self.capacity_mwh if self.capacity_mwh > 0 else 0.0

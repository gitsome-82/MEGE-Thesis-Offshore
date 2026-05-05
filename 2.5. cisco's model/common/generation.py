"""
Vestas V164-8.4 MW power curve and wind-to-farm-power conversion.

The V164-8.4 is the turbine used in WindFloat Atlantic (3 × 8.4 MW = 25.2 MW).
For the 1 GW hypothetical expansion, we scale the per-turbine output proportionally.

Power curve data is based on publicly available Vestas V164 documentation.
"""

import numpy as np

# ---------------------------------------------------------------------------
# Vestas V164-8.4 MW approximate power curve
# wind_speed [m/s], power [kW]
# ---------------------------------------------------------------------------
_WIND_SPEEDS_MS = np.array([
    0.0, 3.0, 3.5, 4.0, 5.0, 6.0, 7.0, 8.0,
    9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 25.0, 25.1,
])

_POWER_KW = np.array([
    0.0, 0.0, 60.0, 280.0, 870.0, 1760.0, 2970.0, 4440.0,
    5960.0, 7080.0, 7800.0, 8200.0, 8400.0, 8400.0, 8400.0, 0.0,
])

# Rated power per turbine [MW]
RATED_MW_PER_TURBINE = 8.4


def v164_power_kw(wind_speed_ms: float | np.ndarray) -> np.ndarray:
    """
    Vestas V164-8.4 power curve: wind speed [m/s] → power [kW] per turbine.

    Parameters
    ----------
    wind_speed_ms : float or array of floats

    Returns
    -------
    power_kw : np.ndarray, same shape as input, clipped to [0, 8400] kW.
    """
    ws = np.asarray(wind_speed_ms, dtype=float)
    power = np.interp(ws, _WIND_SPEEDS_MS, _POWER_KW, left=0.0, right=0.0)
    return np.clip(power, 0.0, 8400.0)


def wind_to_farm_power(
    wind_speed_ms: np.ndarray,
    farm_capacity_mw: float = 1000.0,
    rated_mw_per_turbine: float = RATED_MW_PER_TURBINE,
) -> np.ndarray:
    """
    Convert hub-height wind speed [m/s] to farm output [MW] for a given farm capacity.

    The farm is modelled as N identical V164-8.4 turbines operating at the same wind speed
    (no wake modelling). The number of turbines is farm_capacity_mw / rated_mw_per_turbine.

    Parameters
    ----------
    wind_speed_ms     : array of hourly hub-height wind speeds [m/s]
    farm_capacity_mw  : total installed farm capacity [MW]
    rated_mw_per_turbine : rated power per turbine [MW]

    Returns
    -------
    farm_power_mw : np.ndarray of hourly farm output [MW]
    """
    n_turbines = farm_capacity_mw / rated_mw_per_turbine
    per_turbine_kw = v164_power_kw(wind_speed_ms)
    farm_mw = per_turbine_kw * n_turbines / 1000.0  # kW → MW
    return farm_mw

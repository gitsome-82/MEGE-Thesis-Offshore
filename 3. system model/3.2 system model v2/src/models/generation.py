"""
generation.py — Wind farm generation scaling and power-curve modelling.

Two generation pathways:
    1. National scaling (default): scale German/Portuguese national offshore generation
       by capacity ratio.  No power curve needed — real MWh data used directly.
    2. Power curve (use_power_curve=True): convert site wind speed (Alpha Ventus
       ERA5/ECMWF) to generation using a parametric cubic power curve.
       Turbine parameters are fully configurable in ScenarioConfig.
"""
import numpy as np
import pandas as pd
from src.data.loaders import load_capacity_all
from src.scenarios.config import ScenarioConfig


def scale_generation(
    df: pd.DataFrame,
    target_capacity_mw: float,
    alpha_ventus_capacity_mw: float = 60.0,
    derate_factor: float = 1.0,
    smoothing_window: int = 1,
    reference_capacity_mw: float | None = None,
) -> pd.DataFrame:
    """
    Scale national/regional offshore generation to the target farm capacity.

    Germany: looks up monthly installed DE offshore capacity to derive a
             capacity-factor-based scale factor.
    Portugal (reference_capacity_mw set): uses a fixed reference capacity
             (e.g. 25 MW, the Portuguese offshore total) for direct scaling.

    Adds column 'gen_scaled_mwh' to *df* (in-place) and returns *df*.
    """
    if reference_capacity_mw is not None:
        # Portugal path: fixed reference → direct scale
        scale_factor = target_capacity_mw / reference_capacity_mw
        df["gen_scaled_mwh"] = df["generation_mwh"].fillna(0) * scale_factor * derate_factor
    else:
        # Germany path: monthly installed capacity lookup
        df_cap = load_capacity_all()

        # Build (year, month) → installed offshore capacity [GW → MW] lookup
        cap_lookup = {
            (int(r["year_num"]), int(r["month_num"])): float(r["Wind offshore"]) * 1000  # GW → MW
            for _, r in df_cap.dropna(subset=["Wind offshore"]).iterrows()
        }
        # Fallback: ~8.35 GW if month not in lookup
        fallback_mw = 8_350.0

        keys = list(zip(df["timestamp"].dt.year, df["timestamp"].dt.month))
        installed_mw = pd.Series(
            [cap_lookup.get(k, fallback_mw) for k in keys], index=df.index
        )

        # Scale: national → AV equivalent → target farm
        scale_factor = target_capacity_mw / installed_mw
        df["gen_scaled_mwh"] = df["generation_mwh"].fillna(0) * scale_factor * derate_factor

    # Optional rolling-mean smoothing (window=1 → no change)
    if smoothing_window > 1:
        df["gen_scaled_mwh"] = (
            df["gen_scaled_mwh"]
            .rolling(window=smoothing_window, min_periods=1, center=True)
            .mean()
        )

    return df


# ─────────────────────────────────────────────────────────────────────────────
# Wind-speed height extrapolation
# ─────────────────────────────────────────────────────────────────────────────

def extrapolate_wind_speed(
    v_ref: np.ndarray,
    z_ref: float,
    z_hub: float,
    z0: float = 0.0002,
    **_kwargs,
) -> np.ndarray:
    """
    Extrapolate wind speed from measurement height z_ref to hub height z_hub
    using the logarithmic wind profile (log-law):

        v_hub = v_ref × ln(z_hub / z₀) / ln(z_ref / z₀)

    Assumes neutral atmospheric stability and a fully-developed boundary layer.
    z₀ is the surface roughness length [m].

    !! REPLACE z₀ WITH THE ACTUAL VALUE FOR YOUR SITE !!
    Alpha Ventus / North Sea open sea: z₀ ≈ 0.0001–0.0002 m.
    WindFloat Atlantic / Atlantic coast: z₀ ≈ 0.0002–0.0005 m
    (higher swell and fetch — verify with met-ocean report).

    If z_ref == z_hub, returns v_ref unchanged.

    Parameters
    ----------
    v_ref : wind speed array at reference height z_ref [m/s]
    z_ref : reference (measurement) height [m]
    z_hub : turbine hub height [m]
    z0    : roughness length [m]
    """
    v_ref = np.asarray(v_ref, dtype=float)
    if z_ref == z_hub:
        return v_ref.copy()
    if z0 <= 0:
        raise ValueError("z0_roughness_m must be > 0 for log-law correction.")
    correction = np.log(z_hub / z0) / np.log(z_ref / z0)
    return v_ref * correction


# ─────────────────────────────────────────────────────────────────────────────
# Power-curve pathway
# ─────────────────────────────────────────────────────────────────────────────

def _load_v164_curve() -> tuple:
    """
    Load Vestas V164/8000 power curve from windpowerlib's verified turbine
    database.  Returns (v_array, cf_array) with CF clipped to [0, 1].

    windpowerlib uses the V164/8000 (8.0 MW) variant — the closest available
    to WFA's 8.4 MW turbines.  CF is normalised to rated power so the shape
    is correct regardless of the 5% capacity difference.
    """
    try:
        from windpowerlib import WindTurbine
        t = WindTurbine(turbine_type='V164/8000', hub_height=110)
        pc = t.power_curve
        v_arr = pc['wind_speed'].values.astype(float)
        cf_arr = (pc['value'].values / t.nominal_power).clip(0.0, 1.0)
        # Append explicit cut-out: power drops to 0 just above 25 m/s
        v_arr = np.append(v_arr, [25.01])
        cf_arr = np.append(cf_arr, [0.0])
        return v_arr, cf_arr
    except Exception as e:
        raise ImportError(
            f"windpowerlib is required for power_curve_v164(). "
            f"Install it with: pip install windpowerlib\n({e})"
        )


_V164_CURVE = None   # lazy-loaded on first call


def power_curve_v164(wind_speed_ms: np.ndarray) -> np.ndarray:
    """
    Vestas V164/8000 power curve from windpowerlib's verified turbine database.
    Returns capacity factor [0, 1].

    Source: windpowerlib open-source turbine library (oedb / Vestas datasheet).
    Turbine: V164/8000, 8.0 MW rated, hub height 110 m.
    WFA turbines are 8.4 MW; CF shape is identical, only absolute power scales.
    """
    global _V164_CURVE
    if _V164_CURVE is None:
        _V164_CURVE = _load_v164_curve()
    v = np.asarray(wind_speed_ms, dtype=float)
    return np.interp(v, _V164_CURVE[0], _V164_CURVE[1], left=0.0, right=0.0)


def power_curve_parametric(
    wind_speed_ms: np.ndarray,
    cut_in_ms: float = 3.0,
    rated_speed_ms: float = 11.0,
    cut_out_ms: float = 25.0,
) -> np.ndarray:
    """
    Parametric cubic power curve.  Returns capacity factor in [0, 1].

    Regions
    -------
    v < cut_in                         : 0  (below cut-in; turbine stopped)
    cut_in ≤ v ≤ rated  (cubic ramp)   : (v³ - v_ci³) / (v_r³ - v_ci³)
    rated  < v ≤ cut_out (flat rated)  : 1
    v > cut_out                        : 0  (cut-out; storm protection)

    This is a widely-used approximation that matches typical manufacturer
    power curves well in the ramp region.

    !! REPLACE WITH ACTUAL TURBINE POWER CURVE FOR YOUR CHOSEN MACHINE !!
    Get the tabulated v [m/s] → P [kW] curve from the supplier datasheet
    (e.g. Vestas V236-15MW, SGRE SG 14-222 DD, GE Haliade-X) and swap
    this function for a 1-D interpolation:
        return np.interp(wind_speed_ms, v_table, p_table, left=0, right=0) / p_rated

    Parameters
    ----------
    wind_speed_ms  : wind speed array [m/s] at hub height
    cut_in_ms      : cut-in wind speed [m/s]
    rated_speed_ms : rated wind speed [m/s]  (where P = P_rated)
    cut_out_ms     : cut-out wind speed [m/s]

    Returns
    -------
    capacity_factor : array of floats in [0, 1]
    """
    v = np.asarray(wind_speed_ms, dtype=float)
    cf = np.zeros_like(v)

    ramp = (v >= cut_in_ms) & (v <= rated_speed_ms)
    cf[ramp] = (v[ramp] ** 3 - cut_in_ms ** 3) / (rated_speed_ms ** 3 - cut_in_ms ** 3)

    flat = (v > rated_speed_ms) & (v <= cut_out_ms)
    cf[flat] = 1.0

    return cf.clip(0.0, 1.0)


def generate_from_wind_speed(
    df: pd.DataFrame,
    cfg: ScenarioConfig,
) -> pd.DataFrame:
    """
    Convert site wind speed to farm generation via power curve.

    Steps
    -----
    1. Power-law hub-height correction  (v_hub = v_data × (h_hub/h_data)^α)
    2. Parametric cubic power curve     (v_hub → capacity factor 0–1)
    3. Scale to target farm capacity    (cf × target_farm_capacity_mw)
    4. Apply derate factor and optional smoothing

    Expects column 'wind_speed_ms' in *df* (added by merging with
    load_alpha_ventus_wind output in run_scenario.py).
    Adds column 'gen_scaled_mwh' and returns a copy of *df*.
    """
    v = df["wind_speed_ms"].to_numpy(dtype=float)

    # 1. Hub-height correction (log-law)
    v = extrapolate_wind_speed(
        v,
        z_ref=cfg.wind_data_height_m,
        z_hub=cfg.turbine_hub_height_m,
        z0=cfg.z0_roughness_m,
    )

    # 2. Power curve → capacity factor
    cf = power_curve_parametric(
        v,
        cut_in_ms=cfg.turbine_cut_in_ms,
        rated_speed_ms=cfg.turbine_rated_speed_ms,
        cut_out_ms=cfg.turbine_cut_out_ms,
    )

    # 3 & 4. Scale to farm, derate, smooth
    df = df.copy()
    df["gen_scaled_mwh"] = cf * cfg.target_farm_capacity_mw * cfg.derate_factor

    if cfg.smoothing_window > 1:
        df["gen_scaled_mwh"] = (
            df["gen_scaled_mwh"]
            .rolling(window=cfg.smoothing_window, min_periods=1, center=True)
            .mean()
        )

    return df

"""
generation.py — Wind farm generation scaling from Alpha Ventus to target capacity.
"""
import pandas as pd
from src.data.loaders import load_capacity_all


def scale_generation(
    df: pd.DataFrame,
    target_capacity_mw: float,
    alpha_ventus_capacity_mw: float = 60.0,
    derate_factor: float = 1.0,
    smoothing_window: int = 1,
) -> pd.DataFrame:
    """
    Scale national offshore generation down to Alpha Ventus equivalent,
    then up to the target farm capacity.

    Steps:
        1. Look up actual installed DE offshore capacity for each row's (year, month).
        2. Compute AV-equivalent output:  gen * (AV_capacity / installed_capacity).
        3. Scale to target farm:  AV_equiv * (target_capacity / AV_capacity).
        4. Apply optional derate factor and smoothing.

    Adds column 'gen_scaled_mwh' to *df* (in-place) and returns *df*.
    """
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

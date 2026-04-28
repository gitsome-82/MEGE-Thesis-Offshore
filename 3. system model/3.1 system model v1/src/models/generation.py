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

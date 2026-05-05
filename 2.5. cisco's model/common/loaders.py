"""
Data loaders for the Francisco WFA model.

Wind power
----------
Source: DATA/Portugal Data/Gen data/{year}.csv  (ENTSO-E format)
        Filters "Wind Offshore" rows → actual WFA generation profile.
        Scaled to farm_capacity_mw using WFA installed capacity (25.2 MW).
        Since WFA is Portugal's only offshore wind farm the national offshore
        total equals WFA output, so the capacity-factor profile is accurate.

Electricity prices
------------------
Source: DATA/Portugal Data/GUI_ENERGY_PRICES_*.csv  (ENTSO-E day-ahead)
        Columns: MTU (CET/CEST), Day-ahead Price (EUR/MWh)
        Resolution: hourly up to end of 2024, 15-min from 2025 onwards.
        15-min data is resampled to hourly (mean within each hour).
        Download: https://transparency.entsoe.eu/ → Day Ahead Prices → Portugal

Fallback: flat 50 EUR/MWh with a warning if no price file is found.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths relative to this file:
# common/loaders.py  →  2.5. cisco's model/common/loaders.py
# REPO_ROOT is 2 levels up: cisco's model → MEGE-Thesis-Offshore (workspace root)
# ---------------------------------------------------------------------------
_THIS_DIR = Path(__file__).resolve().parent
_MODEL_DIR = _THIS_DIR.parent            # 2.5. cisco's model/
_REPO_ROOT = _MODEL_DIR.parent           # workspace root

DATA_DIR = _REPO_ROOT / "DATA"
PT_GEN_DIR = DATA_DIR / "Portugal Data" / "Gen data"
PT_PRICES_DIR = DATA_DIR / "Portugal Data"

# WFA installed capacity [MW] – used to derive capacity-factor profile
WFA_INSTALLED_MW = 25.2


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _parse_mtu_start(mtu_str: str, has_seconds: bool = False) -> pd.Timestamp:
    """Parse 'DD/MM/YYYY HH:MM[:SS] - DD/MM/YYYY HH:MM[:SS]' → start timestamp."""
    start = str(mtu_str).split(" - ")[0].strip()
    fmt = "%d/%m/%Y %H:%M:%S" if has_seconds else "%d/%m/%Y %H:%M"
    return pd.to_datetime(start, format=fmt, errors="coerce")


# ---------------------------------------------------------------------------
# Wind power
# ---------------------------------------------------------------------------

def load_wind_power(year: int, farm_capacity_mw: float = 1000.0) -> pd.Series:
    """
    Load hourly wind power for the WFA site scaled to farm_capacity_mw [MW].

    Uses actual ENTSO-E Portugal offshore generation (= WFA output) as the
    capacity-factor profile, then scales to the hypothetical farm size.

    Returns a pd.Series with a UTC DatetimeIndex at 1-hour resolution.
    """
    csv_path = PT_GEN_DIR / f"{year}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Portugal generation file not found: {csv_path}\n"
            "Expected ENTSO-E CSV with columns:\n"
            "  MTU (CET/CEST), Area, Production Type, Generation (MW)"
        )

    df = pd.read_csv(csv_path)
    mask = df["Production Type"].str.strip().str.lower() == "wind offshore"
    offshore = df[mask].copy()

    if offshore.empty:
        raise ValueError(f"No 'Wind Offshore' rows found in {csv_path}")

    # Detect whether MTU timestamps include seconds
    sample = str(offshore["MTU (CET/CEST)"].iloc[0])
    has_sec = sample.count(":") >= 4  # e.g. "01/01/2024 00:00:00 - ..."

    offshore["datetime"] = offshore["MTU (CET/CEST)"].apply(
        lambda s: _parse_mtu_start(s, has_seconds=has_sec)
    )
    gen = (
        offshore.set_index("datetime")
        .sort_index()[["Generation (MW)"]]
        .rename(columns={"Generation (MW)": "wind_mw"})
    )
    gen = pd.to_numeric(gen["wind_mw"], errors="coerce").fillna(0.0)

    # Localise CET/CEST → UTC
    gen.index = (
        pd.to_datetime(gen.index)
        .tz_localize("Europe/Lisbon", ambiguous="NaT", nonexistent="shift_forward")
        .tz_convert("UTC")
    )
    gen = gen[~gen.index.isna()]

    # Resample to hourly (handles any sub-hourly data if present)
    gen = gen.resample("h").mean()

    # Scale WFA actual output → hypothetical farm_capacity_mw
    scale = farm_capacity_mw / WFA_INSTALLED_MW
    gen = (gen * scale).clip(lower=0.0)
    gen.name = "wind_power_mw"
    return gen


# ---------------------------------------------------------------------------
# Electricity prices
# ---------------------------------------------------------------------------

def load_prices(year: int) -> pd.Series:
    """
    Load hourly MIBEL day-ahead electricity prices [EUR/MWh] for a given year.

    Reads ENTSO-E GUI_ENERGY_PRICES_*.csv files from the Portugal Data folder.
    Handles both hourly (≤2024) and 15-min (≥2025) resolution automatically
    by resampling to hourly via mean.

    Returns a pd.Series with a UTC DatetimeIndex at 1-hour resolution.
    """
    price_files = sorted(PT_PRICES_DIR.glob("GUI_ENERGY_PRICES_*.csv"))
    if not price_files:
        warnings.warn(
            f"No GUI_ENERGY_PRICES_*.csv files found in:\n  {PT_PRICES_DIR}\n"
            "Using flat fallback price of 50 EUR/MWh.",
            stacklevel=2,
        )
        idx = pd.date_range(f"{year}-01-01", periods=8760, freq="h", tz="UTC")
        return pd.Series(50.0, index=idx, name="price_eur_mwh")

    frames = []
    for f in price_files:
        s = _parse_entso_price_csv(f)
        if not s.empty:
            frames.append(s)

    if not frames:
        raise ValueError(f"Could not parse any price data from {PT_PRICES_DIR}")

    prices = pd.concat(frames).sort_index()

    # Keep only the requested year
    prices = prices[prices.index.year == year]

    if prices.empty:
        warnings.warn(
            f"No price data found for year {year} in GUI_ENERGY_PRICES files.\n"
            "Using flat fallback price of 50 EUR/MWh.",
            stacklevel=2,
        )
        idx = pd.date_range(f"{year}-01-01", periods=8760, freq="h", tz="UTC")
        return pd.Series(50.0, index=idx, name="price_eur_mwh")

    # Resample to hourly (mean within each hour – handles both 1h and 15-min data)
    prices = prices.resample("h").mean()
    prices.name = "price_eur_mwh"
    return prices


def _parse_entso_price_csv(path: Path) -> pd.Series:
    """
    Parse an ENTSO-E GUI_ENERGY_PRICES_*.csv file.

    Expected columns: MTU (CET/CEST), Area, Sequence,
                      Day-ahead Price (EUR/MWh), ...
    MTU format: 'DD/MM/YYYY HH:MM:SS - DD/MM/YYYY HH:MM:SS'
    """
    try:
        df = pd.read_csv(path, dtype=str)
    except Exception as exc:
        warnings.warn(f"Could not read {path.name}: {exc}", stacklevel=3)
        return pd.Series(dtype=float)

    df.columns = [c.strip().strip('"') for c in df.columns]

    price_col = next(
        (c for c in df.columns if "day-ahead price" in c.lower()),
        None,
    )
    mtu_col = next((c for c in df.columns if c.lower().startswith("mtu")), None)

    if price_col is None or mtu_col is None:
        warnings.warn(
            f"Expected columns not found in {path.name}. "
            f"Got: {list(df.columns)}",
            stacklevel=3,
        )
        return pd.Series(dtype=float)

    # Detect timestamp format (with or without seconds)
    sample = str(df[mtu_col].dropna().iloc[0]).strip().strip('"')
    has_sec = sample.count(":") >= 4

    df["_dt"] = df[mtu_col].apply(lambda s: _parse_mtu_start(str(s).strip('"'), has_seconds=has_sec))
    df["_price"] = pd.to_numeric(df[price_col].str.strip().str.strip('"'), errors="coerce")

    df = df.dropna(subset=["_dt", "_price"])

    if df.empty:
        return pd.Series(dtype=float)

    # Localise CET/CEST → UTC
    dt_index = (
        pd.DatetimeIndex(df["_dt"].values)
        .tz_localize("Europe/Lisbon", ambiguous="NaT", nonexistent="shift_forward")
        .tz_convert("UTC")
    )
    s = pd.Series(df["_price"].values, index=dt_index)
    s = s[~s.index.isna()]
    return s


# ---------------------------------------------------------------------------
# Build simulation input
# ---------------------------------------------------------------------------

def build_simulation_df(
    years: list[int] | None = None,
    n_project_years: int = 25,
    farm_capacity_mw: float = 1000.0,
    start_year: int = 2025,
) -> pd.DataFrame:
    """
    Build a 25-year hourly DataFrame of [wind_mw, price] by tiling the base years.

    Parameters
    ----------
    years            : base years to load and concatenate (default [2023, 2024])
    n_project_years  : project lifetime in years to tile to
    farm_capacity_mw : total wind farm capacity [MW]
    start_year       : start year for the reconstructed index

    Returns
    -------
    pd.DataFrame with columns ['wind_mw', 'price'] and n_project_years×8760 rows.
    """
    if years is None:
        years = [2023, 2024]

    wind_parts = [load_wind_power(y, farm_capacity_mw) for y in years]
    price_parts = [load_prices(y) for y in years]

    wind = pd.concat(wind_parts).sort_index()
    price = pd.concat(price_parts).sort_index()

    df = pd.DataFrame({"wind_mw": wind, "price": price})
    # Resample to guaranteed hourly grid, then fill any gaps created by
    # DST transitions or missing data (e.g. the fall-back hour dropped
    # during localisation).  Wind gaps → 0 MW; price gaps → carry forward.
    df = df.resample("h").mean()
    df["wind_mw"] = df["wind_mw"].fillna(0.0)
    df["price"] = df["price"].ffill().bfill()

    # Tile to n_project_years × 8760 hours
    n_target = n_project_years * 8760
    values = np.tile(df.values, (int(np.ceil(n_target / len(df))), 1))[:n_target]
    idx = pd.date_range(f"{start_year}-01-01", periods=n_target, freq="h", tz="UTC")
    return pd.DataFrame(values[: len(idx)], index=idx, columns=df.columns)

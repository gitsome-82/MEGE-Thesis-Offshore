"""
loaders.py — Load and clean raw input data (generation, load, price, capacity).

All functions return plain DataFrames with a 'timestamp' column.
No Streamlit dependency — can be used in scripts, notebooks, or the app.
"""
import pandas as pd
from functools import lru_cache
from src.data.preprocess import parse_smard_timestamp, parse_smard_numeric
from src.scenarios.config import DATA_DIR, PT_DATA_DIR


# ── SMARD ──────────────────────────────────────────────────────────────────

def load_smard_generation(year: int) -> pd.DataFrame:
    """Hourly offshore-wind generation [MWh] from SMARD for *year*."""
    path = DATA_DIR / "SMARD data" / "SMARD Actual_generation_202201010000_202604140100_Hour.csv"
    df = pd.read_csv(path, sep=';')
    df['timestamp'] = parse_smard_timestamp(df['Start date'])
    col = next((c for c in df.columns if c.startswith("Wind offshore")), None)
    df["generation_mwh"] = parse_smard_numeric(df[col])
    df = df[["timestamp", "generation_mwh"]].dropna()
    return df[df["timestamp"].dt.year == year].reset_index(drop=True)


def load_smard_load(year: int) -> pd.DataFrame:
    """Hourly grid load [MWh] from SMARD for *year*."""
    path = DATA_DIR / "SMARD data" / "SMARD Actual_consumption_202201010000_202604140100_Hour.csv"
    df = pd.read_csv(path, sep=';')
    df['timestamp'] = parse_smard_timestamp(df['Start date'])
    col = next((c for c in df.columns if c.startswith("grid load")), None)
    df["load_mwh"] = parse_smard_numeric(df[col])
    df = df[["timestamp", "load_mwh"]].dropna()
    return df[df["timestamp"].dt.year == year].reset_index(drop=True)


def load_smard_prices(year: int) -> pd.DataFrame:
    """
    Hourly day-ahead price [€/MWh] for Germany/Luxembourg from SMARD.

    Uses per-year files in:
        DATA/Germany Data/SMARD data/Historical forecast data/
            Day-ahead_prices_<YYYYMMDD>0000_<YYYYMMDD>0100_Hour.csv

    The 'Germany/Luxembourg' column is EPEX SPOT day-ahead — the same
    source as Frauenhofer's 'Day Ahead Auction (DE-LU)' column.
    """
    folder = DATA_DIR / "SMARD data" / "Historical forecast data"
    # Match file whose name contains the start year
    candidates = sorted(folder.glob(f"Day-ahead_prices_{year}*.csv"))
    if not candidates:
        raise FileNotFoundError(
            f"No SMARD day-ahead price file found for year {year} in {folder}"
        )
    path = candidates[0]
    df = pd.read_csv(path, sep=';')
    df['timestamp'] = parse_smard_timestamp(df['Start date'])
    price_col = next((c for c in df.columns if c.startswith("Germany/Luxembourg")), None)
    if price_col is None:
        raise KeyError(f"Could not find Germany/Luxembourg price column in {path.name}")
    df["price_eur_per_mwh"] = parse_smard_numeric(df[price_col])
    df = df[["timestamp", "price_eur_per_mwh"]].dropna()
    return df[df["timestamp"].dt.year == year].reset_index(drop=True)


# ── Frauenhofer energy-charts ─────────────────────────────────────────────

def load_frauenhofer(year: int) -> pd.DataFrame:
    """Hourly offshore generation [MWh] and load [MWh] from Frauenhofer 15-min data."""
    path = DATA_DIR / "Frauenhofer data" / f"energy-charts_Public_net_electricity_generation_in_Germany_in_{year} MW.csv"
    df = pd.read_csv(path, skiprows=[1])
    df["timestamp"] = pd.to_datetime(df["Date (GMT+1)"], format="ISO8601", utc=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S"))
    df["Wind offshore"] = pd.to_numeric(df["Wind offshore"], errors='coerce')
    df["Load"] = pd.to_numeric(df["Load"], errors='coerce')
    df = df.rename(columns={"Wind offshore": "offshore_mw", "Load": "load_mw"})

    # Aggregate 15-min MW readings → hourly MWh
    df["hour"] = df["timestamp"].dt.floor("h")
    hourly = df.groupby("hour").agg(
        generation_mwh=("offshore_mw", lambda x: (x * 0.25).sum()),
        load_mwh=("load_mw", lambda x: (x * 0.25).sum()),
    ).reset_index().rename(columns={"hour": "timestamp"})
    return hourly[hourly["timestamp"].dt.year == year].reset_index(drop=True)


def load_frauenhofer_prices(year: int) -> pd.DataFrame:
    """
    Hourly day-ahead price [EUR/MWh] from Frauenhofer energy-charts.

    Tries the dedicated spot-price file first (only exists for some years).
    Falls back to the public generation CSV which always includes the
    'Day Ahead Auction (DE-LU)' column.  15-min prices are averaged to hourly
    (day-ahead prices are constant within each hour, so the mean is exact).
    """
    spot_path = DATA_DIR / "Frauenhofer data" / f"energy-charts_Electricity_production_and_spot_prices_in_Germany_in_{year} (1).csv"
    gen_path  = DATA_DIR / "Frauenhofer data" / f"energy-charts_Public_net_electricity_generation_in_Germany_in_{year} MW.csv"

    if spot_path.exists():
        path = spot_path
    elif gen_path.exists():
        path = gen_path
    else:
        raise FileNotFoundError(f"No Frauenhofer price or generation file found for year {year}.")

    df = pd.read_csv(path, skiprows=[1])
    df["timestamp"] = pd.to_datetime(df["Date (GMT+1)"], format="ISO8601", utc=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S"))
    price_col = [c for c in df.columns if "Day Ahead" in c or "Auction" in c][0]
    df["price_eur_per_mwh"] = pd.to_numeric(df[price_col], errors='coerce')
    df = df[["timestamp", "price_eur_per_mwh"]].dropna()

    # If 15-min data, resample to hourly mean (same price repeated 4×, so mean is exact)
    if (df["timestamp"].diff().dropna().dt.total_seconds() < 3600).any():
        df["hour"] = df["timestamp"].dt.floor("h")
        df = (df.groupby("hour")["price_eur_per_mwh"]
                .mean()
                .reset_index()
                .rename(columns={"hour": "timestamp"}))

    return df.reset_index(drop=True)


# ── Installed capacity (for scaling) ──────────────────────────────────────

def load_capacity_all() -> pd.DataFrame:
    """Monthly installed offshore capacity [GW] from Frauenhofer."""
    path = DATA_DIR / "Frauenhofer data" / "energy-charts_Net_installed_electricity_generation_capacity_in_Germany.csv"
    df = pd.read_csv(path, skiprows=[1])
    df[["month_str", "year_str"]] = df["Month.Year"].astype(str).str.split(".", expand=True)
    df["month_num"] = pd.to_numeric(df["month_str"], errors='coerce').astype(int)
    df["year_num"] = pd.to_numeric(df["year_str"], errors='coerce').astype(int)
    df["Wind offshore"] = pd.to_numeric(df["Wind offshore"], errors='coerce')
    return df


# ── Alpha Ventus site wind speed ───────────────────────────────────────────

def load_alpha_ventus_wind(year: int, use_forecast: bool = False) -> pd.DataFrame:
    """
    Load Alpha Ventus hourly wind speed data downloaded from Open-Meteo.

    actual   (ERA5, 100 m)  : alpha_ventus_wind_actual.csv
    forecast (ECMWF, 120 m) : alpha_ventus_wind_forecast_hx.csv

    Returns DataFrame with columns: timestamp, wind_speed_ms
    """
    if use_forecast:
        path = DATA_DIR / "alpha_ventus_wind_forecast_hx.csv"
        speed_col = "wind_speed_120m_ms"
    else:
        path = DATA_DIR / "alpha_ventus_wind_actual.csv"
        speed_col = "wind_speed_100m_ms"

    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["datetime"])
    df = df.rename(columns={speed_col: "wind_speed_ms"})
    df = df[["timestamp", "wind_speed_ms"]].dropna()
    df = df[df["timestamp"].dt.year == year].reset_index(drop=True)
    return df


# ── Portugal (ENTSO-E) ─────────────────────────────────────────────────────

def _parse_mtu_start(series: pd.Series) -> pd.Series:
    """Parse ENTSO-E MTU range strings to timestamps."""
    starts = series.str.split(" - ").str[0].str.strip()
    ts = pd.to_datetime(starts, format="%d/%m/%Y %H:%M:%S", errors="coerce")
    missing = ts.isna()
    if missing.any():
        ts.loc[missing] = pd.to_datetime(starts[missing], format="%d/%m/%Y %H:%M", errors="coerce")
    return ts


def load_pt_generation(year: int) -> pd.DataFrame:
    """Hourly Wind Offshore generation [MWh] for Portugal from ENTSO-E."""
    path = PT_DATA_DIR / "Gen data" / f"{year}.csv"
    df = pd.read_csv(path)
    df = df[df["Production Type"] == "Wind Offshore"].copy()
    df["timestamp"] = _parse_mtu_start(df["MTU (CET/CEST)"])
    df["generation_mwh"] = pd.to_numeric(df["Generation (MW)"], errors="coerce")
    df = df[["timestamp", "generation_mwh"]].dropna()
    return df[df["timestamp"].dt.year == year].sort_values("timestamp").reset_index(drop=True)


def load_pt_load(year: int) -> pd.DataFrame:
    """Hourly actual total load [MWh] for Portugal from ENTSO-E."""
    target_file = None
    for f in sorted(PT_DATA_DIR.glob("GUI_TOTAL_LOAD_DAYAHEAD_*.csv")):
        parts = f.stem.split("-")
        if len(parts) >= 2 and parts[-1][:4] == str(year):
            target_file = f
            break
    if target_file is None:
        raise FileNotFoundError(f"No Portugal load file found for year {year}")
    df = pd.read_csv(target_file)
    df["timestamp"] = _parse_mtu_start(df["MTU (CET/CEST)"])
    df["load_mwh"] = pd.to_numeric(df["Actual Total Load (MW)"], errors="coerce")
    df = df[["timestamp", "load_mwh"]].dropna()
    return df[df["timestamp"].dt.year == year].sort_values("timestamp").reset_index(drop=True)


def load_pt_prices(year: int) -> pd.DataFrame:
    """
    Hourly day-ahead price [EUR/MWh] for Portugal (MIBEL/OMIE) from ENTSO-E.

    Files: DATA/Portugal Data/GUI_ENERGY_PRICES_<prev_year>12312300-<year>12312300.csv
    Column: 'Day-ahead Price (EUR/MWh)'
    """
    target_file = None
    for f in sorted(PT_DATA_DIR.glob("GUI_ENERGY_PRICES_*.csv")):
        parts = f.stem.split("-")
        if len(parts) >= 2 and parts[-1][:4] == str(year):
            target_file = f
            break
    if target_file is None:
        raise FileNotFoundError(f"No Portugal price file found for year {year}")
    df = pd.read_csv(target_file)
    df["timestamp"] = _parse_mtu_start(df["MTU (CET/CEST)"])
    df["price_eur_per_mwh"] = pd.to_numeric(df["Day-ahead Price (EUR/MWh)"], errors="coerce")
    df = df[["timestamp", "price_eur_per_mwh"]].dropna()
    return df[df["timestamp"].dt.year == year].sort_values("timestamp").reset_index(drop=True)


# ── Convenience: load everything for a year ───────────────────────────────

def load_all_inputs(year: int, source: str = "SMARD", country: str = "Germany") -> pd.DataFrame:
    """
    Load generation, load, and price data for *year*, merged on timestamp.

    Returns DataFrame with columns:
        timestamp, generation_mwh, load_mwh, price_eur_per_mwh
    """
    if country == "Portugal":
        gen = load_pt_generation(year)
        load = load_pt_load(year)
        df = pd.merge(gen, load, on="timestamp")
        try:
            prices = load_pt_prices(year)
            df = pd.merge(df, prices, on="timestamp", how="left")
        except FileNotFoundError:
            df["price_eur_per_mwh"] = 50.0
            print(f"  WARNING: No Portugal day-ahead price data found for {year} — using flat €50/MWh.")
        return df.sort_values("timestamp").reset_index(drop=True)

    if source == "SMARD":
        gen = load_smard_generation(year)
        load = load_smard_load(year)
        df = pd.merge(gen, load, on="timestamp")
    else:
        df = load_frauenhofer(year)

    # Try to attach price data:
    # 1st choice — SMARD dedicated day-ahead price files (2022–2026, hourly)
    # 2nd choice — Frauenhofer generation CSV (has Day Ahead Auction column)
    # Fallback  — flat €50/MWh placeholder
    try:
        prices = load_smard_prices(year)
    except (FileNotFoundError, KeyError, StopIteration):
        try:
            prices = load_frauenhofer_prices(year)
        except (FileNotFoundError, IndexError):
            prices = None

    if prices is not None:
        df = pd.merge(df, prices, on="timestamp", how="left")
    else:
        df["price_eur_per_mwh"] = 50.0  # fallback flat price
        print(f"  WARNING: No day-ahead price data found for {year} — using flat €50/MWh.")

    df = df.sort_values("timestamp").reset_index(drop=True)
    return df

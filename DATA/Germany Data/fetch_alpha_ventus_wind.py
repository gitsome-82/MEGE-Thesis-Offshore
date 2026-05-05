"""
One-time script: fetch Alpha Ventus wind speed data from Open-Meteo and save to CSV.
can update, embed later for LIVE fetching in the app, or just load the CSVs in loaders.py.

Alpha Ventus offshore wind farm, Germany
  Coordinates : 54.011111°N, 6.607778°E
  Hub height  : ~100 m (actual turbines), 120 m also fetched for forecast model

Two datasets saved:
  1. alpha_ventus_wind_actual.csv
       Source  : ERA5 reanalysis (Open-Meteo Historical Weather API)
       Variable: wind_speed_100m  [m/s]
       Period  : 2022-01-01 → latest available

  2. alpha_ventus_wind_forecast_hx.csv
       Source  : Historical forecast (ECMWF IFS, re-run forecasts)
       Variable: wind_speed_120m  [m/s]
       Period  : 2022-01-01 → latest available

Usage:
    python "DATA/Germany Data/fetch_alpha_ventus_wind.py"
  or run once from the terminal; the CSVs are then loaded by loaders.py.

Dependencies (install once):
    pip install openmeteo-requests requests-cache retry-requests numpy pandas
"""

from __future__ import annotations

import sys
import subprocess
from pathlib import Path

# Auto-install dependencies if missing
_deps = ["openmeteo_requests", "requests_cache", "retry_requests", "numpy", "pandas"]
for _dep in _deps:
    try:
        __import__(_dep)
    except ImportError:
        print(f"Installing {_dep} …")
        subprocess.check_call([sys.executable, "-m", "pip", "install", _dep])

import openmeteo_requests
import pandas as pd
import requests_cache
from retry_requests import retry

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LAT = 54.011111
LON = 6.607778
START_DATE = "2022-01-01"
END_DATE = "2026-04-29"

OUT_DIR = Path(__file__).resolve().parent
ACTUAL_CSV = OUT_DIR / "alpha_ventus_wind_actual.csv"
FORECAST_CSV = OUT_DIR / "alpha_ventus_wind_forecast_hx.csv"


def make_client(expire_after: int = -1) -> openmeteo_requests.Client:
    """Create an Open-Meteo client with caching + automatic retry."""
    cache_session = requests_cache.CachedSession(".cache", expire_after=expire_after)
    retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
    return openmeteo_requests.Client(session=retry_session)


# ---------------------------------------------------------------------------
# 1. Actual historical wind speed (ERA5 reanalysis, 100 m hub height)
# ---------------------------------------------------------------------------
def fetch_actual() -> pd.DataFrame:
    print("\n--- Fetching actual historical wind (ERA5, 100 m) ---")
    client = make_client(expire_after=-1)  # cache forever (static reanalysis)

    params = {
        "latitude": LAT,
        "longitude": LON,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "hourly": "wind_speed_100m",
        "timezone": "UTC",
        "wind_speed_unit": "ms",
    }
    responses = client.weather_api("https://archive-api.open-meteo.com/v1/archive", params=params)
    r = responses[0]
    print(f"  Coordinates: {r.Latitude():.4f}°N  {r.Longitude():.4f}°E")
    print(f"  Elevation  : {r.Elevation():.0f} m asl")

    hourly = r.Hourly()
    df = pd.DataFrame({
        "datetime": pd.date_range(
            start=pd.to_datetime(hourly.Time(), unit="s", utc=True),
            end=pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True),
            freq=pd.Timedelta(seconds=hourly.Interval()),
            inclusive="left",
        ),
        "wind_speed_100m_ms": hourly.Variables(0).ValuesAsNumpy(),
    })
    print(f"  Rows       : {len(df):,}  ({df['datetime'].iloc[0].date()} → {df['datetime'].iloc[-1].date()})")
    return df


# ---------------------------------------------------------------------------
# 2. Historical-forecast wind speed (ECMWF IFS re-runs, 120 m)
# ---------------------------------------------------------------------------
def fetch_forecast_hx() -> pd.DataFrame:
    print("\n--- Fetching historical forecast wind (ECMWF IFS, 120 m) ---")
    client = make_client(expire_after=3600)  # cache for 1 h (may extend near real-time)

    params = {
        "latitude": LAT,
        "longitude": LON,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "hourly": "wind_speed_120m",
        "timezone": "UTC",
        "wind_speed_unit": "ms",
    }
    responses = client.weather_api(
        "https://historical-forecast-api.open-meteo.com/v1/forecast", params=params
    )
    r = responses[0]
    print(f"  Coordinates: {r.Latitude():.4f}°N  {r.Longitude():.4f}°E")
    print(f"  Elevation  : {r.Elevation():.0f} m asl")

    hourly = r.Hourly()
    df = pd.DataFrame({
        "datetime": pd.date_range(
            start=pd.to_datetime(hourly.Time(), unit="s", utc=True),
            end=pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True),
            freq=pd.Timedelta(seconds=hourly.Interval()),
            inclusive="left",
        ),
        "wind_speed_120m_ms": hourly.Variables(0).ValuesAsNumpy(),
    })
    print(f"  Rows       : {len(df):,}  ({df['datetime'].iloc[0].date()} → {df['datetime'].iloc[-1].date()})")
    return df


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("  Alpha Ventus wind data fetch")
    print(f"  Lat: {LAT}°N   Lon: {LON}°E")
    print(f"  Period: {START_DATE} → {END_DATE}")
    print("=" * 60)

    actual_df = fetch_actual()
    actual_df.to_csv(ACTUAL_CSV, index=False)
    print(f"\n  Saved → {ACTUAL_CSV.name}")

    forecast_df = fetch_forecast_hx()
    forecast_df.to_csv(FORECAST_CSV, index=False)
    print(f"\n  Saved → {FORECAST_CSV.name}")

    print("\nDone. Both CSVs are ready to load.")
    print(f"  Actual   : {ACTUAL_CSV}")
    print(f"  Forecast : {FORECAST_CSV}")

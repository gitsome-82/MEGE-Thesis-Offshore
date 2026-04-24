"""
Portugal — data loading, scaling, and Streamlit render function.
Generation data: ENTSO-E per-type hourly CSVs (Gen data/YYYY.csv).
Load data:       ENTSO-E day-ahead total load CSVs (GUI_TOTAL_LOAD_DAYAHEAD_*.csv).
"""

import calendar
import pathlib

import pandas as pd
import streamlit as st

from .common import (
    seasons,
    render_top_metrics,
    render_summary_expander,
    plot_year_view,
    plot_season_view,
    plot_month_view,
    plot_day_view,
)

# Portugal data directory
DATA_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "DATA" / "Portugal Data"

# Reference installed offshore wind capacity used when the data was collected
REFERENCE_CAPACITY_MW = 25.0


# ---------------------------------------------------------------------------
# Timestamp parser — handles both "HH:MM:SS" and "HH:MM" variants
# ---------------------------------------------------------------------------

def _parse_mtu_start(series):
    """Extract start timestamp from MTU range strings.

    Handles:
        '01/01/2023 00:00:00 - 01/01/2023 01:00:00'
        '01/01/2023 00:00 - 01/01/2023 01:00'
    """
    starts = series.str.split(" - ").str[0].str.strip()
    ts = pd.to_datetime(starts, format="%d/%m/%Y %H:%M:%S", errors="coerce")
    missing = ts.isna()
    if missing.any():
        ts.loc[missing] = pd.to_datetime(starts[missing], format="%d/%m/%Y %H:%M", errors="coerce")
    return ts


# ---------------------------------------------------------------------------
# Data loaders (cached)
# ---------------------------------------------------------------------------

@st.cache_data
def load_pt_generation(year):
    """Return hourly Wind Offshore generation (MWh) for Portugal for the given year."""
    path = DATA_DIR / "Gen data" / f"{year}.csv"
    df = pd.read_csv(path)
    df = df[df["Production Type"] == "Wind Offshore"].copy()
    df["timestamp"] = _parse_mtu_start(df["MTU (CET/CEST)"])
    df["generation_mwh"] = pd.to_numeric(df["Generation (MW)"], errors="coerce")
    df = df[["timestamp", "generation_mwh"]].dropna()
    return df[df["timestamp"].dt.year == year].sort_values("timestamp").reset_index(drop=True)


@st.cache_data
def load_pt_load(year):
    """Return hourly actual total load (MWh) for Portugal for the given year.

    Matches the load file by the year embedded in the second date of the filename,
    e.g. GUI_TOTAL_LOAD_DAYAHEAD_202212312300-202312312300.csv → year 2023.
    """
    target_file = None
    for f in sorted(DATA_DIR.glob("GUI_TOTAL_LOAD_DAYAHEAD_*.csv")):
        # stem: GUI_TOTAL_LOAD_DAYAHEAD_202212312300-202312312300
        parts = f.stem.split("-")
        if len(parts) >= 2 and parts[-1][:4] == str(year):
            target_file = f
            break
    if target_file is None:
        raise FileNotFoundError(f"No Portugal load file found for year {year} in {DATA_DIR}")

    df = pd.read_csv(target_file)
    df["timestamp"] = _parse_mtu_start(df["MTU (CET/CEST)"])
    df["load_mwh"] = pd.to_numeric(df["Actual Total Load (MW)"], errors="coerce")
    df = df[["timestamp", "load_mwh"]].dropna()
    return df[df["timestamp"].dt.year == year].sort_values("timestamp").reset_index(drop=True)


@st.cache_data
def load_pt(year):
    """Merge generation and load data for Portugal for the given year."""
    gen_df = load_pt_generation(year)
    load_df = load_pt_load(year)
    merged = pd.merge(gen_df, load_df, on="timestamp")
    return merged.dropna(subset=["timestamp", "generation_mwh", "load_mwh"])


# ---------------------------------------------------------------------------
# Scaling helpers
# ---------------------------------------------------------------------------

def _prepare_df(raw_df, target_capacity_mw, load_forecast_mwh, year):
    df = raw_df.copy()
    df["month"] = df["timestamp"].dt.month.astype(int)
    df["day"] = df["timestamp"].dt.date
    df["hour"] = df["timestamp"].dt.hour

    # Generation scaling: linear ratio to reference installed capacity
    df["gen_scaled"] = df["generation_mwh"] * (target_capacity_mw / REFERENCE_CAPACITY_MW)

    # Load scaling: annualise to account for partial-year data, then scale to forecast
    sample_annual_load = df["load_mwh"].sum()
    unique_days = df["timestamp"].dt.date.nunique()
    days_in_year = 366 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 365
    year_coverage = unique_days / days_in_year
    annualised = sample_annual_load / year_coverage if year_coverage > 0 else sample_annual_load
    load_scale = load_forecast_mwh / annualised if annualised > 0 else 1

    df["load_scaled"] = df["load_mwh"] * load_scale
    df["load_met"] = df[["gen_scaled", "load_scaled"]].min(axis=1)
    df["surplus"] = (df["gen_scaled"] - df["load_scaled"]).clip(lower=0)
    df["unmet"] = (df["load_scaled"] - df["gen_scaled"]).clip(lower=0)
    return df, load_scale, year_coverage


# ---------------------------------------------------------------------------
# Streamlit render entry point
# ---------------------------------------------------------------------------

def render():
    st.subheader("Portugal — Offshore Wind vs National Load")
    st.info(
        f"Reference installed offshore wind capacity: **{REFERENCE_CAPACITY_MW:.0f} MW** "
        "(ENTSO-E data, 2024). Generation is scaled linearly from this baseline."
    )

    year = st.selectbox("Year", [2022, 2023, 2024, 2025, 2026], key="pt_year")

    try:
        raw_df = load_pt(year)
    except FileNotFoundError as e:
        st.error(str(e))
        return
    except Exception as e:
        st.error(f"Could not load Portugal data for {year}: {e}")
        return

    if raw_df.empty:
        st.error(f"No data loaded for Portugal {year}.")
        return

    col1, col2 = st.columns(2)
    with col1:
        target_capacity_mw = st.slider(
            "Target offshore capacity (MW)", 0, 20000, 25, 25, key="pt_cap"
        )
    with col2:
        load_forecast_twh = st.slider(
            "Forecast annual load (TWh)", 0, 200, 50, 1, key="pt_load"
        )

    load_forecast_mwh = load_forecast_twh * 1_000_000
    df, load_scale, year_coverage = _prepare_df(raw_df, target_capacity_mw, load_forecast_mwh, year)

    if year_coverage < 0.95:
        unique_days = df["timestamp"].dt.date.nunique()
        st.info(
            f"Note: {year} data covers {year_coverage*100:.0f}% of the year "
            f"({unique_days} days). Load scaling annualised accordingly."
        )

    render_top_metrics(df)
    render_summary_expander(df, target_capacity_mw, capacity_unit="MW")

    view = st.selectbox("View", ["Year", "Season", "Month", "Day"], key="pt_view")

    if view == "Year":
        plot_year_view(df)

    elif view == "Season":
        season = st.selectbox("Season", list(seasons.keys()), key="pt_season")
        months = seasons[season]

        if season == "Winter":
            prev_year = year - 1
            winter_label = f"Winter {prev_year}/{str(year)[-2:]}"
            try:
                prev_raw = load_pt(prev_year)
                prev_df, _, _ = _prepare_df(prev_raw, target_capacity_mw, load_forecast_mwh, prev_year)
                dec_df = prev_df[prev_df["month"] == 12].copy()
                jan_feb = df[df["month"].isin([1, 2])]
                season_df = pd.concat([dec_df, jan_feb]).sort_values("timestamp")
            except Exception as e:
                st.warning(f"Could not load {prev_year} December: {e}. Showing Jan–Feb only.")
                season_df = df[df["month"].isin([1, 2])].sort_values("timestamp")
                winter_label = f"Winter {year} (Jan–Feb only)"
            season_name = winter_label
        else:
            season_df = df[df["month"].isin(months)].sort_values("timestamp")
            season_name = season

        season_df["gen_scaled"] = pd.to_numeric(season_df["gen_scaled"], errors="coerce")
        season_df["load_scaled"] = pd.to_numeric(season_df["load_scaled"], errors="coerce")
        plot_season_view(season_df, season_name)

    elif view == "Month":
        month_names = {calendar.month_name[i]: i for i in range(1, 13)}
        selected_month = st.selectbox("Month", list(month_names.keys()), key="pt_month")
        plot_month_view(df, month_names[selected_month])

    else:  # Day
        day = st.date_input("Day", value=df["timestamp"].min().date(), key="pt_day")
        plot_day_view(df, day)

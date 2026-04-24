"""
Germany — data loading, scaling, and Streamlit render function.
Data sources: Frauenhofer energy-charts CSVs and SMARD hourly CSVs.
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

# Germany data directory (3 levels up from this file → repo root → DATA)
DATA_DIR = str(pathlib.Path(__file__).resolve().parent.parent.parent / "DATA" / "Germany Data")


# ---------------------------------------------------------------------------
# Timestamp / numeric parsers for SMARD format
# ---------------------------------------------------------------------------

def _parse_smard_timestamp(series):
    ts = pd.to_datetime(series, format="%b %d, %Y %I:%M %p", errors="coerce")
    missing = ts.isna()
    if missing.any():
        ts.loc[missing] = pd.to_datetime(series[missing], format="%b-%d, %Y %I:%M %p", errors="coerce")
    return ts


def _parse_smard_numeric(series):
    return pd.to_numeric(series.astype(str).str.replace(",", "", regex=False), errors="coerce")


# ---------------------------------------------------------------------------
# Data loaders (cached)
# ---------------------------------------------------------------------------

@st.cache_data
def load_frauenhofer(year):
    path = (
        f"{DATA_DIR}/Frauenhofer data/"
        f"energy-charts_Public_net_electricity_generation_in_Germany_in_{year} MW.csv"
    )
    df = pd.read_csv(path, skiprows=[1])
    df["timestamp"] = (
        pd.to_datetime(df["Date (GMT+1)"], format="ISO8601", utc=True)
        .dt.tz_convert("Europe/Berlin")
        .dt.tz_localize(None)
    )
    df["Wind offshore"] = pd.to_numeric(df["Wind offshore"], errors="coerce")
    df["Load"] = pd.to_numeric(df["Load"], errors="coerce")
    df = df.rename(columns={"Wind offshore": "offshore_mw", "Load": "load_mw"})
    df = df[["timestamp", "offshore_mw", "load_mw"]]
    df["hour"] = df["timestamp"].dt.floor("h")
    df_hourly = df.groupby("hour").agg(
        offshore_mw=("offshore_mw", lambda x: (x * 0.25).sum()),
        load_mw=("load_mw", lambda x: (x * 0.25).sum()),
    ).reset_index()
    df_hourly = df_hourly.rename(
        columns={"hour": "timestamp", "offshore_mw": "generation_mwh", "load_mw": "load_mwh"}
    )
    return df_hourly[df_hourly["timestamp"].dt.year == year]


@st.cache_data
def _load_smard_combined():
    gen_path = f"{DATA_DIR}/SMARD data/SMARD Actual_generation_202201010000_202604140100_Hour.csv"
    load_path = f"{DATA_DIR}/SMARD data/SMARD Actual_consumption_202201010000_202604140100_Hour.csv"

    gen_df = pd.read_csv(gen_path, sep=";")
    gen_df["timestamp"] = _parse_smard_timestamp(gen_df["Start date"])
    gen_col = next((c for c in gen_df.columns if c.startswith("Wind offshore")), None)
    gen_df["generation_mwh"] = _parse_smard_numeric(gen_df[gen_col])

    load_df = pd.read_csv(load_path, sep=";")
    load_df["timestamp"] = _parse_smard_timestamp(load_df["Start date"])
    load_col = next((c for c in load_df.columns if c.startswith("grid load")), None)
    load_df["load_mwh"] = _parse_smard_numeric(load_df[load_col])

    merged = pd.merge(
        gen_df[["timestamp", "generation_mwh"]],
        load_df[["timestamp", "load_mwh"]],
        on="timestamp",
    )
    return merged.dropna(subset=["timestamp", "generation_mwh", "load_mwh"])


def load_smard(year):
    all_df = _load_smard_combined()
    return all_df[all_df["timestamp"].dt.year == year].copy()


@st.cache_data
def _load_capacity_all():
    path = (
        f"{DATA_DIR}/Frauenhofer data/"
        "energy-charts_Net_installed_electricity_generation_capacity_in_Germany.csv"
    )
    df = pd.read_csv(path, skiprows=[1])
    df[["month_str", "year_str"]] = df["Month.Year"].astype(str).str.split(".", expand=True)
    df["month_num"] = pd.to_numeric(df["month_str"], errors="coerce").astype(int)
    df["year_num"] = pd.to_numeric(df["year_str"], errors="coerce").astype(int)
    df["Wind offshore"] = pd.to_numeric(df["Wind offshore"], errors="coerce")
    return df


def _get_monthly_capacity(df_cap, year):
    year_data = df_cap[df_cap["year_num"] == year][["month_num", "Wind offshore"]].dropna()
    if len(year_data) > 0:
        return {int(m): float(c) for m, c in zip(year_data["month_num"], year_data["Wind offshore"])}
    return None


def _scale_generation(df, target_capacity_gw, df_cap):
    """Scale generation to target_capacity_gw using monthly installed-capacity reference data."""
    cap_lookup = {
        (int(r["year_num"]), int(r["month_num"])): float(r["Wind offshore"])
        for _, r in df_cap.dropna(subset=["Wind offshore"]).iterrows()
    }
    sorted_keys = sorted(cap_lookup.keys())

    def _get_cap(k):
        if k in cap_lookup:
            return cap_lookup[k]
        earlier = [sk for sk in sorted_keys if sk <= k]
        if earlier:
            return cap_lookup[earlier[-1]]
        return cap_lookup[sorted_keys[0]] if sorted_keys else 9.2

    keys = list(zip(df["timestamp"].dt.year, df["timestamp"].dt.month))
    cap_series = pd.Series([_get_cap(k) for k in keys], index=df.index)
    df = df.copy()
    df["gen_scaled"] = df["generation_mwh"].fillna(0) * (target_capacity_gw / cap_series)
    return df


def _prepare_df(raw_df, target_capacity_gw, load_forecast_mwh, df_cap, year):
    df = raw_df.copy()
    df["month"] = df["timestamp"].dt.month.astype(int)
    df["day"] = df["timestamp"].dt.date
    df["hour"] = df["timestamp"].dt.hour

    df = _scale_generation(df, target_capacity_gw, df_cap)

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
    st.subheader("Germany — Offshore Wind vs National Load")

    data_source = st.selectbox("Data Source", ["SMARD", "Frauenhofer"], key="de_source")
    year = st.selectbox("Year", [2022, 2023, 2024, 2025, 2026], key="de_year")

    if data_source == "Frauenhofer":
        raw_df = load_frauenhofer(year)
    else:
        raw_df = load_smard(year)

    if raw_df.empty:
        st.error(f"No valid {data_source} data loaded for {year}.")
        return

    df_cap = _load_capacity_all()
    monthly_cap = _get_monthly_capacity(df_cap, year)
    if monthly_cap:
        st.success(f"Loaded {len(monthly_cap)} months of capacity data for {year}")
    else:
        st.warning(f"No capacity data found for {year}")

    col1, col2 = st.columns(2)
    with col1:
        target_capacity_gw = st.slider("Target offshore capacity (GW)", 0.0, 80.0, 9.2, 0.1, key="de_cap")
    with col2:
        load_forecast_twh = st.slider("Forecast annual load (TWh)", 0, 1000, 400, 5, key="de_load")

    load_forecast_mwh = load_forecast_twh * 1_000_000
    df, load_scale, year_coverage = _prepare_df(raw_df, target_capacity_gw, load_forecast_mwh, df_cap, year)

    if year_coverage < 0.95:
        unique_days = df["timestamp"].dt.date.nunique()
        st.info(
            f"Note: {year} data covers {year_coverage*100:.0f}% of the year "
            f"({unique_days} days). Load scaling annualised accordingly."
        )

    if df["load_mwh"].sum() <= 0:
        st.error("Load data summed to zero — check source CSV formatting.")
        return

    render_top_metrics(df)
    render_summary_expander(df, target_capacity_gw, capacity_unit="GW")

    view = st.selectbox("View", ["Year", "Season", "Month", "Day"], key="de_view")

    if view == "Year":
        plot_year_view(df)

    elif view == "Season":
        season = st.selectbox("Season", list(seasons.keys()), key="de_season")
        months = seasons[season]

        if season == "Winter":
            prev_year = year - 1
            winter_label = f"Winter {prev_year}/{str(year)[-2:]}"
            try:
                prev_raw = load_frauenhofer(prev_year) if data_source == "Frauenhofer" else load_smard(prev_year)
                prev_df, _, _ = _prepare_df(prev_raw, target_capacity_gw, load_forecast_mwh, df_cap, prev_year)
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
        selected_month = st.selectbox("Month", list(month_names.keys()), key="de_month")
        plot_month_view(df, month_names[selected_month])

    else:  # Day
        day = st.date_input("Day", value=df["timestamp"].min().date(), key="de_day")
        plot_day_view(df, day)

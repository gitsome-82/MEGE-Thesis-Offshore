import streamlit as st
import pandas as pd
import calendar
import os
import pathlib
import plotly.express as px
import plotly.graph_objects as go

# Base data directory (relative to this script → works on any machine / Streamlit Cloud)
DATA_DIR = str(pathlib.Path(__file__).resolve().parent.parent / "DATA" / "Germany Data")

# Compact metric styling (reduces oversized default font)
st.markdown("""
<style>
[data-testid="stMetricValue"] > div { font-size: 1.1rem !important; }
[data-testid="stMetricLabel"] { font-size: 0.75rem !important; }
</style>
""", unsafe_allow_html=True)

# Define meteorological seasons (DWD / WMO standard)
seasons = {
    "Winter": [12, 1, 2],
    "Spring": [3, 4, 5],
    "Summer": [6, 7, 8],
    "Autumn": [9, 10, 11]
}


def parse_smard_timestamp(series):
    timestamps = pd.to_datetime(series, format='%b %d, %Y %I:%M %p', errors='coerce')
    missing = timestamps.isna()
    if missing.any():
        timestamps.loc[missing] = pd.to_datetime(series[missing], format='%b-%d, %Y %I:%M %p', errors='coerce')
    return timestamps


def parse_smard_numeric(series):
    return pd.to_numeric(series.astype(str).str.replace(',', '', regex=False), errors='coerce')

# --- Data loading functions (cached for performance) ---

@st.cache_data
def load_frauenhofer(year):
    path = f"{DATA_DIR}/Frauenhofer data/energy-charts_Public_net_electricity_generation_in_Germany_in_{year} MW.csv"
    df = pd.read_csv(path, skiprows=[1])
    df["timestamp"] = pd.to_datetime(df["Date (GMT+1)"], format="ISO8601", utc=True)
    df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["Wind offshore"] = pd.to_numeric(df["Wind offshore"], errors='coerce')
    df["Load"] = pd.to_numeric(df["Load"], errors='coerce')
    df = df.rename(columns={"Wind offshore": "offshore_mw", "Load": "load_mw"})
    df = df[["timestamp", "offshore_mw", "load_mw"]]
    df["hour"] = df["timestamp"].dt.floor("h")
    df_hourly = df.groupby("hour").agg({
        "offshore_mw": lambda x: (x * 0.25).sum(),
        "load_mw": lambda x: (x * 0.25).sum()
    }).reset_index()
    df_hourly = df_hourly.rename(columns={"hour": "timestamp", "offshore_mw": "generation_mwh", "load_mw": "load_mwh"})
    df_hourly = df_hourly[df_hourly["timestamp"].dt.year == year]
    return df_hourly

@st.cache_data
def load_smard_combined():
    """Load entire combined SMARD dataset (cached)"""
    gen_path = f"{DATA_DIR}/SMARD data/SMARD Actual_generation_202201010000_202604140100_Hour.csv"
    load_path = f"{DATA_DIR}/SMARD data/SMARD Actual_consumption_202201010000_202604140100_Hour.csv"

    gen_df = pd.read_csv(gen_path, sep=';')
    gen_df['timestamp'] = parse_smard_timestamp(gen_df['Start date'])
    gen_col = next((c for c in gen_df.columns if c.startswith("Wind offshore")), None)
    gen_df["generation_mwh"] = parse_smard_numeric(gen_df[gen_col])

    load_df = pd.read_csv(load_path, sep=';')
    load_df['timestamp'] = parse_smard_timestamp(load_df['Start date'])
    load_col = next((c for c in load_df.columns if c.startswith("grid load")), None)
    load_df["load_mwh"] = parse_smard_numeric(load_df[load_col])

    merged = pd.merge(gen_df[["timestamp", "generation_mwh"]], load_df[["timestamp", "load_mwh"]], on="timestamp")
    return merged.dropna(subset=["timestamp", "generation_mwh", "load_mwh"])

def load_smard(year):
    all_df = load_smard_combined()
    return all_df[all_df["timestamp"].dt.year == year].copy()

@st.cache_data
def load_capacity_all():
    """Load all monthly offshore capacity data"""
    capacity_path = f"{DATA_DIR}/Frauenhofer data/energy-charts_Net_installed_electricity_generation_capacity_in_Germany.csv"
    df_cap = pd.read_csv(capacity_path, skiprows=[1])
    df_cap[["month_str", "year_str"]] = df_cap["Month.Year"].astype(str).str.split(".", expand=True)
    df_cap["month_num"] = pd.to_numeric(df_cap["month_str"], errors='coerce').astype(int)
    df_cap["year_num"] = pd.to_numeric(df_cap["year_str"], errors='coerce').astype(int)
    df_cap["Wind offshore"] = pd.to_numeric(df_cap["Wind offshore"], errors='coerce')
    return df_cap

def get_monthly_capacity(df_cap, year):
    """Get dict of {month: capacity_gw} for a given year"""
    year_data = df_cap[df_cap["year_num"] == year][["month_num", "Wind offshore"]].dropna()
    if len(year_data) > 0:
        return {int(m): float(c) for m, c in zip(year_data["month_num"], year_data["Wind offshore"])}
    return None

def scale_generation(df, target_capacity_gw, df_cap):
    """Scale generation using actual monthly installed capacity per row's year+month"""
    # Build vectorized capacity lookup: (year, month) -> capacity_gw
    cap_lookup = {
        (int(r["year_num"]), int(r["month_num"])): float(r["Wind offshore"])
        for _, r in df_cap.dropna(subset=["Wind offshore"]).iterrows()
    }
    keys = list(zip(df["timestamp"].dt.year, df["timestamp"].dt.month))
    cap_series = pd.Series([cap_lookup.get(k, 8.35) for k in keys], index=df.index)
    df["gen_scaled"] = df["generation_mwh"].fillna(0) * (target_capacity_gw / cap_series)
    return df

# --- Main app ---

st.title("Offshore Wind Generation vs Load Analysis - Germany")

data_source = st.selectbox("Data Source", ["SMARD", "Frauenhofer"])
year = st.selectbox("Year", [2022, 2023, 2024, 2025, 2026])

# Load main year data
if data_source == "Frauenhofer":
    df = load_frauenhofer(year)
else:
    df = load_smard(year)

if df.empty:
    st.error(f"No valid {data_source} data was loaded for {year}.")
    st.stop()

df["month"] = df["timestamp"].dt.month.astype(int)
df["day"] = df["timestamp"].dt.date
df["hour"] = df["timestamp"].dt.hour

# Load capacity data
df_cap = load_capacity_all()
monthly_capacity_gw = get_monthly_capacity(df_cap, year)
if monthly_capacity_gw:
    st.success(f"Loaded {len(monthly_capacity_gw)} months of capacity data for {year}")
else:
    st.warning(f"No capacity data found for year {year}")

# Controls
col1, col2 = st.columns(2)
with col1:
    target_capacity_gw = st.slider("Target offshore capacity (GW)", 0.0, 80.0, 9.2, 0.1)
with col2:
    load_forecast_twh = st.slider("Forecast annual load (TWh)", 0, 1000, 400, 5)
    load_forecast_mwh = load_forecast_twh * 1_000_000

# Scale generation (uses each row's year+month for correct capacity lookup)
df = scale_generation(df, target_capacity_gw, df_cap)

# Scale load
sample_annual_load = df["load_mwh"].sum()
if sample_annual_load <= 0:
    st.error(f"Loaded {data_source} load data for {year}, but the annual load summed to zero. Check the source CSV formatting.")
    st.stop()

load_scale = load_forecast_mwh / sample_annual_load if sample_annual_load > 0 else 1
df["load_scaled"] = df["load_mwh"] * load_scale
df["load_met"] = df[["gen_scaled", "load_scaled"]].min(axis=1)
df["surplus"] = (df["gen_scaled"] - df["load_scaled"]).clip(lower=0)
df["unmet"] = (df["load_scaled"] - df["gen_scaled"]).clip(lower=0)

# Metrics
total_load = df["load_scaled"].sum()
total_gen = df["gen_scaled"].sum()
total_met = df["load_met"].sum()
coverage_pct = 100 * total_met / total_load if total_load else 0

col_m1, col_m2, col_m3 = st.columns(3)
col_m1.metric("Annual load (TWh)", f"{total_load / 1e6:.1f}")
col_m2.metric("Annual generation (TWh)", f"{total_gen / 1e6:.1f}")
col_m3.metric("Coverage (%)", f"{coverage_pct:.1f}")

# --- Summary box: annual totals, capacity factors, peak values ---
hours_in_period = len(df)
capacity_factor = (total_gen / (target_capacity_gw * 1e3 * hours_in_period) * 100) if (target_capacity_gw > 0 and hours_in_period > 0) else 0
peak_gen = df["gen_scaled"].max()
peak_load = df["load_scaled"].max()
peak_surplus = df["surplus"].max()
peak_unmet = df["unmet"].max()
total_surplus = df["surplus"].sum()
full_load_hours = (total_gen / (target_capacity_gw * 1e3)) if target_capacity_gw > 0 else 0

with st.expander("📊 Annual Summary", expanded=True):
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Capacity Factor", f"{capacity_factor:.1f} %")
    s2.metric("Full-Load Hours", f"{full_load_hours:,.0f} h")
    s3.metric("Total Surplus", f"{total_surplus / 1e6:.2f} TWh")
    s4.metric("Total Unmet Load", f"{(total_load - total_met) / 1e6:.2f} TWh")

    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Peak Generation", f"{peak_gen / 1000:.2f} GW")
    p2.metric("Peak Load", f"{peak_load / 1000:.2f} GW")
    p3.metric("Peak Surplus", f"{peak_surplus / 1000:.2f} GW")
    p4.metric("Peak Unmet", f"{peak_unmet / 1000:.2f} GW")

# View selection
view = st.selectbox("View", ["Year", "Season", "Month", "Day"])

if view == "Year":
    monthly = df.resample("ME", on="timestamp").sum(numeric_only=True).reset_index()
    monthly["load_met_gwh"] = monthly["load_met"] / 1000
    monthly["unmet_gwh"] = monthly["unmet"] / 1000
    monthly["month_label"] = monthly["timestamp"].dt.strftime("%b %Y")
    monthly["coverage_pct"] = 100 * monthly["load_met"] / monthly["load_scaled"]

    # Pie chart
    annual_cov = {"Load Met": total_met / 1e6, "Unmet Load": (total_load - total_met) / 1e6}
    fig_pie = px.pie(names=list(annual_cov.keys()), values=list(annual_cov.values()),
                     title="Annual Load Coverage (TWh)")
    fig_pie.update_traces(hovertemplate="<b>%{label}</b><br>%{value:.2f} TWh<extra></extra>")
    st.plotly_chart(fig_pie, width='stretch')

    # Stacked bar: Load Met + Unmet
    fig_stack = go.Figure()
    fig_stack.add_trace(go.Bar(x=monthly["month_label"], y=monthly["load_met_gwh"],
                               name="Load Met by Offshore", marker_color="#2ca02c"))
    fig_stack.add_trace(go.Bar(x=monthly["month_label"], y=monthly["unmet_gwh"],
                               name="Unmet Load", marker_color="#d3d3d3"))
    fig_stack.update_layout(barmode="stack", title="Monthly Load Coverage",
                            yaxis_title="Energy (GWh)", xaxis_title="Month")
    st.plotly_chart(fig_stack, width='stretch')

    # 100% stacked coverage bar
    fig_pct = go.Figure()
    fig_pct.add_trace(go.Bar(x=monthly["month_label"], y=monthly["coverage_pct"],
                             name="Covered by Offshore", marker_color="#2ca02c"))
    fig_pct.add_trace(go.Bar(x=monthly["month_label"], y=100 - monthly["coverage_pct"],
                             name="Unmet", marker_color="#d3d3d3"))
    fig_pct.update_layout(barmode="stack", title="Monthly Offshore Wind Coverage (%)",
                          yaxis=dict(title="Coverage (%)", range=[0, 100]), xaxis_title="Month")
    st.plotly_chart(fig_pct, width='stretch')

elif view == "Season":
    season = st.selectbox("Season", list(seasons.keys()))
    months = seasons[season]

    if season == "Winter":
        # Winter = Dec(year-1) + Jan(year) + Feb(year)
        winter_label = f"Winter {year-1}/{str(year)[-2:]}"
        prev_year = year - 1
        try:
            if data_source == "Frauenhofer":
                prev_df = load_frauenhofer(prev_year)
            else:
                prev_df = load_smard(prev_year)
            prev_df["month"] = prev_df["timestamp"].dt.month.astype(int)
            prev_df["day"] = prev_df["timestamp"].dt.date
            prev_df["hour"] = prev_df["timestamp"].dt.hour
            dec_df = prev_df[prev_df["month"] == 12].copy()

            # Scale December with prev year's capacity
            dec_df = scale_generation(dec_df, target_capacity_gw, df_cap)
            dec_df["load_scaled"] = dec_df["load_mwh"] * load_scale
            dec_df["load_met"] = dec_df[["gen_scaled", "load_scaled"]].min(axis=1)
            dec_df["surplus"] = (dec_df["gen_scaled"] - dec_df["load_scaled"]).clip(lower=0)
            dec_df["unmet"] = (dec_df["load_scaled"] - dec_df["gen_scaled"]).clip(lower=0)

            jan_feb = df[df["month"].isin([1, 2])]
            season_df = pd.concat([dec_df, jan_feb]).sort_values("timestamp")
        except Exception as e:
            st.warning(f"Could not load {prev_year} December data: {e}. Showing Jan-Feb only.")
            season_df = df[df["month"].isin([1, 2])].sort_values("timestamp")
            winter_label = f"Winter {year} (Jan-Feb only)"
    else:
        season_df = df[df["month"].isin(months)].sort_values("timestamp")
        winter_label = None

    season_name = winter_label if season == "Winter" else season

    # Pie chart
    season_met = season_df["load_met"].sum()
    season_load = season_df["load_scaled"].sum()
    season_cov = {"Load Met": season_met / 1e6, "Unmet Load": (season_load - season_met) / 1e6}
    fig_pie = px.pie(names=list(season_cov.keys()), values=list(season_cov.values()),
                     title=f"{season_name} Load Coverage (TWh)")
    fig_pie.update_traces(hovertemplate="<b>%{label}</b><br>%{value:.2f} TWh<extra></extra>")
    st.plotly_chart(fig_pie, width='stretch')

    # Line chart
    fig = px.line(season_df, x="timestamp", y=["gen_scaled", "load_scaled"],
                  title=f"{season_name} Generation vs Load")
    fig.update_yaxes(title_text="Power (MWh/h)")
    fig.update_xaxes(range=[season_df["timestamp"].min(), season_df["timestamp"].max()])
    fig.for_each_trace(lambda t: t.update(name="Generation" if t.name == "gen_scaled" else "Load"))
    st.plotly_chart(fig, width='stretch')

    # Daily % coverage
    season_daily = season_df.groupby("day").sum(numeric_only=True).reset_index()
    season_daily["coverage_pct"] = 100 * season_daily["load_met"] / season_daily["load_scaled"]
    fig_pct = go.Figure()
    fig_pct.add_trace(go.Bar(x=season_daily["day"], y=season_daily["coverage_pct"],
                             name="Covered by Offshore", marker_color="#2ca02c"))
    fig_pct.add_trace(go.Bar(x=season_daily["day"], y=100 - season_daily["coverage_pct"],
                             name="Unmet", marker_color="#d3d3d3"))
    fig_pct.update_layout(barmode="stack", title=f"{season_name} Daily Coverage (%)",
                          yaxis=dict(title="Coverage (%)", range=[0, 100]), xaxis_title="Day")
    st.plotly_chart(fig_pct, width='stretch')

elif view == "Month":
    month_names = {calendar.month_name[i]: i for i in range(1, 13)}
    selected_month = st.selectbox("Month", list(month_names.keys()))
    month_num = month_names[selected_month]
    month_df = df[df["month"] == month_num]

    daily = month_df.groupby("day").sum(numeric_only=True).reset_index()
    daily["load_met_gwh"] = daily["load_met"] / 1000
    daily["unmet_gwh"] = daily["unmet"] / 1000
    daily["coverage_pct"] = 100 * daily["load_met"] / daily["load_scaled"]

    # Pie chart
    month_met = month_df["load_met"].sum()
    month_load = month_df["load_scaled"].sum()
    month_cov = {"Load Met": month_met / 1e6, "Unmet Load": (month_load - month_met) / 1e6}
    fig_pie = px.pie(names=list(month_cov.keys()), values=list(month_cov.values()),
                     title=f"{calendar.month_name[month_num]} Load Coverage (TWh)")
    fig_pie.update_traces(hovertemplate="<b>%{label}</b><br>%{value:.3f} TWh<extra></extra>")
    st.plotly_chart(fig_pie, width='stretch')

    # Stacked bar: Load Met + Unmet
    fig_stack = go.Figure()
    fig_stack.add_trace(go.Bar(x=daily["day"], y=daily["load_met_gwh"],
                               name="Load Met by Offshore", marker_color="#2ca02c"))
    fig_stack.add_trace(go.Bar(x=daily["day"], y=daily["unmet_gwh"],
                               name="Unmet Load", marker_color="#d3d3d3"))
    fig_stack.update_layout(barmode="stack", title=f"{calendar.month_name[month_num]} Daily Load Coverage",
                            yaxis_title="Energy (GWh)", xaxis_title="Day")
    st.plotly_chart(fig_stack, width='stretch')

    # 100% stacked coverage bar
    fig_pct = go.Figure()
    fig_pct.add_trace(go.Bar(x=daily["day"], y=daily["coverage_pct"],
                             name="Covered by Offshore", marker_color="#2ca02c"))
    fig_pct.add_trace(go.Bar(x=daily["day"], y=100 - daily["coverage_pct"],
                             name="Unmet", marker_color="#d3d3d3"))
    fig_pct.update_layout(barmode="stack", title=f"{calendar.month_name[month_num]} Daily Coverage (%)",
                          yaxis=dict(title="Coverage (%)", range=[0, 100]), xaxis_title="Day")
    st.plotly_chart(fig_pct, width='stretch')

else:  # Day
    day = st.date_input("Day", value=df["timestamp"].min().date())
    day_df = df[df["day"] == day]

    # Pie chart (convert MWh to GWh)
    day_met_gwh = day_df["load_met"].sum() / 1000
    day_load_gwh = day_df["load_scaled"].sum() / 1000
    day_cov = {"Load Met": day_met_gwh, "Unmet Load": day_load_gwh - day_met_gwh}
    fig_pie = px.pie(names=list(day_cov.keys()), values=list(day_cov.values()),
                     title=f"{day} Load Coverage (GWh)")
    fig_pie.update_traces(hovertemplate="<b>%{label}</b><br>%{value:.2f} GWh<extra></extra>")
    st.plotly_chart(fig_pie, width='stretch')

    # Stacked bar: Load Met + Unmet (hourly, MWh)
    fig_stack = go.Figure()
    fig_stack.add_trace(go.Bar(x=day_df["hour"], y=day_df["load_met"],
                               name="Load Met by Offshore", marker_color="#2ca02c"))
    fig_stack.add_trace(go.Bar(x=day_df["hour"], y=day_df["unmet"],
                               name="Unmet Load", marker_color="#d3d3d3"))
    fig_stack.update_layout(barmode="stack", title=f"{day} Hourly Load Coverage",
                            yaxis_title="Energy (MWh)", xaxis_title="Hour")
    st.plotly_chart(fig_stack, width='stretch')

    # 100% stacked coverage bar (hourly)
    day_pct = day_df.copy()
    day_pct["coverage_pct"] = 100 * day_pct["load_met"] / day_pct["load_scaled"]
    fig_pct = go.Figure()
    fig_pct.add_trace(go.Bar(x=day_pct["hour"], y=day_pct["coverage_pct"],
                             name="Covered by Offshore", marker_color="#2ca02c"))
    fig_pct.add_trace(go.Bar(x=day_pct["hour"], y=100 - day_pct["coverage_pct"],
                             name="Unmet", marker_color="#d3d3d3"))
    fig_pct.update_layout(barmode="stack", title=f"{day} Hourly Coverage (%)",
                          yaxis=dict(title="Coverage (%)", range=[0, 100]), xaxis_title="Hour")
    st.plotly_chart(fig_pct, width='stretch')
# Run command (from repo root):
# .venv\Scripts\streamlit run "3. system model/3.2 system model v2/app/streamlit_app.py"

"""
Streamlit dashboard for the offshore wind + H2 storage control model.

Calls the scenario runner and displays the supervisor's hourly output table
plus summary metrics and plots.
"""
# --- Ensure all required packages are installed (auto-install if missing) ---
import subprocess
import sys

_required = ["streamlit", "pandas", "plotly"]
for _pkg in _required:
    try:
        __import__(_pkg)
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', _pkg])

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import pathlib

# Ensure src/ is importable when running `streamlit run app/streamlit_app.py`
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src.utils.config import ScenarioConfig
from src.scenarios.run_scenario import run_scenario

st.set_page_config(page_title="Offshore Wind + H₂ Storage Model", layout="wide")
st.title("Offshore Wind + H₂ Storage Control Model")


# ── Sidebar: scenario parameters ─────────────────────────────────────────
st.sidebar.header("Scenario Parameters")
country = st.sidebar.selectbox("Country", ["Germany", "Portugal"])

if country == "Germany":
    data_source = st.sidebar.selectbox("Data Source", ["SMARD", "Frauenhofer"])
    available_years = [2022, 2023, 2024, 2025]
else:
    data_source = "ENTSO-E"
    st.sidebar.info("Data source: ENTSO-E (Portugal)")
    available_years = [2022, 2023, 2024, 2025]

year = st.sidebar.selectbox("Year", available_years)

st.sidebar.subheader("Wind Farm")
target_farm_mw = st.sidebar.slider("Target farm capacity (MW)", 50, 5000, 500, 50)
derate = st.sidebar.slider("Derate factor", 0.5, 1.0, 1.0, 0.01)

st.sidebar.subheader("Electrolyser")
elec_mw = st.sidebar.slider("Electrolyser capacity (MW)", 0, 1000, 100, 10)
elec_eff = st.sidebar.slider("Specific consumption (kWh/kg)", 40.0, 70.0, 55.0, 1.0)

st.sidebar.subheader("H₂ Tank")
tank_kg = st.sidebar.slider("Tank capacity (kg)", 0, 100_000, 10_000, 1_000)
h2_offtake = st.sidebar.slider("H₂ daily offtake (kg/day)", 0, 20_000, 2_000, 100)

st.sidebar.subheader("Economics")
h2_price = st.sidebar.slider("H₂ selling price (EUR/kg)", 1.0, 15.0, 5.0, 0.5)
opex = st.sidebar.slider("Operating cost (EUR/MWh)", 0.0, 50.0, 23.0, 1.0)

# ── Build config ──────────────────────────────────────────────────────────
cfg = ScenarioConfig(    country=country,    data_source=data_source,
    year=year,
    target_farm_capacity_mw=target_farm_mw,
    derate_factor=derate,
    electrolyser_capacity_mw=elec_mw,
    electrolyser_efficiency_kwh_per_kg=elec_eff,
    tank_capacity_kg=tank_kg,
    h2_daily_offtake_kg=h2_offtake,
    h2_selling_price_eur_per_kg=h2_price,
    opex_eur_per_mwh=opex,
)


# ── Run scenario (cached) ────────────────────────────────────────────────
@st.cache_data
def cached_run(cfg_dict):
    c = ScenarioConfig(**cfg_dict)
    return run_scenario(c)

from dataclasses import asdict
hourly_df, summary = cached_run(asdict(cfg))


# ── Summary metrics ──────────────────────────────────────────────────────
st.header("Annual Summary")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Generation (GWh)", f"{summary['total_generation_mwh']/1e3:,.0f}")
c2.metric("To Grid (GWh)", f"{summary['total_to_grid_mwh']/1e3:,.0f}")
c3.metric("H₂ Produced (t)", f"{summary['total_h2_produced_kg']/1e3:,.1f}")
c4.metric("Curtailed (GWh)", f"{summary['total_curtailed_mwh']/1e3:,.0f}")
c5.metric("Curtailment Rate", f"{summary['curtailment_rate_pct']:.1f}%")

r1, r2, r3, r4 = st.columns(4)
r1.metric("Grid Revenue (M€)", f"{summary['total_grid_revenue_eur']/1e6:,.2f}")
r2.metric("H₂ Revenue (M€)", f"{summary['total_h2_revenue_eur']/1e6:,.2f}")
r3.metric("Total Revenue (M€)", f"{summary['total_revenue_eur']/1e6:,.2f}")
r4.metric("PV of Operating Profit (M€)", f"{summary['npv_eur']/1e6:,.2f}",
          help="Present value of this year's profit × 25yr annuity factor. No CAPEX included — not a true project NPV.")


# ── Hourly output table (supervisor's format) ────────────────────────────
st.header("Hourly Output Table")
display_cols = [
    "timestamp", "action", "energy_flux_battery_kwh",
    "h2_produced_kg", "to_grid_mwh", "curtailed_mwh",
    "ancillary_revenue_eur", "total_revenue_eur", "profit_eur",
]
st.dataframe(hourly_df[display_cols], use_container_width=True, height=400)


# ── Plots ─────────────────────────────────────────────────────────────────
st.header("Dispatch Overview")

# Time-range selector
min_date = hourly_df["timestamp"].min().date()
max_date = hourly_df["timestamp"].max().date()
date_range = st.date_input("Date range", value=(min_date, max_date),
                           min_value=min_date, max_value=max_date)
if len(date_range) == 2:
    mask = (hourly_df["timestamp"].dt.date >= date_range[0]) & \
           (hourly_df["timestamp"].dt.date <= date_range[1])
    plot_df = hourly_df[mask]
else:
    plot_df = hourly_df

# Stacked area: generation allocation
fig_alloc = go.Figure()
fig_alloc.add_trace(go.Scatter(
    x=plot_df["timestamp"], y=plot_df["to_grid_mwh"],
    stackgroup='one', name="To Grid", line=dict(width=0)))
fig_alloc.add_trace(go.Scatter(
    x=plot_df["timestamp"], y=plot_df["to_electrolyser_mwh"],
    stackgroup='one', name="To Electrolyser", line=dict(width=0)))
fig_alloc.add_trace(go.Scatter(
    x=plot_df["timestamp"], y=plot_df["curtailed_mwh"],
    stackgroup='one', name="Curtailed", line=dict(width=0)))
fig_alloc.update_layout(title="Generation Allocation", yaxis_title="MWh/h")
st.plotly_chart(fig_alloc, use_container_width=True)

# Tank SOC
fig_soc = px.line(plot_df, x="timestamp", y="tank_soc_kg",
                  title="H₂ Tank State of Charge")
fig_soc.update_yaxes(title_text="kg H₂")
st.plotly_chart(fig_soc, use_container_width=True)

# Cumulative revenue
plot_df = plot_df.copy()
plot_df["cumulative_revenue"] = plot_df["total_revenue_eur"].cumsum()
fig_rev = px.line(plot_df, x="timestamp", y="cumulative_revenue",
                  title="Cumulative Revenue")
fig_rev.update_yaxes(title_text="EUR")
st.plotly_chart(fig_rev, use_container_width=True)

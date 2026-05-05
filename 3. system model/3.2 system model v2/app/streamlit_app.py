# Run command (from repo root):
# .venv\Scripts\streamlit run "3. system model/3.2 system model v2/app/streamlit_app.py"

"""
Streamlit dashboard for the offshore wind + H2 storage control model.

Calls the scenario runner and displays the hourly output table
plus summary metrics and plots.
"""
# --- Ensure all required packages are installed (auto-install if missing) ---
import subprocess
import sys

_required = ["streamlit", "pandas", "plotly", "folium", "streamlit_folium"]
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
import folium
from streamlit_folium import st_folium

# Ensure src/ is importable when running `streamlit run app/streamlit_app.py`
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src.scenarios.config import ScenarioConfig
from src.scenarios.run_scenario import run_scenario
from src.scenarios.library import SCENARIOS, get_scenario

st.set_page_config(page_title="Offshore Wind + H₂ Storage Model", layout="wide")
st.title("Offshore Wind + H₂ Storage Control Model")

# Make summary metrics less visually dominant.
st.markdown(
    """
    <style>
    div[data-testid="stMetricValue"] {
        font-size: 1.5rem;
    }
    div[data-testid="stMetricLabel"] {
        font-size: 0.85rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ── Sidebar: scenario parameters ─────────────────────────────────────────
st.sidebar.header("Scenario Parameters")

# ── Preset loader ─────────────────────────────────────────────────────────
preset_options = ["— custom —"] + sorted(SCENARIOS.keys())
if "last_preset" not in st.session_state:
    st.session_state["last_preset"] = "— custom —"

preset = st.sidebar.selectbox("Load preset scenario", preset_options, index=0)

if preset != "— custom —" and preset != st.session_state["last_preset"]:
    _p = get_scenario(preset)
    st.session_state["preset_project"]      = _p.wf_project
    st.session_state["preset_year"]         = _p.year
    st.session_state["preset_farm_mw"]      = float(_p.target_farm_capacity_mw)
    st.session_state["preset_derate"]       = float(_p.derate_factor)
    st.session_state["preset_stor_type"]    = _p.storage_type
    st.session_state["preset_stor_pct"]     = float(_p.storage_size_pct)
    st.session_state["preset_objective"]    = _p.objective
    st.session_state["preset_ancillary"]    = bool(_p.ancillary_services)
    st.session_state["preset_wind_scen"]    = _p.wind_scenario
    st.session_state["preset_elec_eff"]     = float(_p.electrolyser_efficiency_kwh_per_kg)
    st.session_state["preset_tank_kg"]      = float(_p.tank_capacity_kg)
    st.session_state["preset_h2_offtake"]   = float(_p.h2_daily_offtake_kg)
    st.session_state["preset_h2_price"]     = float(_p.h2_selling_price_eur_per_kg)
    st.session_state["preset_opex"]         = float(_p.opex_eur_per_mwh)
    st.session_state["preset_use_lp"]       = bool(_p.use_optimised_dispatch)
    st.session_state["last_preset"]         = preset


def _ss(key, fallback):
    """Return session-state override if present (from preset), else fallback."""
    return st.session_state.get(key, fallback)


# ── Project / Site ────────────────────────────────────────────────────────
st.sidebar.subheader("Project")

WF_PROJECTS = [
    "Germany - Alpha Ventus (North Sea)",
    "Portugal - WindFloat Atlantic (Atlantic)",
    "England - East Anglia (North Sea)",
]

# Map project → (country, data_source)
_PROJECT_META = {
    "Germany - Alpha Ventus (North Sea)":        ("Germany",  "SMARD"),
    "Portugal - WindFloat Atlantic (Atlantic)":  ("Portugal", "ENTSO-E"),
    "England - East Anglia (North Sea)":         ("England",  "ENTSO-E"),
}

wf_project = st.sidebar.selectbox(
    "Wind Farm Project",
    WF_PROJECTS,
    index=WF_PROJECTS.index(_ss("preset_project", WF_PROJECTS[0])),
)
country, data_source = _PROJECT_META[wf_project]

if country == "Germany":
    data_source = st.sidebar.selectbox("Data Source", ["SMARD", "Frauenhofer"])

available_years = [2022, 2023, 2024, 2025]
_def_year = _ss("preset_year", 2023)
year = st.sidebar.selectbox(
    "Year", available_years,
    index=available_years.index(_def_year) if _def_year in available_years else 0,
)

# ── Wind Farm ─────────────────────────────────────────────────────────────
st.sidebar.subheader("Wind Farm")
target_farm_mw = st.sidebar.number_input(
    "Farm capacity (MW)", min_value=25.0, max_value=25000.0,
    value=_ss("preset_farm_mw", 500.0), step=50.0,
)
derate = st.sidebar.slider("Derate factor", 0.5, 1.0, _ss("preset_derate", 1.0), 0.01)

# ── Storage ───────────────────────────────────────────────────────────────
st.sidebar.subheader("Storage")

STORAGE_TYPES = ["hydrogen", "battery", "hybrid"]
storage_type = st.sidebar.selectbox(
    "Storage Type",
    STORAGE_TYPES,
    index=STORAGE_TYPES.index(_ss("preset_stor_type", "hydrogen")),
)
if storage_type in ("battery", "hybrid"):
    st.sidebar.warning("⚠️ NOTE — PLACEHOLDER: Battery dispatch not yet configured.")

STORAGE_SIZE_OPTS = [5, 10, 20, 30, 50]
_def_pct = float(_ss("preset_stor_pct", 20.0))
_pct_idx = STORAGE_SIZE_OPTS.index(int(_def_pct)) if int(_def_pct) in STORAGE_SIZE_OPTS else 2
storage_size_pct = st.sidebar.selectbox(
    "Electrolyser/Battery Capacity (% of farm MW)",
    STORAGE_SIZE_OPTS,
    index=_pct_idx,
    help="Power capacity only. This is converted to MW for the electrolyser/battery rating, not H2 tank size.",
)

# Derived power capacity in MW used by electrolyser and/or battery.
storage_mw = float(target_farm_mw) * float(storage_size_pct) / 100.0
st.sidebar.caption(f"→ Rated power capacity: {storage_mw:.0f} MW")

# ── Objective ─────────────────────────────────────────────────────────────
st.sidebar.subheader("Objective")
OBJECTIVES = ["max_profit", "max_h2", "max_energy_stor"]
OBJ_LABELS  = ["Max Profit", "Max H₂ Production", "Max Energy Storage"]
_def_obj = _ss("preset_objective", "max_profit")
_obj_idx = OBJECTIVES.index(_def_obj) if _def_obj in OBJECTIVES else 0
objective = st.sidebar.selectbox(
    "Optimisation Objective (rule-based)",
    OBJ_LABELS,
    index=_obj_idx,
    help="Controls dispatch priority when LP is OFF. When LP is ON, the LP objective takes precedence.",
)
objective_key = OBJECTIVES[OBJ_LABELS.index(objective)]
if objective_key == "max_energy_stor":
    st.sidebar.warning("⚠️ NOTE — PLACEHOLDER: Max Energy Storage objective not yet configured.")

# ── Ancillary Grid Services ───────────────────────────────────────────────
ancillary = st.sidebar.selectbox(
    "Ancillary Grid Services",
    ["No", "Yes"],
    index=1 if _ss("preset_ancillary", False) else 0,
)
ancillary_services = ancillary == "Yes"
if ancillary_services:
    st.sidebar.warning("⚠️ NOTE — PLACEHOLDER: Ancillary revenue model not yet configured.")

# ── Wind Scenario ─────────────────────────────────────────────────────────
WIND_SCENARIOS = ["ncep", "low_wind", "high_wind"]
WIND_LABELS    = ["NCEP (reference)", "Low Wind", "High Wind"]
_def_ws = _ss("preset_wind_scen", "ncep")
_ws_idx = WIND_SCENARIOS.index(_def_ws) if _def_ws in WIND_SCENARIOS else 0
wind_scenario_label = st.sidebar.selectbox("Wind Scenario", WIND_LABELS, index=_ws_idx)
wind_scenario = WIND_SCENARIOS[WIND_LABELS.index(wind_scenario_label)]
if wind_scenario != "ncep":
    st.sidebar.warning("⚠️ NOTE — PLACEHOLDER: Wind scenario scaling not yet configured.")

# ── H₂ System ─────────────────────────────────────────────────────────────
if storage_type in ("hydrogen", "hybrid"):
    st.sidebar.subheader("H₂ System")
    elec_eff = st.sidebar.slider(
        "Electrolyser efficiency (kWh/kg)", 40.0, 70.0,
        _ss("preset_elec_eff", 55.0), 1.0,
    )
    tank_kg = st.sidebar.number_input(
        "Tank capacity (kg)", min_value=0.0, max_value=1_000_000.0,
        value=_ss("preset_tank_kg", 10_000.0), step=1000.0,
    )
    h2_offtake = st.sidebar.number_input(
        "H₂ daily offtake (kg/day)", min_value=0.0, max_value=100_000.0,
        value=_ss("preset_h2_offtake", 2_000.0), step=500.0,
    )
    h2_price = st.sidebar.number_input(
        "H₂ selling price (EUR/kg)", min_value=0.0, max_value=20.0,
        value=_ss("preset_h2_price", 5.0), step=0.5,
        help="Typical green H₂ range: 2–10 EUR/kg",
    )
else:
    elec_eff   = 55.0
    tank_kg    = 0.0
    h2_offtake = 0.0
    h2_price   = 5.0

# ── Economics ─────────────────────────────────────────────────────────────
st.sidebar.subheader("Economics")
opex = st.sidebar.number_input(
    "Operating cost (EUR/MWh)", min_value=0.0, max_value=100.0,
    value=_ss("preset_opex", 23.0), step=1.0,
)

# ── Dispatch Engine ───────────────────────────────────────────────────────
st.sidebar.subheader("Dispatch")
use_lp = st.sidebar.checkbox(
    "Use LP optimiser",
    value=_ss("preset_use_lp", False),
    help="LP solves 24h window at once (slower but optimal). Rule-based uses greedy priority logic.",
)
if use_lp:
    lp_obj = st.sidebar.radio("LP objective", ["revenue", "h2"], horizontal=True)
else:
    lp_obj = "revenue"

# Show which objective is actually active
st.sidebar.info(f"🎯 **Active dispatch:** {'LP optimised (objective: ' + lp_obj + ')' if use_lp else 'Rule-based (' + OBJ_LABELS[OBJECTIVES.index(objective_key)] + ')'}")

# ── Build config ──────────────────────────────────────────────────────────
cfg = ScenarioConfig(
    wf_project=wf_project,
    country=country,
    data_source=data_source,
    year=year,
    target_farm_capacity_mw=float(target_farm_mw),
    derate_factor=derate,
    storage_type=storage_type,
    storage_size_pct=float(storage_size_pct),
    objective=objective_key,
    ancillary_services=ancillary_services,
    wind_scenario=wind_scenario,
    electrolyser_capacity_mw=storage_mw if storage_type in ("hydrogen", "hybrid") else 0.0,
    electrolyser_efficiency_kwh_per_kg=elec_eff,
    tank_capacity_kg=float(tank_kg),
    h2_daily_offtake_kg=float(h2_offtake),
    h2_selling_price_eur_per_kg=float(h2_price),
    opex_eur_per_mwh=float(opex),
    prioritise_h2=(objective_key == "max_h2"),
    use_optimised_dispatch=use_lp,
    dispatch_objective=lp_obj,
    battery_capacity_mwh=storage_mw if storage_type in ("battery", "hybrid") else 0.0,
    battery_power_mw=storage_mw if storage_type in ("battery", "hybrid") else 0.0,
)


# ── Run scenario (cached) ────────────────────────────────────────────────
@st.cache_data
def cached_run(cfg_dict):
    c = ScenarioConfig(**cfg_dict)
    return run_scenario(c)

from dataclasses import asdict
hourly_df, summary = cached_run(asdict(cfg))

# ── Load prior year for winter season (if needed) ──────────────────────────
# To show proper winter (Dec from prior year + Jan/Feb from current year),
# run the full prior-year scenario so dispatch columns (tank_soc_kg etc.)
# are present in December too.
@st.cache_data
def load_prior_year_data(cfg_dict):
    """Run prior year's scenario and return just December dispatch results."""
    c = ScenarioConfig(**cfg_dict)
    prior_year = c.year - 1
    try:
        prior_cfg_dict = dict(cfg_dict)
        prior_cfg_dict["year"] = prior_year
        prior_hourly, _ = cached_run(prior_cfg_dict)
        prior_december = prior_hourly[prior_hourly["timestamp"].dt.month == 12].copy()
        return prior_december if not prior_december.empty else None
    except Exception:
        return None

prior_dec_df = load_prior_year_data(asdict(cfg))


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


# ── Project location map ──────────────────────────────────────────────────
_SITE_DATA = {
    "Germany - Alpha Ventus (North Sea)": {
        "lat": 54.011111, "lon": 6.607778,
        "name": "Alpha Ventus OWF",
        "info": "Alpha Ventus — Germany's first offshore wind farm<br>45 km north of Borkum<br>Installed: 60 MW (12 × 5 MW)",
    },
    "Portugal - WindFloat Atlantic (Atlantic)": {
        "lat": 41.6865, "lon": -9.0574,
        "name": "WindFloat Atlantic",
        "info": "WindFloat Atlantic — Portugal's first floating offshore wind farm<br>Viana do Castelo<br>Installed: 25.2 MW (3 × 8.4 MW)",
    },
    "England - East Anglia (North Sea)": {
        "lat": 52.9078, "lon": 2.6286,
        "name": "East Anglia ONE OWF",
        "info": "East Anglia ONE — Offshore wind farm, North Sea<br>Lowestoft, Suffolk<br>Installed: 714 MW (102 × 7 MW SWT-7.0-154)",
    },
}
_site = _SITE_DATA[wf_project]
if wf_project == "England - East Anglia (North Sea)":
    st.info("🚧 **Coming Soon** — England / East Anglia data integration is not yet configured. Results will not reflect this site.")

with st.expander(f"Project location — {_site['name']}", expanded=True):
    m = folium.Map(location=[_site['lat'], _site['lon']], zoom_start=8, tiles="CartoDB positron")
    folium.Marker(
        location=[_site['lat'], _site['lon']],
        popup=folium.Popup(_site['info'], max_width=280),
        tooltip=_site['name'],
        icon=folium.Icon(color="blue", icon="cloud", prefix="fa"),
    ).add_to(m)
    folium.Circle(
        location=[_site['lat'], _site['lon']],
        radius=5000,
        color="steelblue",
        fill=True,
        fill_opacity=0.15,
        tooltip="Approx. farm extent",
    ).add_to(m)
    st_folium(m, width=700, height=400, returned_objects=[])


# ── Hourly output table (supervisor's format) ────────────────────────────
with st.expander("Hourly Output Table", expanded=False):
    display_cols = [
        "timestamp", "action", "energy_flux_battery_kwh",
        "h2_produced_kg", "to_grid_mwh", "curtailed_mwh",
        "ancillary_revenue_eur", "total_revenue_eur", "profit_eur",
    ]
    st.dataframe(hourly_df[display_cols], use_container_width=True, height=400)


# ── Plots ─────────────────────────────────────────────────────────────────
st.header("Dispatch Overview")

# Time-range selector with presets
min_date = hourly_df["timestamp"].min().date()
max_date = hourly_df["timestamp"].max().date()

time_range_preset = st.selectbox(
    "View",
    ["Custom date range", "Full year", "Month", "Season", "Single day"],
    index=0,
)

if time_range_preset == "Full year":
    plot_df = hourly_df
elif time_range_preset == "Month":
    selected_month = st.select_slider(
        "Select month",
        options=range(1, 13),
        value=1,
        format_func=lambda m: ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m-1],
    )
    mask = hourly_df["timestamp"].dt.month == selected_month
    plot_df = hourly_df[mask]
elif time_range_preset == "Season":
    season_map = {
        "Winter": [12, 1, 2],
        "Spring": [3, 4, 5],
        "Summer": [6, 7, 8],
        "Autumn": [9, 10, 11],
    }
    selected_season = st.selectbox("Select season", list(season_map.keys()))
    
    if selected_season == "Winter" and prior_dec_df is not None:
        # Combine prior year's December with current year's Jan/Feb
        jan_feb = hourly_df[hourly_df["timestamp"].dt.month.isin([1, 2])]
        plot_df = pd.concat([prior_dec_df, jan_feb], ignore_index=False).sort_values("timestamp")
    else:
        # Fallback: just current year's Dec/Jan/Feb
        mask = hourly_df["timestamp"].dt.month.isin(season_map[selected_season])
        plot_df = hourly_df[mask]
elif time_range_preset == "Single day":
    selected_day = st.date_input(
        "Select day",
        value=min_date,
        min_value=min_date,
        max_value=max_date,
    )
    mask = hourly_df["timestamp"].dt.date == selected_day
    plot_df = hourly_df[mask]
else:  # Custom date range
    date_range = st.date_input(
        "Date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )
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

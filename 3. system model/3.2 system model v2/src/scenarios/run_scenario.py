"""
run_scenario.py — The "mother" script that wires everything together.

    load inputs  →  scale generation  →  run dispatch  →  compute economics

Can be called from:
    • the Streamlit app
    • a plain Python script
    • a Jupyter notebook
"""
import pandas as pd
from src.scenarios.config import ScenarioConfig
from src.data.loaders import load_all_inputs, load_alpha_ventus_wind
from src.models.generation import scale_generation, generate_from_wind_speed
from src.models.dispatch import run_dispatch
from src.models.dispatch_optimised import run_dispatch_optimised
from src.models.economics import compute_hourly_economics, annual_summary, npv


def run_scenario(cfg: ScenarioConfig | None = None) -> tuple[pd.DataFrame, dict]:
    """
    Execute a full scenario run.

    Parameters
    ----------
    cfg : ScenarioConfig, optional
        Override any defaults by passing a customised config.
        If None, uses ScenarioConfig() defaults.

    Returns
    -------
    hourly_df : pd.DataFrame
        Hourly results table (the supervisor's output table format).
    summary : dict
        Annual summary metrics.
    """
    if cfg is None:
        cfg = ScenarioConfig()

    # ── 1. Load raw inputs ────────────────────────────────────────────
    df = load_all_inputs(year=cfg.year, source=cfg.data_source, country=cfg.country)

    # ── 2. Generate power from wind data ─────────────────────────────
    if cfg.use_power_curve:
        # Power-curve path: load Alpha Ventus wind speed CSV, convert via
        # parametric cubic power curve, scale to target farm capacity.
        wind_df = load_alpha_ventus_wind(year=cfg.year)
        df = pd.merge(df, wind_df, on="timestamp", how="left")
        df["wind_speed_ms"] = df["wind_speed_ms"].fillna(0.0)
        df = generate_from_wind_speed(df, cfg)
    else:
        # National-scaling path (default): scale German national offshore
        # generation by capacity ratio.  No power curve needed.
        ref_cap = None if cfg.country == "Germany" else 25.0
        df = scale_generation(
            df,
            target_capacity_mw=cfg.target_farm_capacity_mw,
            alpha_ventus_capacity_mw=cfg.alpha_ventus_capacity_mw,
            derate_factor=cfg.derate_factor,
            smoothing_window=cfg.smoothing_window,
            reference_capacity_mw=ref_cap,
        )

    # ── 3. Run hourly dispatch ────────────────────────────────────────
    if cfg.use_optimised_dispatch:
        dispatch_df = run_dispatch_optimised(
            df,
            cfg,
            horizon_hours=cfg.dispatch_horizon_hours,
            step_hours=cfg.dispatch_step_hours,
            objective=cfg.dispatch_objective,
            battery_cycling_penalty=cfg.battery_cycling_penalty,
        )
    else:
        dispatch_df = run_dispatch(df, cfg)

    # ── 4. Compute economics ──────────────────────────────────────────
    hourly_df = compute_hourly_economics(dispatch_df, cfg)

    # ── 5. Summary metrics ────────────────────────────────────────────
    summary = annual_summary(hourly_df)
    summary["npv_eur"] = npv(
        summary["total_profit_eur"], cfg.discount_rate, cfg.project_lifetime_years
    )

    return hourly_df, summary


# ── Quick CLI usage ──────────────────────────────────────────────────────
if __name__ == "__main__":
    # ── CONFIGURE YOUR RUN HERE ──────────────────────────────────────────
    cfg = ScenarioConfig(
        year=2023,
        country="Germany",
        data_source="SMARD",

        # Dispatch mode — flip use_optimised_dispatch to switch engines:
        #   False → rule-based (dispatch.py)   — fast, simple priority logic
        #   True  → LP optimiser (dispatch_optimised.py) — solves 24h window at once
        use_optimised_dispatch=False,

        # Optimised dispatch settings (only used when use_optimised_dispatch=True):
        #   dispatch_objective = "revenue"  →  maximise grid + H₂ revenue
        #   dispatch_objective = "h2"       →  maximise H₂ production volume
        dispatch_objective="revenue",
        dispatch_horizon_hours=24,          # 24 = day-ahead; 168 = weekly lookahead
        battery_cycling_penalty=1.0,        # €/MWh penalty per MWh battery throughput

        # Fuel cell (set > 0 to enable, only active with optimised dispatch):
        fuel_cell_capacity_mw=0.0,

        # Generation pathway — flip use_power_curve to switch:
        #   False → national German offshore generation scaled by capacity ratio
        #   True  → Alpha Ventus ERA5 wind speed → parametric power curve
        use_power_curve=False,
        # Turbine specs (only used when use_power_curve=True):
        turbine_rated_speed_ms=11.0,   # modern 15 MW class turbine
        turbine_cut_in_ms=3.0,
        turbine_cut_out_ms=25.0,
        turbine_hub_height_m=120.0,    # hub height [m]
        wind_data_height_m=100.0,      # ERA5 data is at 100 m
    )
    # ────────────────────────────────────────────────────────────────────
    hourly_df, summary = run_scenario(cfg)

    print("\n=== SCENARIO SUMMARY ===")
    for k, v in summary.items():
        if isinstance(v, float):
            print(f"  {k}: {v:,.2f}")
        else:
            print(f"  {k}: {v}")

    print(f"\nHourly table: {len(hourly_df)} rows")
    print(hourly_df.head(24).to_string(index=False))

    # Save to CSV
    from src.scenarios.config import OUTPUT_DIR
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"scenario_{cfg.year}_{cfg.data_source}.csv"
    hourly_df.to_csv(out_path, index=False)
    print(f"\nSaved to {out_path}")

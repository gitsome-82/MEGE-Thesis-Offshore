"""
run_scenario.py — The "mother" script that wires everything together.

    load inputs  →  scale generation  →  run dispatch  →  compute economics

Can be called from:
    • the Streamlit app
    • a plain Python script
    • a Jupyter notebook
"""
import pandas as pd
from src.utils.config import ScenarioConfig
from src.data.loaders import load_all_inputs
from src.models.generation import scale_generation
from src.models.dispatch import run_dispatch
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

    # ── 2. Scale generation to target farm size ───────────────────────
    ref_cap = None if cfg.country == "Germany" else 25.0  # Portugal: 25 MW fixed reference
    df = scale_generation(
        df,
        target_capacity_mw=cfg.target_farm_capacity_mw,
        alpha_ventus_capacity_mw=cfg.alpha_ventus_capacity_mw,
        derate_factor=cfg.derate_factor,
        smoothing_window=cfg.smoothing_window,
        reference_capacity_mw=ref_cap,
    )

    # ── 3. Run hourly dispatch ────────────────────────────────────────
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
    cfg = ScenarioConfig()
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
    from src.utils.config import OUTPUT_DIR
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"scenario_{cfg.year}_{cfg.data_source}.csv"
    hourly_df.to_csv(out_path, index=False)
    print(f"\nSaved to {out_path}")

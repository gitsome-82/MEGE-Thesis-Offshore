"""
economics.py — Revenue, profit, and techno-economic metrics.

Takes the hourly dispatch results DataFrame and computes financial outputs.
"""
import numpy as np
import pandas as pd
from src.utils.config import ScenarioConfig


def compute_hourly_economics(
    dispatch_df: pd.DataFrame,
    cfg: ScenarioConfig,
) -> pd.DataFrame:
    """
    Add revenue / profit columns to the dispatch results.

    New columns:
        grid_revenue_eur, h2_revenue_eur, ancillary_revenue_eur,
        total_revenue_eur, opex_eur, profit_eur
    """
    df = dispatch_df.copy()

    df["grid_revenue_eur"] = df["to_grid_mwh"] * df["price_eur_per_mwh"]
    # H₂ revenue is earned when H₂ is SOLD (offtake), not when produced
    df["h2_revenue_eur"] = df["h2_offtake_kg"] * cfg.h2_selling_price_eur_per_kg
    df["ancillary_revenue_eur"] = 0.0  # placeholder — expand later

    df["total_revenue_eur"] = (
        df["grid_revenue_eur"]
        + df["h2_revenue_eur"]
        + df["ancillary_revenue_eur"]
    )

    df["opex_eur"] = df["generation_mwh"] * cfg.opex_eur_per_mwh
    df["profit_eur"] = df["total_revenue_eur"] - df["opex_eur"]

    return df


def annual_summary(df: pd.DataFrame) -> dict:
    """Compute key annual totals from the hourly economics DataFrame."""
    return {
        "total_generation_mwh": df["generation_mwh"].sum(),
        "total_to_grid_mwh": df["to_grid_mwh"].sum(),
        "total_curtailed_mwh": df["curtailed_mwh"].sum(),
        "total_h2_produced_kg": df["h2_produced_kg"].sum(),
        "total_h2_sold_kg": df["h2_offtake_kg"].sum(),
        "curtailment_rate_pct": 100 * df["curtailed_mwh"].sum() / df["generation_mwh"].sum()
        if df["generation_mwh"].sum() > 0 else 0,
        "total_grid_revenue_eur": df["grid_revenue_eur"].sum(),
        "total_h2_revenue_eur": df["h2_revenue_eur"].sum(),
        "total_revenue_eur": df["total_revenue_eur"].sum(),
        "total_profit_eur": df["profit_eur"].sum(),
    }


def npv(annual_profit: float, discount_rate: float, lifetime_years: int) -> float:
    """
    Present value of a constant annual operating profit over the project lifetime.

    This is an annuity PV, NOT a true project NPV — CAPEX is not yet included.
    True project NPV would subtract upfront capital costs (turbines, electrolyser,
    grid connection, etc.) which are typically €1–2B+ for a 500 MW offshore farm.

    Formula:  PV = annual_profit × [(1 - (1+r)^-n) / r]
    """
    return sum(
        annual_profit / (1 + discount_rate) ** t
        for t in range(1, lifetime_years + 1)
    )


def lcoh(total_energy_kwh: float, total_h2_kg: float) -> float:
    """Levelised cost of hydrogen [EUR/kg] (energy-only, no CAPEX yet)."""
    if total_h2_kg <= 0:
        return float('inf')
    # Placeholder: just energy input cost at a flat rate
    return total_energy_kwh / total_h2_kg  # kWh/kg = the efficiency itself

"""
library.py — Named scenario presets.

Usage:
    from src.scenarios.library import get_scenario
    cfg = get_scenario("balanced")

    # or list what's available:
    from src.scenarios.library import SCENARIOS
    print(list(SCENARIOS.keys()))

Each entry is a dict of keyword overrides applied on top of ScenarioConfig
defaults.  Only the fields that differ from the defaults need to be listed.

Adding a new scenario: add one entry to SCENARIOS below. That's it — no
other files need to change.

──────────────────────────────────────────────────────────────────────────
Sizing reference (100 MW electrolyser, 55 kWh/kg):
    max production  = 100 MW × 1000 / 55 = 1818 kg/h  =  43 636 kg/day
    break-even      = offtake_kg/day ÷ (1000/55) ÷ 1000 × 24  [MW]
    e.g. 5 000 kg/day → 11.5 MW electrolyser to just cover offtake
──────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations
from src.scenarios.config import ScenarioConfig


# ── Scenario library ──────────────────────────────────────────────────────────
#
# Keys are scenario names (lowercase, hyphen-separated).
# Values are dicts of ScenarioConfig field overrides.
#
SCENARIOS: dict[str, dict] = {

    # ── "balanced" ────────────────────────────────────────────────────────────
    # Electrolyser sized to just cover the daily offtake contract.
    # The tank stores ~2 days of buffer so the dispatch is forced to make
    # real choices between H₂ and grid export.
    # 5 000 kg/day ÷ 24 h × 55 kWh/kg ÷ 1000 ≈ 11.5 MW
    # prioritise_h2=False → Francisco-style price-switching rule:
    #   make H₂ only when grid price < breakeven (1000/eff × h2_price ≈ €90.9/MWh)
    "balanced": dict(
        target_farm_capacity_mw=500.0,
        electrolyser_capacity_mw=12.0,       # just covers 5 000 kg/day offtake
        tank_capacity_kg=10_000.0,           # ~2 days of offtake buffer
        h2_daily_offtake_kg=5_000.0,
        h2_selling_price_eur_per_kg=5.0,
        prioritise_h2=False,
        use_optimised_dispatch=False,
    ),

    # ── "balanced_lp" ─────────────────────────────────────────────────────────
    # Same sizing as "balanced" but uses the LP optimiser (revenue objective).
    # Useful for direct comparison of rule-based vs LP at the same scale.
    "balanced_lp": dict(
        target_farm_capacity_mw=500.0,
        electrolyser_capacity_mw=12.0,
        tank_capacity_kg=10_000.0,
        h2_daily_offtake_kg=5_000.0,
        h2_selling_price_eur_per_kg=5.0,
        prioritise_h2=True,
        use_optimised_dispatch=True,
        dispatch_objective="revenue",
        dispatch_horizon_hours=48,   # 48h lookahead, execute 24h — avoids end-of-day tank drain
        dispatch_step_hours=24,
    ),

    # ── "balanced_h2" ─────────────────────────────────────────────────────────
    # Same sizing as "balanced" but LP maximises H₂ production volume instead
    # of revenue.  Electrolyser runs as hard as wind and tank allow; grid only
    # absorbs surplus when the tank is full.
    # Useful for industrial H₂ supply contracts where volume > price arbitrage.
    "balanced_h2": dict(
        target_farm_capacity_mw=500.0,
        electrolyser_capacity_mw=12.0,
        tank_capacity_kg=10_000.0,
        h2_daily_offtake_kg=5_000.0,
        h2_selling_price_eur_per_kg=5.0,
        prioritise_h2=True,
        use_optimised_dispatch=True,
        dispatch_objective="h2",
        dispatch_horizon_hours=48,   # 48h lookahead, execute 24h
        dispatch_step_hours=24,
    ),

    # ── "big_tank" ────────────────────────────────────────────────────────────
    # Large electrolyser + ~2 weeks of storage.
    # Demonstrates H₂ as medium-term seasonal buffer: the farm can produce
    # aggressively during windy/low-price periods and the tank absorbs it,
    # releasing steadily to the offtake buyer throughout the year.
    # Net fill rate ≈ 100 MW × 1000/55 − 5000/24 ≈ 1610 kg/h
    # Time to fill 500 000 kg tank ≈ 13 days (one windy fortnight)
    "big_tank": dict(
        target_farm_capacity_mw=500.0,
        electrolyser_capacity_mw=100.0,
        tank_capacity_kg=500_000.0,          # ~100 days of offtake at 5 000 kg/day
        h2_daily_offtake_kg=5_000.0,
        h2_selling_price_eur_per_kg=5.0,
        prioritise_h2=True,
        use_optimised_dispatch=True,
        dispatch_objective="revenue",
        dispatch_horizon_hours=24,
    ),

    # ── "grid_first" ─────────────────────────────────────────────────────────
    # Grid export is always preferred; H₂ only gets surplus power.
    # Shows the opposite extreme to "balanced" — useful to bound the
    # trade-off between H₂ contract revenue and spot market exposure.
    "grid_first": dict(
        target_farm_capacity_mw=500.0,
        electrolyser_capacity_mw=100.0,
        tank_capacity_kg=50_000.0,
        h2_daily_offtake_kg=5_000.0,
        h2_selling_price_eur_per_kg=5.0,
        prioritise_h2=False,
        use_optimised_dispatch=False,
    ),

    # ── "high_h2_price" ───────────────────────────────────────────────────────
    # H₂ at €10/kg (≈ €182/MWh equivalent) — above almost all 2023 spot prices.
    # Electrolysis is always the rational choice; tests the H₂-maximising limit.
    "high_h2_price": dict(
        target_farm_capacity_mw=500.0,
        electrolyser_capacity_mw=100.0,
        tank_capacity_kg=50_000.0,
        h2_daily_offtake_kg=5_000.0,
        h2_selling_price_eur_per_kg=10.0,
        prioritise_h2=True,
        use_optimised_dispatch=True,
        dispatch_objective="revenue",
    ),

    # ── "large_farm" ──────────────────────────────────────────────────────────
    # 2 GW farm representing a future large-scale offshore hub.
    # Electrolyser scaled proportionally; shows curtailment economics at scale.
    "large_farm": dict(
        target_farm_capacity_mw=2000.0,
        electrolyser_capacity_mw=400.0,
        tank_capacity_kg=200_000.0,
        h2_daily_offtake_kg=20_000.0,
        h2_selling_price_eur_per_kg=5.0,
        prioritise_h2=True,
        use_optimised_dispatch=True,
        dispatch_objective="revenue",
        dispatch_horizon_hours=24,
    ),

    # ── "portugal_2024" ───────────────────────────────────────────────────────
    # WindFloat Atlantic reference case with real MIBEL day-ahead prices.
    "portugal_2024": dict(
        country="Portugal",
        data_source="ENTSO-E",
        year=2024,
        target_farm_capacity_mw=500.0,
        electrolyser_capacity_mw=100.0,
        tank_capacity_kg=50_000.0,
        h2_daily_offtake_kg=5_000.0,
        h2_selling_price_eur_per_kg=5.0,
        prioritise_h2=True,
        use_optimised_dispatch=True,
        dispatch_objective="revenue",
    ),
}


def get_scenario(name: str, **overrides) -> ScenarioConfig:
    """
    Return a ScenarioConfig for a named scenario.

    Any keyword argument overrides the preset value, e.g.:
        cfg = get_scenario("balanced", year=2024, h2_selling_price_eur_per_kg=8.0)
    """
    if name not in SCENARIOS:
        available = ", ".join(sorted(SCENARIOS))
        raise KeyError(f"Unknown scenario {name!r}. Available: {available}")
    params = {**SCENARIOS[name], **overrides}
    return ScenarioConfig(**params)

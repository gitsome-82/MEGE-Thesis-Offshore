"""
dispatch.py — Hourly storage-control / dispatch engine.

This is the heart of WP5.4.  For each timestep it decides how to split
the available generation between:
    • grid export
    • electrolyser (H2 production)
    • curtailment

The dispatch strategy is rule-based (V1).  Later this can be replaced with
an optimisation-based approach.

Returns a list of hourly result dicts that become the supervisor's table.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import pandas as pd

from src.models.hydrogen import Electrolyser, HydrogenTank
from src.models.battery import Battery
from src.utils.config import ScenarioConfig


def run_dispatch(
    df: pd.DataFrame,
    cfg: ScenarioConfig,
) -> pd.DataFrame:
    """
    Run the hourly dispatch model over the timeseries in *df*.

    Expected columns in *df*:
        timestamp, gen_scaled_mwh, load_mwh, price_eur_per_mwh

    Dispatch logic (V1 — rule-based, price-driven):
        The farm operator decides how to allocate each hour's generation
        between grid sale, electrolyser, or curtailment based on economic
        signals.  System demand is recorded for context but is NOT a
        constraint (no grid congestion assumed).

        Priority logic:
        1. If spot price ≤ curtailment threshold  → do NOT sell to grid
        2. Compare grid revenue vs H₂ revenue per MWh  → allocate to the
           more profitable channel (up to electrolyser / tank limits)
        3. Whatever cannot go to grid or storage  → curtailed

    Returns a DataFrame with one row per timestep and columns matching the
    supervisor's output table.
    """
    # ── Initialise storage components ─────────────────────────────────
    electrolyser = Electrolyser(
        capacity_mw=cfg.electrolyser_capacity_mw,
        efficiency_kwh_per_kg=cfg.electrolyser_efficiency_kwh_per_kg,
        min_load_frac=cfg.electrolyser_min_load_frac,
    )
    tank = HydrogenTank(
        capacity_kg=cfg.tank_capacity_kg,
        soc_kg=cfg.tank_initial_soc_kg,
    )

    # Battery (0 capacity = disabled)
    battery = Battery(
        capacity_mwh=cfg.battery_capacity_mwh,
        power_mw=cfg.battery_power_mw,
        efficiency=cfg.battery_efficiency,
        soc_mwh=cfg.battery_initial_soc_mwh,
    )

    # Pre-compute: H₂ revenue per MWh of electrical input
    # (1000 kWh / specific_consumption) * h2_price  [EUR / MWh_elec]
    if cfg.electrolyser_efficiency_kwh_per_kg > 0:
        h2_value_per_mwh = (1000.0 / cfg.electrolyser_efficiency_kwh_per_kg) * cfg.h2_selling_price_eur_per_kg
    else:
        h2_value_per_mwh = 0.0

    # Curtailment floor: if no explicit threshold, use operating cost
    # (selling below opex means losing money on every MWh exported)
    curtail_floor = (
        cfg.curtailment_price_threshold_eur
        if cfg.curtailment_price_threshold_eur is not None
        else cfg.opex_eur_per_mwh
    )

    # DISCHARGE RULE — fixed daily offtake, spread evenly across 24 hours.
    # Represents a steady industrial H₂ buyer (pipeline delivery contract).
    # Each hour we remove offtake/24 from the tank (if available).
    hourly_offtake_kg = cfg.h2_daily_offtake_kg / 24.0

    results = []

    for _, row in df.iterrows():
        ts = row["timestamp"]
        gen = row["gen_scaled_mwh"]       # MWh generated this hour
        demand = row["load_mwh"]          # system demand (context only)
        price = row.get("price_eur_per_mwh", 50.0)

        remaining = gen
        to_grid = 0.0
        power_consumed = 0.0
        h2_produced = 0.0
        batt_charge_mw = 0.0
        curtailed = 0.0
        h2_offtake = 0.0
        action_parts = []

        # ── Step 0: H₂ tank offtake (DISCHARGE RULE) ─────────────────
        # Fixed hourly withdrawal representing steady industrial buyer.
        # This happens every hour regardless of generation — the buyer
        # takes delivery on a schedule.
        if hourly_offtake_kg > 0 and tank.soc_kg > 0:
            h2_offtake = tank.discharge(hourly_offtake_kg)

        # ── Step 1: Should we avoid the grid this hour? ──────────────
        # Don't sell to grid if spot price is at or below operating cost
        # (would lose money).  However, H₂ production may still be
        # profitable even when grid sale is not — handled in Step 2.
        allow_grid = price > curtail_floor

        # ── Step 2: Allocate generation ──────────────────────────────
        # Compare marginal value: grid sale (price) vs H₂ production
        prefer_h2 = (
            cfg.electrolyser_capacity_mw > 0
            and tank.soc_kg < tank.capacity_kg
            and (cfg.prioritise_h2 or h2_value_per_mwh > price)
        )

        if prefer_h2:
            # --- Send up to electrolyser capacity to H₂ first ---
            elec_input = min(remaining, cfg.electrolyser_capacity_mw)
            power_consumed, h2_produced = electrolyser.produce(elec_input)
            h2_stored, h2_excess = tank.charge(h2_produced)

            # If tank full mid-step: back off
            if h2_excess > 0:
                wasted_kwh = h2_excess * cfg.electrolyser_efficiency_kwh_per_kg
                power_consumed -= wasted_kwh / 1000.0
                power_consumed = max(0.0, power_consumed)
                h2_produced -= h2_excess

            remaining -= power_consumed
            if power_consumed > 0:
                action_parts.append("electrolyse")

            # --- Send remainder to grid (if allowed) ---
            if allow_grid and remaining > 0:
                to_grid = remaining
                remaining = 0.0
                action_parts.append("grid")
        else:
            # --- Grid first ---
            if allow_grid:
                to_grid = remaining
                remaining = 0.0
                action_parts.append("grid")
            else:
                # Price too low for grid → try electrolyser
                if cfg.electrolyser_capacity_mw > 0 and tank.soc_kg < tank.capacity_kg:
                    elec_input = min(remaining, cfg.electrolyser_capacity_mw)
                    power_consumed, h2_produced = electrolyser.produce(elec_input)
                    h2_stored, h2_excess = tank.charge(h2_produced)
                    if h2_excess > 0:
                        wasted_kwh = h2_excess * cfg.electrolyser_efficiency_kwh_per_kg
                        power_consumed -= wasted_kwh / 1000.0
                        power_consumed = max(0.0, power_consumed)
                        h2_produced -= h2_excess
                    remaining -= power_consumed
                    if power_consumed > 0:
                        action_parts.append("electrolyse")

        # --- Battery charge (if enabled and energy remains) ---
        if remaining > 0 and cfg.battery_capacity_mwh > 0:
            batt_charge_mw, _ = battery.charge(remaining)
            remaining -= batt_charge_mw
            if batt_charge_mw > 0:
                action_parts.append("battery_charge")

        # --- Curtailment = whatever is left ---
        curtailed = max(0.0, remaining)
        if curtailed > 0:
            action_parts.append("curtail")

        action = " + ".join(action_parts) if action_parts else "idle"

        results.append({
            "timestamp": ts,
            "action": action,
            "generation_mwh": gen,
            "demand_mwh": demand,
            "price_eur_per_mwh": price,
            "to_grid_mwh": to_grid,
            "to_electrolyser_mwh": power_consumed,
            "h2_produced_kg": h2_produced,
            "tank_soc_kg": tank.soc_kg,
            "energy_flux_battery_kwh": batt_charge_mw * 1000.0,
            "curtailed_mwh": curtailed,
            "battery_soc_mwh": battery.soc_mwh,
            "h2_offtake_kg": h2_offtake,
        })

    return pd.DataFrame(results)

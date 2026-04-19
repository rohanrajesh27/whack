"""
Corner Store of the Future - Dynamic Pricing
Track 2: GW Global Food Institute | Problem Statement 2

Edit the INPUTS section at the top of the file, then run:
    python3 banana_price.py

The script prints the anchor, freshness score, multiplier, and final
shelf price, along with any guardrails that clamped the price.
"""

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ===========================================================================
# INPUTS - edit these when you have real data, then re-run the script
# ===========================================================================

# --- FAO anchor (the one thing we DON'T change without a new monthly figure)
FAO_BANANA_PRICE_USD_PER_KG = 0.90   # recent FAO wholesale banana price
AVG_BANANA_WEIGHT_KG = 0.120         # USDA average, ~120g per medium banana

# --- Markup tier (pick one: 2.5, 3.0, or 3.5)
MARKUP_MULTIPLIER = 3.0              # 2.5 conservative / 3.0 DCCK / 3.5 big-box

# --- Sensor readings for the banana you're pricing right now
CURRENT_WEIGHT_G = 120.0             # current weight from the load cell
INITIAL_WEIGHT_G = 120.0             # weight at day zero (lot registration)
AGE_DAYS = 0.0                       # days since lot was registered
TEMPERATURE_C = 22.0                 # current ambient temperature
HUMIDITY_PCT = 60.0                  # current relative humidity

# --- Visual override (human or camera-based "how does it actually look?")
# Multiplies the effective age before it goes into the freshness curve.
# 1.0  = looks exactly as expected for its age (no override)
# <1.0 = LOOKS FRESHER than its age suggests (treat as younger banana)
# >1.0 = LOOKS WORSE than its age suggests (treat as older banana)
VISUAL_AGE_MULTIPLIER = 1.0

# --- Per-store calibration (change once per store, then leave alone)
DISTRIBUTOR_COST_PER_UNIT = 0.18     # what the store paid per banana
SNAP_MATCH_FLOOR = 0.15              # price floor that preserves SNAP Match math
AFFORDABILITY_CEILING = 0.60         # never price above this (mission cap)
MIN_DISPLAY_CHANGE = 0.05            # LCD doesn't refresh for smaller changes


# ===========================================================================
# FRESHNESS MODEL TUNABLES
# ===========================================================================

# Weights for the freshness score components (must sum to 1.0)
W_TIME = 0.40
W_TEMP = 0.30
W_WEIGHT = 0.20
W_HUMIDITY = 0.10

# Non-linear time decay (logistic curve). Midpoint = day the score hits 50.
TIME_DECAY_MIDPOINT_DAYS = 4.0
TIME_DECAY_STEEPNESS = 1.3

# Optimal storage conditions for bananas
OPTIMAL_TEMP_C = 15.0
OPTIMAL_HUMIDITY_PCT = 90.0

# End-of-life multiplier floor
FRESHNESS_FLOOR_MULTIPLIER = 0.40


# ===========================================================================
# PRICING LOGIC
# ===========================================================================

@dataclass
class SensorReading:
    timestamp: float
    weight_g: float
    temperature_c: float
    humidity_pct: float


@dataclass
class LotState:
    lot_id: str
    registered_at: float
    initial_weight_g: float
    readings: list = field(default_factory=list)
    last_shown_price: Optional[float] = None
    locked_anchor: float = 0.0

    def add_reading(self, r: SensorReading) -> None:
        self.readings.append(r)

    def latest(self) -> Optional[SensorReading]:
        return self.readings[-1] if self.readings else None


@dataclass
class PricingResult:
    anchor: float
    freshness_score: float
    multiplier: float
    raw_price: float
    final_price: float
    should_update_display: bool
    reason_codes: list = field(default_factory=list)


def compute_anchor_price() -> float:
    """Anchor = FAO wholesale * avg weight * markup, clamped by floor & ceiling."""
    raw = FAO_BANANA_PRICE_USD_PER_KG * AVG_BANANA_WEIGHT_KG * MARKUP_MULTIPLIER
    return max(DISTRIBUTOR_COST_PER_UNIT, min(raw, AFFORDABILITY_CEILING))


def _time_score(lot: LotState, now: float) -> float:
    """Logistic time decay, modulated by VISUAL_AGE_MULTIPLIER."""
    raw_age_days = (now - lot.registered_at) / 86400.0
    effective_age_days = raw_age_days * VISUAL_AGE_MULTIPLIER
    exponent = TIME_DECAY_STEEPNESS * (effective_age_days - TIME_DECAY_MIDPOINT_DAYS)
    exponent = max(-50.0, min(50.0, exponent))
    score = 100.0 / (1.0 + math.exp(exponent))
    return max(0.0, min(100.0, score))


def _temp_score(lot: LotState) -> float:
    """Cumulative degree-hours above optimal."""
    if len(lot.readings) < 2:
        return 100.0
    penalty = 0.0
    for i in range(1, len(lot.readings)):
        prev, curr = lot.readings[i - 1], lot.readings[i]
        dt_hours = (curr.timestamp - prev.timestamp) / 3600.0
        excess = max(0.0, curr.temperature_c - OPTIMAL_TEMP_C)
        penalty += excess * dt_hours
    return max(0.0, 100.0 - penalty * 0.5)


def _weight_score(lot: LotState) -> float:
    """Weight loss signal. ~15% loss = end of life."""
    latest = lot.latest()
    if latest is None or lot.initial_weight_g <= 0:
        return 100.0
    pct_lost = max(0.0, (lot.initial_weight_g - latest.weight_g) / lot.initial_weight_g)
    return max(0.0, 100.0 * (1.0 - pct_lost / 0.15))


def _humidity_score(lot: LotState) -> float:
    """Deviation from optimal humidity."""
    if not lot.readings:
        return 100.0
    deviations = [abs(r.humidity_pct - OPTIMAL_HUMIDITY_PCT) for r in lot.readings]
    avg_dev = sum(deviations) / len(deviations)
    return max(0.0, 100.0 * (1.0 - avg_dev / 40.0))


def compute_freshness_score(lot: LotState, now: float) -> float:
    """Weighted blend of time, temperature, weight, and humidity."""
    score = (
        W_TIME * _time_score(lot, now)
        + W_TEMP * _temp_score(lot)
        + W_WEIGHT * _weight_score(lot)
        + W_HUMIDITY * _humidity_score(lot)
    )
    return max(0.0, min(100.0, score))


def freshness_to_multiplier(freshness: float) -> float:
    """Map 0-100 freshness score to a [FLOOR, 1.0] price multiplier."""
    normalized = freshness / 100.0
    return FRESHNESS_FLOOR_MULTIPLIER + normalized * (1.0 - FRESHNESS_FLOOR_MULTIPLIER)


def compute_shelf_price(lot: LotState, now: float) -> PricingResult:
    """Full pipeline: anchor -> freshness -> multiplier -> guardrails -> display."""
    reasons = []

    if lot.locked_anchor <= 0:
        lot.locked_anchor = compute_anchor_price()
    anchor = lot.locked_anchor

    freshness = compute_freshness_score(lot, now)
    multiplier = freshness_to_multiplier(freshness)
    raw = anchor * multiplier

    final = raw
    if final < DISTRIBUTOR_COST_PER_UNIT:
        final = DISTRIBUTOR_COST_PER_UNIT
        reasons.append("clamped_to_distributor_cost")
    if final < SNAP_MATCH_FLOOR:
        final = SNAP_MATCH_FLOOR
        reasons.append("clamped_to_snap_match_floor")
    if final > AFFORDABILITY_CEILING:
        final = AFFORDABILITY_CEILING
        reasons.append("clamped_to_affordability_ceiling")
    if lot.last_shown_price is not None and final > lot.last_shown_price:
        final = lot.last_shown_price
        reasons.append("downward_only_enforced")

    final = round(final, 2)

    should_update = (
        lot.last_shown_price is None
        or abs(final - lot.last_shown_price) >= MIN_DISPLAY_CHANGE
    )
    if should_update:
        lot.last_shown_price = final

    return PricingResult(
        anchor=round(anchor, 2),
        freshness_score=round(freshness, 1),
        multiplier=round(multiplier, 3),
        raw_price=round(raw, 3),
        final_price=final,
        should_update_display=should_update,
        reason_codes=reasons,
    )


# ===========================================================================
# Helper for other modules (restock) to get the current price without
# running main() and printing everything.
# ===========================================================================

def price_from_inputs() -> PricingResult:
    """Build a LotState from the module-level INPUTS and return the price."""
    now = AGE_DAYS * 86400.0
    lot = LotState(
        lot_id="banana",
        registered_at=0.0,
        initial_weight_g=INITIAL_WEIGHT_G,
    )
    if AGE_DAYS > 0:
        lot.add_reading(SensorReading(
            timestamp=0.0,
            weight_g=INITIAL_WEIGHT_G,
            temperature_c=TEMPERATURE_C,
            humidity_pct=HUMIDITY_PCT,
        ))
    lot.add_reading(SensorReading(
        timestamp=now,
        weight_g=CURRENT_WEIGHT_G,
        temperature_c=TEMPERATURE_C,
        humidity_pct=HUMIDITY_PCT,
    ))
    return compute_shelf_price(lot, now=now)


# ===========================================================================
# RUN
# ===========================================================================

def main() -> None:
    result = price_from_inputs()

    print("=" * 60)
    print("  Corner Store Pricing - Banana")
    print("=" * 60)
    print(f"  FAO wholesale:          ${FAO_BANANA_PRICE_USD_PER_KG:.2f}/kg")
    print(f"  Avg banana weight:      {AVG_BANANA_WEIGHT_KG * 1000:.0f}g")
    print(f"  Markup multiplier:      {MARKUP_MULTIPLIER}x")
    print("  " + "-" * 56)
    print(f"  Current weight:         {CURRENT_WEIGHT_G:.0f}g")
    print(f"  Day-zero weight:        {INITIAL_WEIGHT_G:.0f}g")
    if INITIAL_WEIGHT_G > 0:
        pct_lost = (INITIAL_WEIGHT_G - CURRENT_WEIGHT_G) / INITIAL_WEIGHT_G * 100
        print(f"  Weight loss:            {pct_lost:.1f}%")
    print(f"  Age:                    {AGE_DAYS} days")
    if VISUAL_AGE_MULTIPLIER != 1.0:
        effective = AGE_DAYS * VISUAL_AGE_MULTIPLIER
        label = "looks fresher" if VISUAL_AGE_MULTIPLIER < 1.0 else "looks worse"
        print(f"  Visual override:        {VISUAL_AGE_MULTIPLIER}x ({label}, "
              f"effective age {effective:.1f} days)")
    print(f"  Temperature:            {TEMPERATURE_C}C")
    print(f"  Humidity:               {HUMIDITY_PCT}%")
    print("  " + "-" * 56)
    print(f"  Anchor price:           ${result.anchor:.2f}")
    print(f"  Freshness score:        {result.freshness_score}/100")
    print(f"  Freshness multiplier:   {result.multiplier}")
    print(f"  Raw price:              ${result.raw_price:.3f}")
    print(f"  FINAL SHELF PRICE:      ${result.final_price:.2f}")
    if result.reason_codes:
        print(f"  Guardrails hit:         {', '.join(result.reason_codes)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
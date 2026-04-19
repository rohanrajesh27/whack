"""
Corner Store of the Future - Dynamic Pricing
Track 2: GW Global Food Institute | Problem Statement 2

Edit the INPUTS section at the top of the file, then run:
    python3 banana_price.py

The script prints the anchor, freshness score, multiplier, and final
shelf price, along with any guardrails that clamped the price.
"""

import datetime as dt
import math
import os
from dataclasses import dataclass, field
from typing import Optional


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# ===========================================================================
# INPUTS - edit these when you have real data, then re-run the script
# (Production: optional env overrides — PRICING_FAO_BANANA_USD_PER_KG,
# PRICING_AVG_BANANA_WEIGHT_KG, PRICING_MARKUP_MULTIPLIER, etc.)
# ===========================================================================

# --- FAO anchor (the one thing we DON'T change without a new monthly figure)
FAO_BANANA_PRICE_USD_PER_KG = _env_float("PRICING_FAO_BANANA_USD_PER_KG", 0.90)
AVG_BANANA_WEIGHT_KG = _env_float("PRICING_AVG_BANANA_WEIGHT_KG", 0.120)

# --- Markup tier (pick one: 2.5, 3.0, or 3.5)
MARKUP_MULTIPLIER = _env_float("PRICING_MARKUP_MULTIPLIER", 3.0)

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
DISTRIBUTOR_COST_PER_UNIT = _env_float("PRICING_DISTRIBUTOR_COST_PER_UNIT", 0.18)
SNAP_MATCH_FLOOR = _env_float("PRICING_SNAP_MATCH_FLOOR", 0.15)
AFFORDABILITY_CEILING = _env_float("PRICING_AFFORDABILITY_CEILING", 0.60)
MIN_DISPLAY_CHANGE = _env_float("PRICING_MIN_DISPLAY_CHANGE", 0.05)


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


def _time_score(lot: LotState, now: float, visual_age_mult: Optional[float] = None) -> float:
    """Logistic time decay, modulated by visual age multiplier (ripeness / camera)."""
    raw_age_days = (now - lot.registered_at) / 86400.0
    mult = VISUAL_AGE_MULTIPLIER if visual_age_mult is None else float(visual_age_mult)
    effective_age_days = raw_age_days * mult
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


def compute_freshness_score(
    lot: LotState, now: float, visual_age_mult: Optional[float] = None
) -> float:
    """Weighted blend of time, temperature, weight, and humidity."""
    score = (
        W_TIME * _time_score(lot, now, visual_age_mult)
        + W_TEMP * _temp_score(lot)
        + W_WEIGHT * _weight_score(lot)
        + W_HUMIDITY * _humidity_score(lot)
    )
    return max(0.0, min(100.0, score))


def freshness_to_multiplier(freshness: float) -> float:
    """Map 0-100 freshness score to a [FLOOR, 1.0] price multiplier."""
    normalized = freshness / 100.0
    return FRESHNESS_FLOOR_MULTIPLIER + normalized * (1.0 - FRESHNESS_FLOOR_MULTIPLIER)


def compute_shelf_price(
    lot: LotState, now: float, visual_age_mult: Optional[float] = None
) -> PricingResult:
    """Full pipeline: anchor -> freshness -> multiplier -> guardrails -> display."""
    reasons = []

    if lot.locked_anchor <= 0:
        lot.locked_anchor = compute_anchor_price()
    anchor = lot.locked_anchor

    freshness = compute_freshness_score(lot, now, visual_age_mult)
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
    """CLI/demo: same pipeline as :func:`price_for_mongo_lot` using module INPUTS."""
    nw = dt.datetime.now().replace(microsecond=0)
    ra = nw - dt.timedelta(days=float(AGE_DAYS))
    return price_for_mongo_lot(
        received_at=ra,
        now=nw,
        initial_weight_g=float(INITIAL_WEIGHT_G),
        current_weight_g=float(CURRENT_WEIGHT_G),
        temperature_c=float(TEMPERATURE_C),
        humidity_pct=float(HUMIDITY_PCT),
        ripeness=None,
        last_shown_price=None,
        anchor_price=None,
    )


def visual_multiplier_from_ripeness(ripeness: Optional[int]) -> float:
    """Map camera / shelf ripeness 1–5 into PricingAlgo visual-age semantics.

    Higher ripeness => looks older => larger multiplier (same direction as
    ``VISUAL_AGE_MULTIPLIER`` > 1 in the module docstring).
    """
    if ripeness is None:
        return VISUAL_AGE_MULTIPLIER
    r = max(1, min(5, int(ripeness)))
    return 0.82 + (r - 1) * (1.22 - 0.82) / 4.0


def _per_lot_ripeness_and_weight_price_adjust(
    ripeness: Optional[int], initial_weight_g: float, current_weight_g: float
) -> tuple[float, float, float]:
    """Extra multipliers so each batch differs by shelf ripeness + measured weight loss.

    Returns ``(rip_adj, weight_loss_adj, combined)`` applied after the freshness pipeline.
    """
    if ripeness is None:
        rip_adj = 1.0
    else:
        r = max(1, min(5, int(ripeness)))
        # Fresher (1) holds a small premium; riper (5) discounts more than freshness alone.
        rip_adj = 1.09 - (r - 1) * 0.0725
    iw = max(1.0, float(initial_weight_g))
    cw = max(1.0, float(current_weight_g))
    wl = max(0.0, (iw - cw) / iw)
    weight_loss_adj = 1.0 - min(0.2, wl * 0.55)
    return rip_adj, weight_loss_adj, rip_adj * weight_loss_adj


def price_for_mongo_lot(
    *,
    received_at: dt.datetime,
    now: dt.datetime,
    initial_weight_g: float,
    current_weight_g: float,
    temperature_c: float,
    humidity_pct: float,
    ripeness: Optional[int] = None,
    last_shown_price: Optional[float] = None,
    anchor_price: Optional[float] = None,
) -> PricingResult:
    """Run the shelf model for a real lot (Mongo + sensor style fields).

    ``received_at`` / ``now`` may be tz-aware; they are converted to naive UTC
    for age math. ``now`` in :func:`compute_shelf_price` is seconds since lot
    registration (same convention as :func:`price_from_inputs`).

    If ``anchor_price`` is a positive number (e.g. the food item's base retail
    from Mongo), that value is used as the shelf anchor instead of the FAO
    wholesale formula in :func:`compute_anchor_price`.
    """
    ra = received_at
    nw = now
    if ra.tzinfo is not None:
        ra = ra.astimezone(dt.timezone.utc).replace(tzinfo=None)
    if nw.tzinfo is not None:
        nw = nw.astimezone(dt.timezone.utc).replace(tzinfo=None)
    age_seconds = max(1.0, (nw - ra).total_seconds())

    iw = max(1.0, float(initial_weight_g))
    cw = max(1.0, float(current_weight_g))
    tc = float(temperature_c)
    hp = float(humidity_pct)
    visual = visual_multiplier_from_ripeness(ripeness)

    locked = 0.0
    if anchor_price is not None:
        try:
            ap = float(anchor_price)
            if ap > 0:
                locked = max(DISTRIBUTOR_COST_PER_UNIT, min(ap, AFFORDABILITY_CEILING))
        except (TypeError, ValueError):
            locked = 0.0

    lot = LotState(
        lot_id="mongo",
        registered_at=0.0,
        initial_weight_g=iw,
        last_shown_price=last_shown_price,
        locked_anchor=locked,
    )
    lot.add_reading(
        SensorReading(timestamp=0.0, weight_g=iw, temperature_c=tc, humidity_pct=hp)
    )
    lot.add_reading(
        SensorReading(
            timestamp=float(age_seconds),
            weight_g=cw,
            temperature_c=tc,
            humidity_pct=hp,
        )
    )
    result = compute_shelf_price(lot, now=float(age_seconds), visual_age_mult=visual)

    _, _, combined = _per_lot_ripeness_and_weight_price_adjust(ripeness, iw, cw)
    adapted = round(float(result.final_price) * combined, 2)
    reasons = list(result.reason_codes)
    if abs(combined - 1.0) > 1e-6:
        reasons.append("per_lot_ripeness_weight_adjust")
    adapted = max(DISTRIBUTOR_COST_PER_UNIT, adapted)
    adapted = max(SNAP_MATCH_FLOOR, adapted)
    adapted = min(AFFORDABILITY_CEILING, adapted)
    adapted = round(adapted, 2)

    raw_adj = round(float(result.final_price) * combined, 3)

    return PricingResult(
        anchor=result.anchor,
        freshness_score=result.freshness_score,
        multiplier=result.multiplier,
        raw_price=raw_adj,
        final_price=adapted,
        should_update_display=result.should_update_display,
        reason_codes=reasons,
    )


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
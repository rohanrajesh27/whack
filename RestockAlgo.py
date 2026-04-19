"""
Corner Store of the Future - Restock / Inventory Dashboard
Track 2: GW Global Food Institute | Problem Statement 2

Edit the INPUTS section at the top of the file, then run:
    python3 banana_restock.py

This file imports the current shelf price from ``PricingAlgo.price_from_inputs``
(same engine as ``price_for_mongo_lot`` on the web) so the supply-demand loop
uses the same freshness pipeline as the dashboard.

Formula:
    Reorder Point  = (daily_sales * lead_time) + safety_stock
    Safety Stock   = Z * sigma * sqrt(lead_time) + buffer_days * daily_sales
    Price-adjusted = base_velocity * (reference_price / current_price) ^ elasticity
"""

import math
from dataclasses import dataclass

# Pulls the current shelf price from the pricing module.
from PricingAlgo import price_from_inputs


# ===========================================================================
# INPUTS - edit these when you have real data, then re-run the script
# ===========================================================================

# --- Current inventory state
CURRENT_STOCK_UNITS = 15                        # bananas on the shelf right now

# --- Recent daily sales (most recent day last). Used to compute mean + stdev.
RECENT_DAILY_SALES = [8, 10, 9, 12, 7, 11, 10]  # bananas sold per day

# --- Supply chain constants
LEAD_TIME_DAYS = 4                              # days from ordering to delivery
REVIEW_PERIOD_DAYS = 1                          # daily shelf check
SAFETY_BUFFER_DAYS = 1                          # extra cushion beyond the math
SERVICE_LEVEL_Z = 1.65                          # 1.65 = 95% no-stockout, 2.33 = 99%

# --- Shelf capacity ceiling
MAX_SHELF_CAPACITY = 60                         # can't fit more than this

# --- Price elasticity (the supply-demand link)
# Produce elasticity is typically -0.6 to -1.2. We use the absolute value.
# 0.8 = a 10% price drop drives ~8% more sales.
PRICE_ELASTICITY = 0.8

# Reference price = the price at which the above daily sales were measured.
# Deviation from this scales projected demand.
REFERENCE_PRICE = 0.32


# ===========================================================================
# RESTOCK LOGIC
# ===========================================================================

@dataclass
class RestockResult:
    current_stock: int
    base_velocity: float         # units/day from historical data
    adjusted_velocity: float     # units/day after price-elasticity adjustment
    velocity_std: float          # stdev of daily sales
    days_of_supply: float        # how long current stock will last
    reorder_point: int           # trigger level
    safety_stock: int            # buffer component of reorder point
    should_reorder: bool
    suggested_order_qty: int
    stockout_risk_pct: float     # rough chance of running out before delivery
    alert_level: str             # "green" / "yellow" / "red"
    alert_message: str


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stdev(values: list[float]) -> float:
    """Sample standard deviation. Returns 0 if fewer than 2 values."""
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))


def compute_adjusted_velocity(base_velocity: float, current_price: float) -> float:
    """
    Price-elasticity adjustment.
    adjusted = base * (reference_price / current_price) ^ elasticity
    Lower current price -> higher ratio -> faster sales.
    """
    if current_price <= 0 or REFERENCE_PRICE <= 0:
        return base_velocity
    price_ratio = REFERENCE_PRICE / current_price
    return base_velocity * (price_ratio ** PRICE_ELASTICITY)


def compute_stockout_risk(
    stock: int,
    velocity_mean: float,
    velocity_std: float,
    lead_time_days: int,
) -> float:
    """
    Rough probability that stock runs out before the next delivery arrives.
    Uses a normal approximation on lead-time demand.
    Returns a percentage 0-100.
    """
    expected_demand = velocity_mean * lead_time_days
    demand_std = velocity_std * math.sqrt(lead_time_days) if velocity_std > 0 else 0.01

    if demand_std <= 0:
        return 0.0 if stock >= expected_demand else 100.0
    z = (stock - expected_demand) / demand_std
    phi = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    stockout_prob = 1.0 - phi
    return round(stockout_prob * 100.0, 1)


def compute_restock(
    current_price: float,
    *,
    current_stock_units: int | None = None,
    recent_daily_sales: list[float] | None = None,
    lead_time_days: int | None = None,
) -> RestockResult:
    """Full restock pipeline. Takes the current shelf price to close the loop.

    When ``current_stock_units`` / ``recent_daily_sales`` are omitted, module
    defaults (``CURRENT_STOCK_UNITS``, ``RECENT_DAILY_SALES``) are used so the
    CLI keeps working. Pass one float per banana **lot** (e.g. three lots) in
    ``recent_daily_sales`` so velocity mean/std reflect your batches.
    """
    stock = int(current_stock_units) if current_stock_units is not None else int(CURRENT_STOCK_UNITS)
    sales = list(recent_daily_sales) if recent_daily_sales is not None else list(RECENT_DAILY_SALES)
    if len(sales) < 2:
        sales = sales + [sales[-1]] * (2 - len(sales)) if sales else [1.0, 1.0]
    lt = int(LEAD_TIME_DAYS) if lead_time_days is None else int(lead_time_days)

    base_velocity = _mean(sales)
    velocity_std = _stdev(sales)
    adjusted_velocity = compute_adjusted_velocity(base_velocity, current_price)

    days_of_supply = stock / adjusted_velocity if adjusted_velocity > 0 else float("inf")

    safety_stock = int(
        math.ceil(
            SERVICE_LEVEL_Z * velocity_std * math.sqrt(lt)
            + adjusted_velocity * SAFETY_BUFFER_DAYS
        )
    )
    reorder_point = int(math.ceil(adjusted_velocity * lt + safety_stock))

    should_reorder = stock <= reorder_point

    target_stock = int(math.ceil(adjusted_velocity * (lt + REVIEW_PERIOD_DAYS) + safety_stock))
    suggested_order_qty = (
        max(0, min(target_stock - stock, MAX_SHELF_CAPACITY - stock)) if should_reorder else 0
    )

    stockout_risk = compute_stockout_risk(stock, adjusted_velocity, velocity_std, lt)

    if stock <= reorder_point * 0.5 or stockout_risk >= 40:
        alert_level = "red"
        alert_message = "ORDER NOW - high stockout risk before next delivery"
    elif should_reorder:
        alert_level = "yellow"
        alert_message = "Order soon - at or near reorder point"
    else:
        alert_level = "green"
        alert_message = f"Plenty of stock ({days_of_supply:.1f} days of supply)"

    return RestockResult(
        current_stock=stock,
        base_velocity=round(base_velocity, 2),
        adjusted_velocity=round(adjusted_velocity, 2),
        velocity_std=round(velocity_std, 2),
        days_of_supply=round(days_of_supply, 1),
        reorder_point=reorder_point,
        safety_stock=safety_stock,
        should_reorder=should_reorder,
        suggested_order_qty=suggested_order_qty,
        stockout_risk_pct=stockout_risk,
        alert_level=alert_level,
        alert_message=alert_message,
    )


# ===========================================================================
# RUN
# ===========================================================================

def main() -> None:
    # Pull the current shelf price from banana_price.py so elasticity is real.
    pricing = price_from_inputs()
    current_price = pricing.final_price

    restock = compute_restock(current_price)

    alert_icons = {"green": "[OK]", "yellow": "[!!]", "red": "[!!!]"}
    print("=" * 60)
    print("  Restock / Inventory Dashboard - Banana")
    print("=" * 60)
    print(f"  Current shelf price:    ${current_price:.2f}  "
          f"(reference: ${REFERENCE_PRICE:.2f})")
    print(f"  Current stock:          {restock.current_stock} bananas")
    print("  " + "-" * 56)
    print(f"  Base sales velocity:    {restock.base_velocity} bananas/day "
          f"(avg of last {len(RECENT_DAILY_SALES)} days)")
    print(f"  Sales variability:      +/- {restock.velocity_std} bananas/day")
    if abs(restock.adjusted_velocity - restock.base_velocity) >= 0.1:
        direction = "FASTER" if restock.adjusted_velocity > restock.base_velocity else "SLOWER"
        print(f"  Price-adjusted velocity: {restock.adjusted_velocity} bananas/day "
              f"({direction} due to price)")
    print("  " + "-" * 56)
    print(f"  Days of supply left:    {restock.days_of_supply} days")
    print(f"  Lead time:              {LEAD_TIME_DAYS} days")
    print(f"  Reorder point:          {restock.reorder_point} bananas "
          f"(incl. {restock.safety_stock} safety stock)")
    print(f"  Stockout risk:          {restock.stockout_risk_pct}% before next delivery")
    print("  " + "-" * 56)
    print(f"  {alert_icons[restock.alert_level]} {restock.alert_message}")
    if restock.should_reorder:
        print(f"  Suggested order:        {restock.suggested_order_qty} bananas")
    print("=" * 60)


if __name__ == "__main__":
    main()
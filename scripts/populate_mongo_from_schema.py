#!/usr/bin/env python3
"""
Populate MongoDB with random VitalShelf-shaped data (stores, users, SKUs, lots, readings, pricing).

This script mirrors the app’s Mongo collections:
  stores, users, food_items, lots, sensor_readings, pricing_rules

Usage (from project root):
  python scripts/populate_mongo_from_schema.py
  python scripts/populate_mongo_from_schema.py --reset   # drop app collections + counters, re-index, then fill

Requires MONGODB_URI (and optional MONGODB_DB_NAME) in .env or environment.
"""

from __future__ import annotations

import argparse
import datetime
import os
import random
import sys
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass

from werkzeug.security import generate_password_hash

from db_mongo import alloc_id, init_mongo, now_ts
from mongo_db import close_mongo_client, get_mongo_db

COLLECTIONS = (
    "stores",
    "users",
    "food_items",
    "lots",
    "sensor_readings",
    "pricing_rules",
)

DEPARTMENTS = ["Produce", "Dairy", "Meat", "Bakery", "Frozen", "Pantry", "Beverages", "Other"]

PRODUCTS = [
    ("Crimini mushrooms", "8 oz pack"),
    ("Red onions", "3 lb bag"),
    ("Strawberries", "1 lb"),
    ("Cottage cheese", "16 oz"),
    ("Salmon fillet", "per lb"),
    ("Ciabatta rolls", "4 count"),
    ("Ice cream pint", "various"),
    ("Black beans", "15 oz can"),
    ("Seltzer 12-pack", "lime"),
    ("Baby carrots", "1 lb"),
    ("Mozzarella", "8 oz"),
    ("Ground turkey", "93% lean"),
    ("Pita bread", "6 pack"),
    ("Frozen broccoli", "12 oz"),
    ("Granola", "14 oz"),
    ("Lemons", "2 lb bag"),
    ("Half & half", "32 oz"),
    ("Breakfast sausage", "12 oz"),
    ("Croissants", "4 count"),
    ("Apple juice", "64 oz"),
]

STREETS = ["Oak", "Maple", "Cedar", "Pine", "Elm", "Bay", "Hill", "Lake"]
CITIES = ["Springfield", "Riverside", "Fairview", "Madison", "Georgetown"]


def _reset_db() -> None:
    db = get_mongo_db()
    for name in COLLECTIONS:
        db[name].drop()
    db["_counters"].drop()
    init_mongo()


def _rand_address(rng: random.Random) -> str:
    n = rng.randint(100, 9999)
    st = rng.choice(STREETS)
    c = rng.choice(CITIES)
    return f"{n} {st} St, {c}, USA"


def populate(
    *,
    num_stores: int = 4,
    num_users: int = 6,
    items_per_store_range=(4, 9),
    seed: Optional[int] = None,
) -> None:
    rng = random.Random(seed)
    db = get_mongo_db()
    init_mongo()

    now = datetime.datetime.now().replace(microsecond=0)
    store_ids: list[int] = []

    for i in range(num_stores):
        sid = alloc_id("stores")
        store_ids.append(sid)
        db.stores.insert_one(
            {
                "_id": sid,
                "name": f"{rng.choice(['Corner', 'Fresh', 'Neighborhood', 'Family'])} Market #{sid}",
                "address": _rand_address(rng),
                "created_at": now_ts(),
            }
        )

    for u in range(num_users):
        uid = alloc_id("users")
        uname = f"user_{uid}_{rng.randint(1000, 9999)}"
        db.users.insert_one(
            {
                "_id": uid,
                "username": uname,
                "password_hash": generate_password_hash(f"demo-{uid}"),
                "created_at": now_ts(),
            }
        )

    all_item_ids: list[int] = []
    for sid in store_ids:
        n_items = rng.randint(*items_per_store_range)
        chosen = rng.sample(PRODUCTS, min(n_items, len(PRODUCTS)))
        for name, desc in chosen:
            dept = rng.choice(DEPARTMENTS)
            price = round(rng.uniform(0.99, 24.99), 2)
            fid = alloc_id("food_items")
            barcode = str(8_900_000_000_000 + fid)
            db.food_items.insert_one(
                {
                    "_id": fid,
                    "name": name,
                    "description": desc,
                    "department": dept,
                    "sku_number": f"SKU-{fid:05d}",
                    "barcode": barcode,
                    "image_url": f"https://picsum.photos/seed/fi-{fid}/80",
                    "price": price,
                    "store_id": sid,
                    "created_at": now_ts(),
                }
            )
            all_item_ids.append(fid)

            n_lots = rng.randint(1, 3)
            for b in range(n_lots):
                lot_code = f"ST{sid}-I{fid}-B{b + 1}-{rng.randint(100, 999)}"
                received = now - datetime.timedelta(hours=rng.randint(1, 120))
                expires = now + datetime.timedelta(days=rng.randint(0, 14), hours=rng.randint(0, 12))
                lid = alloc_id("lots")
                db.lots.insert_one(
                    {
                        "_id": lid,
                        "store_id": sid,
                        "food_item_id": fid,
                        "lot_code": lot_code,
                        "received_at": received,
                        "expires_at": expires,
                        "quantity_label": rng.choice(["case", "unit", "6-pack", "1 lb", "dozen"]),
                        "notes": f"Filler lot · {dept}",
                        "created_at": now_ts(),
                    }
                )
                n_readings = rng.randint(1, 3)
                for _ in range(n_readings):
                    rid = alloc_id("sensor_readings")
                    rec_at = received + datetime.timedelta(hours=rng.randint(0, 48))
                    db.sensor_readings.insert_one(
                        {
                            "_id": rid,
                            "lot_id": lid,
                            "weight_g": round(rng.uniform(400, 2200), 1),
                            "temp_c": round(rng.uniform(2.0, 8.0), 1),
                            "humidity_rh": round(rng.uniform(40, 70), 1),
                            "voc_ppb": float(rng.randint(200, 900)),
                            "recorded_at": rec_at,
                            "created_at": now_ts(),
                        }
                    )

            if rng.random() < 0.35:
                pr_id = alloc_id("pricing_rules")
                db.pricing_rules.insert_one(
                    {
                        "_id": pr_id,
                        "food_item_id": fid,
                        "min_price": round(price * 0.4, 2),
                        "max_price": round(price * 1.2, 2),
                        "margin_floor_pct": float(rng.choice([8.0, 10.0, 12.0, 15.0])),
                        "created_at": now_ts(),
                    }
                )

    print("MongoDB populated (schema-aligned collections).")
    print(f"  stores: {db.stores.count_documents({})}")
    print(f"  users: {db.users.count_documents({})}")
    print(f"  food_items: {db.food_items.count_documents({})}")
    print(f"  lots: {db.lots.count_documents({})}")
    print(f"  sensor_readings: {db.sensor_readings.count_documents({})}")
    print(f"  pricing_rules: {db.pricing_rules.count_documents({})}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Fill MongoDB with random VitalShelf-shaped data.")
    ap.add_argument("--reset", action="store_true", help="Drop app collections and _counters, recreate indexes, then seed.")
    ap.add_argument("--stores", type=int, default=4)
    ap.add_argument("--users", type=int, default=6)
    ap.add_argument("--seed", type=int, default=None, help="RNG seed for reproducible data.")
    args = ap.parse_args()

    try:
        if args.reset:
            _reset_db()
        populate(num_stores=args.stores, num_users=args.users, seed=args.seed)
    except Exception as e:
        print("Error:", e, file=sys.stderr)
        sys.exit(1)
    finally:
        close_mongo_client()


if __name__ == "__main__":
    main()

"""Minimal demo catalog + one-store reset. Used by app seeding and scripts/reset_minimal_demo.py."""

from __future__ import annotations

import datetime as dt

from db_mongo import alloc_id, now_ts
from mongo_db import get_mongo_db

MINIMAL_CATALOG: list[tuple[str, str, str, float]] = [
    ("Bananas", "Organic bunches", "Produce", 0.79),
    ("Baby spinach", "5 oz clamshell", "Produce", 3.49),
    ("Whole milk 1 gal", "Vitamin D", "Dairy", 4.29),
]


def _barcode(item_id: int) -> str:
    return str(10_000_000_000 + int(item_id))


def _image_url(item_id: int) -> str:
    return f"https://picsum.photos/seed/sku-{int(item_id)}/80"


def clear_business_collections(db) -> None:
    """Remove store-scoped demo data and counters (users are kept)."""
    for name in (
        "food_items",
        "lots",
        "sensor_readings",
        "pricing_rules",
        "stores",
        "logs",
        "ingest_pending",
    ):
        db[name].delete_many({})
    db["_counters"].delete_many({})


def _seed_items_for_store(db, store_id: int) -> None:
    now = dt.datetime.now().replace(microsecond=0)
    food_item_ids: list[int] = []

    for name, desc, department, price in MINIMAL_CATALOG:
        fid = alloc_id("food_items")
        food_item_ids.append(fid)
        db.food_items.insert_one(
            {
                "_id": fid,
                "name": name,
                "description": desc,
                "department": department,
                "sku_number": None,
                "barcode": _barcode(fid),
                "image_url": _image_url(fid),
                "price": price,
                "store_id": store_id,
                "created_at": now_ts(),
            }
        )

        received = now - dt.timedelta(hours=18 + fid % 5)
        expires = now + dt.timedelta(days=4 + (fid % 3))
        days_left = max(0, (expires.date() - now.date()).days)
        lot_code = f"LOT-{store_id}-{fid}"
        lot_pk = alloc_id("lots")
        weight_grams = 780.0 + (fid % 4) * 95.0
        temperature_c = 3.2 + (fid % 3) * 0.6
        humidity_pct = 52.0 - (fid % 3) * 2.5
        ripeness = 2 + (fid % 4)
        recommended_price = round(float(price) * (0.92 if days_left > 2 else 0.85), 2)

        db.lots.insert_one(
            {
                "_id": lot_pk,
                "food_item_id": fid,
                "lot_code": lot_code,
                "lot_id": lot_code,
                "type": department,
                "weight_grams": weight_grams,
                "temperature_c": temperature_c,
                "humidity_pct": humidity_pct,
                "recommended_price": recommended_price,
                "ripeness": ripeness,
                "expiration": expires,
                "expires_at": expires,
                "days_left": days_left,
                "received_at": received,
                "quantity_label": "Primary batch",
                "notes": "Seeded minimal demo batch",
                "created_at": now_ts(),
            }
        )

        rid = alloc_id("sensor_readings")
        db.sensor_readings.insert_one(
            {
                "_id": rid,
                "lot_id": lot_pk,
                "weight_g": weight_grams,
                "temp_c": temperature_c,
                "humidity_rh": humidity_pct,
                "voc_ppb": 400 + (fid % 5) * 35,
                "recorded_at": now,
                "created_at": now_ts(),
            }
        )

    for fid in food_item_ids:
        fi = db.food_items.find_one({"_id": fid})
        base = float(fi.get("price") or 0) if fi else 0.0
        if base <= 0:
            continue
        pr_id = alloc_id("pricing_rules")
        db.pricing_rules.insert_one(
            {
                "_id": pr_id,
                "food_item_id": fid,
                "min_price": round(base * 0.35, 2),
                "max_price": round(base * 1.15, 2),
                "margin_floor_pct": 12.0,
                "created_at": now_ts(),
            }
        )


def seed_minimal_demo(db=None) -> int:
    """Clear business collections and create a single store with MINIMAL_CATALOG. Returns new store_id."""
    db = db or get_mongo_db()
    clear_business_collections(db)
    sid = alloc_id("stores")
    db.stores.insert_one(
        {
            "_id": sid,
            "name": "Demo Corner Store",
            "address": "",
            "created_at": now_ts(),
        }
    )
    _seed_items_for_store(db, sid)
    return sid


def seed_store_catalog_if_empty(store_id: int) -> bool:
    """If the store has no food_items yet, seed MINIMAL_CATALOG. Returns True if seeded."""
    db = get_mongo_db()
    if db.food_items.count_documents({"store_id": store_id}) > 0:
        return False
    _seed_items_for_store(db, store_id)
    return True

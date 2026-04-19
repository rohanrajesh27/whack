"""Demo data + banana pilot batches for store 1.

Pilot IDs (stable labels ``ST1-I1-B#-###``):

- ``STORE_PILOT_ID = 1``
- ``BANANA_ITEM_PILOT_ID = 1``

Each **lot** (batch) document includes:

  store_id, type, weight_grams, temperature_c, humidity_pct, recommended_price,
  discount_pct, ripeness, expiration, days_left, lot_id

plus ``food_item_id``, ``lot_code``, ``received_at``, ``expires_at``, ``created_at``, etc.
"""

from __future__ import annotations

import datetime as dt

from db_mongo import alloc_id, now_ts
from mongo_db import get_mongo_db

STORE_PILOT_ID = 1
BANANA_ITEM_PILOT_ID = 1

BANANA_PRODUCT: tuple[str, str, str, float] = ("Bananas", "Organic bunches", "Produce", 0.79)

_DISCOUNT_PCT_BY_RIPENESS: dict[int, float] = {1: 0.0, 2: 10.0, 3: 22.0, 4: 35.0, 5: 48.0}


def _barcode(item_id: int) -> str:
    return str(10_000_000_000 + int(item_id))


def _image_url(item_id: int) -> str:
    return f"https://picsum.photos/seed/sku-{int(item_id)}/80"


def clear_business_collections(db) -> None:
    """Remove store-scoped data and counters (users are kept)."""
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


def _sync_counters_from_collections(db) -> None:
    """Set ``_counters.seq`` to max ``_id`` per entity collection (keeps alloc_id sane after manual inserts)."""
    for entity, coll in (
        ("stores", "stores"),
        ("food_items", "food_items"),
        ("lots", "lots"),
        ("sensor_readings", "sensor_readings"),
        ("pricing_rules", "pricing_rules"),
    ):
        m = db[coll].find_one(sort=[("_id", -1)], projection={"_id": 1})
        seq = int(m["_id"]) if m else 0
        db["_counters"].replace_one({"_id": entity}, {"_id": entity, "seq": seq}, upsert=True)


def _batch_label(store_id: int, food_item_id: int, batch_index: int, suffix_three: int) -> str:
    """Pattern ST#-I#-B#-### (### is a three-digit suffix, e.g. 001)."""
    return f"ST{store_id}-I{food_item_id}-B{batch_index}-{suffix_three:03d}"


def _insert_lot_with_batch_schema(
    db,
    *,
    store_id: int,
    food_item_id: int,
    batch_index: int,
    suffix_three: int,
    now: dt.datetime,
    weight_grams: float,
    temperature_c: float,
    humidity_pct: float,
    base_price: float,
    ripeness: int,
    expiration: dt.datetime,
    received_at: dt.datetime,
) -> int:
    days_left = max(0, (expiration.date() - now.date()).days)
    label = _batch_label(store_id, food_item_id, batch_index, suffix_three)
    lot_pk = alloc_id("lots")
    disc = float(_DISCOUNT_PCT_BY_RIPENESS.get(int(ripeness), 22.0))
    recommended_price = round(float(base_price) * (1.0 - disc / 100.0), 2)
    db.lots.insert_one(
        {
            "_id": lot_pk,
            "store_id": int(store_id),
            "food_item_id": food_item_id,
            "lot_code": label,
            "lot_id": label,
            "type": "Banana",
            "weight_grams": weight_grams,
            "temperature_c": temperature_c,
            "humidity_pct": humidity_pct,
            "recommended_price": recommended_price,
            "ripeness": int(ripeness),
            "discount_pct": round(disc, 2),
            "expiration": expiration,
            "expires_at": expiration,
            "days_left": int(days_left),
            "received_at": received_at,
            "quantity_label": f"Banana batch {batch_index}",
            "notes": None,
            "created_at": now_ts(),
        }
    )
    db.sensor_readings.insert_one(
        {
            "_id": alloc_id("sensor_readings"),
            "lot_id": lot_pk,
            "weight_g": weight_grams,
            "temp_c": temperature_c,
            "humidity_rh": humidity_pct,
            "voc_ppb": 0,
            "recorded_at": now,
            "created_at": now_ts(),
        }
    )
    return lot_pk


def _insert_three_banana_lots(db, *, store_id: int, food_item_id: int, price: float) -> None:
    now = dt.datetime.now().replace(microsecond=0)
    specs = [
        (1, 1, 980.0, 4.0, 54.0, 2, now + dt.timedelta(days=5), now - dt.timedelta(hours=20)),
        (2, 2, 1020.0, 3.6, 56.0, 3, now + dt.timedelta(days=3), now - dt.timedelta(hours=14)),
        (3, 3, 890.0, 5.1, 48.0, 4, now + dt.timedelta(days=1), now - dt.timedelta(hours=8)),
    ]
    for batch_index, suffix_three, w, t, h, rip, exp, recv in specs:
        _insert_lot_with_batch_schema(
            db,
            store_id=store_id,
            food_item_id=food_item_id,
            batch_index=batch_index,
            suffix_three=suffix_three,
            now=now,
            weight_grams=w,
            temperature_c=t,
            humidity_pct=h,
            base_price=float(price),
            ripeness=rip,
            expiration=exp,
            received_at=recv,
        )


def _ensure_pricing_rule(db, food_item_id: int, price: float) -> None:
    db.pricing_rules.delete_many({"food_item_id": food_item_id})
    db.pricing_rules.insert_one(
        {
            "_id": alloc_id("pricing_rules"),
            "food_item_id": food_item_id,
            "min_price": round(float(price) * 0.35, 2),
            "max_price": round(float(price) * 1.15, 2),
            "margin_floor_pct": 12.0,
            "created_at": now_ts(),
        }
    )


def seed_minimal_demo(db=None) -> int:
    """Wipe business data; create store 1, banana SKU 1, three lots ``ST1-I1-B#-###``."""
    db = db or get_mongo_db()
    clear_business_collections(db)

    name, desc, department, price = BANANA_PRODUCT
    db.stores.insert_one(
        {
            "_id": STORE_PILOT_ID,
            "name": "Demo Corner Store",
            "address": "",
            "created_at": now_ts(),
        }
    )
    db.food_items.insert_one(
        {
            "_id": BANANA_ITEM_PILOT_ID,
            "name": name,
            "description": desc,
            "department": department,
            "sku_number": None,
            "barcode": _barcode(BANANA_ITEM_PILOT_ID),
            "image_url": _image_url(BANANA_ITEM_PILOT_ID),
            "price": price,
            "store_id": STORE_PILOT_ID,
            "created_at": now_ts(),
        }
    )
    _insert_three_banana_lots(db, store_id=STORE_PILOT_ID, food_item_id=BANANA_ITEM_PILOT_ID, price=float(price))
    _ensure_pricing_rule(db, BANANA_ITEM_PILOT_ID, float(price))
    _sync_counters_from_collections(db)
    return STORE_PILOT_ID


def reseed_banana_lots_for_store(db=None, store_id: int = STORE_PILOT_ID) -> bool:
    """If you only deleted ``lots``: recreate three banana batches for that store's banana SKU."""
    db = db or get_mongo_db()
    fi = db.food_items.find_one(
        {"store_id": store_id, "name": {"$regex": "banana", "$options": "i"}}
    )
    if fi is None:
        return False
    fid = int(fi["_id"])
    lids = [x["_id"] for x in db.lots.find({"food_item_id": fid}, {"_id": 1})]
    if lids:
        db.sensor_readings.delete_many({"lot_id": {"$in": lids}})
    db.lots.delete_many({"food_item_id": fid})
    price = float(fi.get("price") or 0.79)
    _insert_three_banana_lots(db, store_id=store_id, food_item_id=fid, price=price)
    _sync_counters_from_collections(db)
    return True


def seed_store_catalog_if_empty(store_id: int) -> bool:
    """If the store has no food_items yet, seed banana pilot (expects store 1 pilot layout after reset)."""
    db = get_mongo_db()
    if db.food_items.count_documents({"store_id": store_id}) > 0:
        return False
    name, desc, department, price = BANANA_PRODUCT
    fid = alloc_id("food_items")
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
    _insert_three_banana_lots(db, store_id=store_id, food_item_id=fid, price=float(price))
    _ensure_pricing_rule(db, fid, float(price))
    _sync_counters_from_collections(db)
    return True

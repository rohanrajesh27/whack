"""MongoDB persistence: collections mirror former SQLite tables; integer _id for URL/session compatibility."""

from __future__ import annotations

import datetime as dt

from pymongo import ASCENDING, DESCENDING, ReturnDocument

from mongo_db import get_mongo_db

COUNTERS = "_counters"


def alloc_id(entity: str) -> int:
    db = get_mongo_db()
    doc = db[COUNTERS].find_one_and_update(
        {"_id": entity},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(doc["seq"])


def init_mongo() -> None:
    """Idempotent indexes (call once per process / first request).

    ``lots`` = **batches**. Canonical batch fields (see ``demo_seed`` module docstring):

    ``type``, ``weight_grams``, ``temperature_c``, ``humidity_pct``,
    ``recommended_price``, ``discount_pct`` (markdown from ripeness), ``ripeness``,
    ``expiration``, ``days_left``, ``lot_id``

    plus ``food_item_id``, ``lot_code``, ``received_at``, ``expires_at`` (mirror of
    ``expiration`` where used), ``created_at``, optional ``quantity_label`` / ``notes``.
    """
    db = get_mongo_db()
    db.users.create_index("username", unique=True)
    db.stores.create_index([("name", ASCENDING)])
    db.food_items.create_index("store_id")
    db.food_items.create_index([("store_id", ASCENDING), ("department", ASCENDING)])
    db.lots.create_index("food_item_id")
    db.lots.create_index("store_id")
    db.lots.create_index([("food_item_id", ASCENDING), ("lot_code", ASCENDING)], unique=True)
    db.lots.create_index(
        "lot_id",
        partialFilterExpression={"lot_id": {"$type": "string", "$gt": ""}},
    )
    db.sensor_readings.create_index("lot_id")
    db.sensor_readings.create_index([("lot_id", ASCENDING), ("recorded_at", DESCENDING)])
    db.pricing_rules.create_index("food_item_id", unique=True)
    db.food_items.create_index(
        [("barcode", ASCENDING)],
        unique=True,
        partialFilterExpression={"barcode": {"$type": "string", "$gt": ""}},
    )


def now_ts() -> dt.datetime:
    return dt.datetime.now().replace(microsecond=0)

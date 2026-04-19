from flask import Flask, render_template, redirect, url_for, request, flash, session, send_from_directory, jsonify
import os

try:
    from dotenv import load_dotenv
    load_dotenv()  # Load environment variables from .env
except ImportError:
    pass

import hashlib
import os
import random
import re
import datetime
from collections import defaultdict
from functools import wraps
from typing import Optional

from pymongo.errors import DuplicateKeyError
from werkzeug.security import generate_password_hash

import dc_grocery
from demo_seed import seed_store_catalog_if_empty
from mongo_db import get_mongo_db
from db_mongo import alloc_id, init_mongo, now_ts

import PricingAlgo as _PA
import RestockAlgo as _RA

from dotenv import load_dotenv

app = Flask("app")
# Treat `https://host//logs` like `/logs` (path rule matching); requires Flask 2.2+.
app.config["MERGE_SLASHES"] = True
FLASK_ENV = "development"
app.secret_key = "CHANGE ME"


def _with_id(doc):
    """Expose Mongo _id as id for templates (SQLite compatibility)."""
    if doc is None:
        return None
    d = dict(doc)
    if "_id" in d:
        d["id"] = d.pop("_id")
    return d


_LOGS_MAX_ENTRIES = 100
# Next POST with flag=0 (telemetry app) is merged into one log row with the latest flag=1 camera POST.
INGEST_PENDING_DOC_ID = "pending_camera"


def _trim_logs_collection(coll) -> None:
    """Remove oldest documents so ``logs`` stays at most ``_LOGS_MAX_ENTRIES`` rows."""
    n = coll.count_documents({})
    if n <= _LOGS_MAX_ENTRIES:
        return
    excess = n - _LOGS_MAX_ENTRIES
    ids = [doc["_id"] for doc in coll.find({}, {"_id": 1}).sort("ts", 1).limit(excess)]
    if ids:
        coll.delete_many({"_id": {"$in": ids}})


def _payload_flag_value(payload) -> Optional[int]:
    """First-field ``flag`` value (0 or 1) if present, else None."""
    if not isinstance(payload, dict) or not payload:
        return None
    first_key, first_val = next(iter(payload.items()))
    if first_key != "flag" or first_val not in (0, 1):
        return None
    return int(first_val)


def _coalesce_int(*vals: object) -> Optional[int]:
    for v in vals:
        if v is None or isinstance(v, bool):
            continue
        try:
            return int(v)
        except (TypeError, ValueError):
            continue
    return None


def _coalesce_float(*vals: object) -> Optional[float]:
    for v in vals:
        if v is None or isinstance(v, bool):
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def merge_camera_and_telemetry_to_batch(camera: dict, telemetry: dict) -> dict:
    """Strip ``flag`` and build one batch-shaped dict (lot / shelf fields for DB or UI)."""
    c = {k: v for k, v in camera.items() if k != "flag"}
    s = {k: v for k, v in telemetry.items() if k != "flag"}

    lot_id = s.get("lot_id") or s.get("lot_code") or c.get("lot_id") or c.get("lot_code") or c.get("product_code")
    product_code = c.get("product_code") or s.get("product_code") or lot_id
    if lot_id is None and product_code:
        lot_id = product_code
    if product_code is None and lot_id:
        product_code = lot_id

    ripeness = _coalesce_int(
        s.get("ripeness"),
        c.get("ripeness_score"),
        s.get("ripeness_score"),
        c.get("ripeness"),
    )

    weight_grams = _coalesce_float(s.get("weight_grams"), s.get("weight_g"), c.get("weight_grams"), c.get("weight_g"))
    temperature_c = _coalesce_float(s.get("temperature_c"), s.get("temp_c"), c.get("temperature_c"), c.get("temp_c"))
    humidity_pct = _coalesce_float(
        s.get("humidity_pct"), s.get("humidity_rh"), c.get("humidity_pct"), c.get("humidity_rh")
    )
    recommended_price = _coalesce_float(
        s.get("recommended_price"),
        s.get("recommended"),
        c.get("recommended_price"),
    )

    batch_type = s.get("type") or s.get("product_type") or c.get("type")

    expiration = s.get("expiration") or s.get("expires_at") or c.get("expiration") or c.get("expires_at")
    days_left = _coalesce_int(s.get("days_left"), c.get("days_left"))
    if days_left is None and expiration is not None:
        exp_dt = expiration if isinstance(expiration, datetime.datetime) else parse_storage_datetime(str(expiration))
        if exp_dt is not None:
            days_left = max(0, (exp_dt.date() - datetime.datetime.now().date()).days)

    return {
        "lot_id": lot_id,
        "product_code": product_code,
        "type": batch_type,
        "weight_grams": weight_grams,
        "temperature_c": temperature_c,
        "humidity_pct": humidity_pct,
        "recommended_price": recommended_price,
        "ripeness": ripeness,
        "expiration": expiration,
        "days_left": days_left,
    }


# Keys persisted on ``/logs`` for merged ingest (no ``discount_pct``, ``lot_match``, etc.).
BATCH_LOG_KEYS: tuple[str, ...] = (
    "store_id",
    "lot_id",
    "product_code",
    "type",
    "weight_grams",
    "temperature_c",
    "humidity_pct",
    "recommended_price",
    "ripeness",
    "expiration",
    "days_left",
)


def sanitize_batch_for_log(batch: dict) -> dict:
    """Keep only canonical batch fields for log storage / display."""
    out: dict = {}
    for k in BATCH_LOG_KEYS:
        v = batch.get(k)
        if isinstance(v, datetime.datetime):
            v = v.replace(microsecond=0).isoformat(sep=" ")
        out[k] = v
    return out


@app.route("/logs")
def logs():
    """Show merged camera + telemetry rows (newest pairs last in chronological list)."""
    db = get_mongo_db()
    logs_collection = db["logs"]

    entries = logs_collection.find().sort("ts", 1)
    results = []
    for entry in entries:
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        if "batch" in payload and isinstance(payload.get("batch"), dict):
            results.append(
                {
                    "kind": "batch",
                    "ts": entry.get("ts"),
                    "batch": sanitize_batch_for_log(payload["batch"]),
                    "lot_update": entry.get("lot_update"),
                }
            )
            continue
        if "camera" in payload and "sensor" in payload:
            results.append(
                {
                    "kind": "pair",
                    "ts": entry.get("ts"),
                    "camera": payload["camera"],
                    "sensor": payload["sensor"],
                }
            )
            continue
        if "sensor" in payload and "camera" not in payload:
            results.append(
                {
                    "kind": "sensor_only",
                    "ts": entry.get("ts"),
                    "sensor": payload.get("sensor"),
                }
            )
            continue
        flag_val = _payload_flag_value(payload)
        if flag_val is not None:
            results.append(
                {
                    "kind": "flat",
                    "ts": entry.get("ts"),
                    "flag": flag_val,
                    "payload": payload,
                }
            )
    return render_template("logs.html", logs=results)

@app.route('/receive-data', methods=['POST'])
def receive_data():
    if not request.is_json:
        return jsonify(status='error', message='Request must be JSON'), 400

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data:
        return jsonify(status='error', message='JSON body must be a non-empty object'), 400

    first_key, first_val = next(iter(data.items()))
    if first_key == "flag" and first_val == 1:
        try:
            get_mongo_db()["ingest_pending"].replace_one(
                {"_id": INGEST_PENDING_DOC_ID},
                {"_id": INGEST_PENDING_DOC_ID, "payload": dict(data), "ts": now_ts()},
                upsert=True,
            )
        except Exception:
            pass
        return render_template("receive_data_display.html", payload=data)

    if first_key == "flag" and first_val == 0:
        # Only the first flag=0 after a flag=1 is logged (one merged row). Orphan flag=0 posts are ignored.
        merged_ok = False
        lot_status: Optional[str] = None
        try:
            db = get_mongo_db()
            pend = db["ingest_pending"].find_one({"_id": INGEST_PENDING_DOC_ID})
            if pend and isinstance(pend.get("payload"), dict):
                coll = db["logs"]
                batch = merge_camera_and_telemetry_to_batch(dict(pend["payload"]), dict(data))
                batch, lot_status = apply_batch_merge_to_lot(db, batch)
                coll.insert_one(
                    {
                        "ts": now_ts(),
                        "payload": {"batch": sanitize_batch_for_log(batch)},
                        "lot_update": lot_status,
                    }
                )
                _trim_logs_collection(coll)
                db["ingest_pending"].delete_one({"_id": INGEST_PENDING_DOC_ID})
                merged_ok = True
        except Exception:
            pass
        if merged_ok:
            return jsonify(
                status="success",
                message="Logged batch and updated lot if matched.",
                lot_update=lot_status,
            ), 200
        return jsonify(status="success", message="No pending camera capture; telemetry not logged."), 200

    # Legacy: pinger-style payloads (weight + message)
    if 'weight' in data and 'message' in data:
        return jsonify(
            status='success',
            weight=data.get('weight'),
            message=data.get('message'),
        ), 200

    return jsonify(
        status="error",
        message='First JSON field must be "flag" with value 0 or 1, or send weight and message.',
    ), 400


@app.before_request
def _ensure_mongo():
    if not getattr(app, "_mongo_ready", False):
        init_mongo()
        app._mongo_ready = True


def login_required(view_func):
    @wraps(view_func)
    def _wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return _wrapped


def get_or_create_user(username, password=None):
    uname = (username or "").strip() or "demo"
    pw = password or "demo"

    db = get_mongo_db()
    existing = db.users.find_one({"username": uname})
    if existing is not None:
        return int(existing["_id"])

    uid = alloc_id("users")
    db.users.insert_one(
        {
            "_id": uid,
            "username": uname,
            "password_hash": generate_password_hash(pw),
            "created_at": now_ts(),
        }
    )
    return uid


def parse_optional_float(value):
    if value is None:
        return None
    value = value.strip()
    if value == "":
        return None
    return float(value)


def parse_optional_int(value):
    if value is None:
        return None
    value = value.strip()
    if value == "":
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def parse_optional_datetime_local(value):
    if value is None:
        return None
    value = value.strip()
    if value == "":
        return None
    return datetime.datetime.fromisoformat(value)


def to_storage_datetime(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    return dt.replace(microsecond=0).isoformat(sep=" ")


def parse_storage_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value
    s = str(value).strip()
    if s == "":
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace(" ", "T"))
    except ValueError:
        return None


# Ripeness 1 = very fresh (no markdown), 5 = end of life (heavier markdown). Drives shelf ``days_left`` when absent.
_DISCOUNT_PCT_BY_RIPENESS: dict[int, float] = {1: 0.0, 2: 10.0, 3: 22.0, 4: 35.0, 5: 48.0}
_DAYSLEFT_BY_RIPENESS: dict[int, int] = {1: 7, 2: 5, 3: 4, 4: 2, 5: 0}


def _normalize_lot_label(value) -> str:
    """Strip whitespace and stray trailing commas from batch labels (bad paste / exports)."""
    if value is None:
        return ""
    s = str(value).strip()
    while s.endswith(","):
        s = s[:-1].strip()
    return s


def _dedupe_lots_for_display(lots_list: list) -> list:
    """Keep one row per (food_item_id, normalized lot label), preferring the newest by received_at then _id."""
    buckets: dict[tuple[int, str], list] = defaultdict(list)
    for lot in lots_list:
        fid = int(lot["food_item_id"])
        label = _normalize_lot_label(lot.get("lot_code") or lot.get("lot_id") or "")
        key = (fid, label or f"_id:{lot['_id']}")
        buckets[key].append(lot)

    def _recv_ts(lx: dict) -> datetime.datetime:
        r = lx.get("received_at")
        if isinstance(r, datetime.datetime):
            return r
        if r is not None:
            pd = parse_storage_datetime(r)
            if pd is not None:
                return pd
        return datetime.datetime.min

    out: list = []
    for group in buckets.values():
        if len(group) == 1:
            out.append(group[0])
            continue
        out.append(
            sorted(
                group,
                key=lambda lx: (_recv_ts(lx), int(lx["_id"])),
                reverse=True,
            )[0]
        )
    return out


def _batch_code_lookup_clauses(key: str) -> list[dict]:
    """Build ``$or`` clauses so ``ST1-I1-…`` lots match OCR-normalised ``ST1-11-…`` (I→1) keys."""
    k = _normalize_lot_label(key)
    if not k:
        return []
    clauses: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(v: str) -> None:
        v = v.strip()
        if not v:
            return
        for fld in ("lot_code", "lot_id"):
            t = (fld, v)
            if t not in seen:
                seen.add(t)
                clauses.append({fld: v})

    ku = k.upper().replace(" ", "")
    add(k)
    if ku != k:
        add(ku)
    m = re.fullmatch(r"(ST\d+)-11-(B\d+-\d{3})", ku)
    if m:
        add(f"{m.group(1)}-I1-{m.group(2)}")
    m2 = re.fullmatch(r"(ST\d+)-I1-(B\d+-\d{3})", ku, flags=re.IGNORECASE)
    if m2:
        add(f"{m2.group(1)}-11-{m2.group(2)}")
    return clauses


def _find_lot_by_batch_key(db, key: str):
    if not key or not str(key).strip():
        return None
    clauses = _batch_code_lookup_clauses(key)
    if not clauses:
        return None
    lot = db.lots.find_one({"$or": clauses})
    if lot is None and key:
        pattern = re.compile(r"^\s*" + re.escape(key) + r",?\s*$", re.IGNORECASE)
        lot = db.lots.find_one({"$or": [{"lot_code": pattern}, {"lot_id": pattern}]})
    return lot


_RIPENESS_TO_VISUAL_MULT: dict[int, float] = {1: 0.7, 2: 0.85, 3: 1.0, 4: 1.3, 5: 1.7}


def _pricing_algo_for_lot(lot_doc: dict, weight_g, temp_c, humidity_pct, ripeness):
    """Run PricingAlgo with real sensor readings. Returns PricingResult or None on failure."""
    try:
        received_at = lot_doc.get("received_at") or datetime.datetime.now()
        if not isinstance(received_at, datetime.datetime):
            received_at = parse_storage_datetime(received_at) or datetime.datetime.now()
        age_days = max(0.0, (datetime.datetime.now() - received_at).total_seconds() / 86400.0)

        r = max(1, min(5, int(ripeness or 3)))
        _PA.VISUAL_AGE_MULTIPLIER = _RIPENESS_TO_VISUAL_MULT.get(r, 1.0)

        init_w = float(weight_g or _PA.INITIAL_WEIGHT_G)
        t = float(temp_c or _PA.TEMPERATURE_C)
        h = float(humidity_pct or _PA.HUMIDITY_PCT)
        now_ts_f = age_days * 86400.0

        lot_state = _PA.LotState(
            lot_id=str(lot_doc.get("lot_code") or lot_doc["_id"]),
            registered_at=0.0,
            initial_weight_g=init_w,
        )
        if age_days > 0:
            lot_state.add_reading(_PA.SensorReading(0.0, init_w, t, h))
        lot_state.add_reading(_PA.SensorReading(now_ts_f, init_w, t, h))
        return _PA.compute_shelf_price(lot_state, now=now_ts_f)
    except Exception:
        return None


def _restock_algo_for_lot(current_price, weight_g):
    """Run RestockAlgo using weight-derived stock estimate. Returns RestockResult or None."""
    try:
        est_stock = max(1, int(round(float(weight_g) / 120.0))) if weight_g else _RA.CURRENT_STOCK_UNITS
        _RA.CURRENT_STOCK_UNITS = est_stock
        return _RA.compute_restock(float(current_price or _RA.REFERENCE_PRICE))
    except Exception:
        return None


def apply_batch_merge_to_lot(db, batch: dict) -> tuple[dict, str]:
    """If ``lot_id`` / ``product_code`` matches a banana lot, enrich + ``$set`` batch fields (never ``type``)."""
    key = _normalize_lot_label(batch.get("lot_id") or batch.get("product_code") or "")
    if not key:
        out = dict(batch)
        out["lot_match"] = False
        return out, "missing_batch_key"

    lot = _find_lot_by_batch_key(db, key)
    if lot is None:
        out = dict(batch)
        out["lot_match"] = False
        return out, "lot_not_found"

    canonical = (
        _normalize_lot_label(lot.get("lot_code"))
        or _normalize_lot_label(lot.get("lot_id"))
        or key
    )

    fi = db.food_items.find_one({"_id": lot["food_item_id"]})
    if fi is None or "banana" not in (fi.get("name") or "").lower():
        out = dict(batch)
        out["lot_match"] = False
        return out, "not_banana_sku"

    r_raw = batch.get("ripeness")
    if r_raw is None:
        r = 3
    else:
        try:
            r = int(round(float(r_raw)))
        except (TypeError, ValueError):
            r = 3
        r = max(1, min(5, r))

    dl = batch.get("days_left")
    if dl is None:
        days_left = int(_DAYSLEFT_BY_RIPENESS.get(r, 4))
    else:
        try:
            days_left = max(0, int(dl))
        except (TypeError, ValueError):
            days_left = int(_DAYSLEFT_BY_RIPENESS.get(r, 4))

    base_price = float(fi.get("price") or 0.0)
    pr = db.pricing_rules.find_one({"food_item_id": fi["_id"]})

    pricing_result = _pricing_algo_for_lot(
        lot,
        batch.get("weight_grams"),
        batch.get("temperature_c"),
        batch.get("humidity_pct"),
        r,
    )
    if pricing_result is not None:
        freshness_score = pricing_result.freshness_score
        multiplier = pricing_result.multiplier
        if base_price > 0:
            rec = round(base_price * multiplier, 2)
        else:
            rec = pricing_result.final_price
        discount_pct = round((1.0 - multiplier) * 100.0, 1)
    else:
        freshness_score = None
        discount_pct = float(_DISCOUNT_PCT_BY_RIPENESS.get(r, 22.0))
        rec = round(base_price * (1.0 - discount_pct / 100.0), 2)

    if pr is not None:
        mn, mx = pr.get("min_price"), pr.get("max_price")
        if mn is not None and rec < float(mn):
            rec = float(mn)
        if mx is not None and rec > float(mx):
            rec = float(mx)

    restock_result = _restock_algo_for_lot(rec, batch.get("weight_grams"))

    now = datetime.datetime.now().replace(microsecond=0)
    exp_dt = now + datetime.timedelta(days=days_left)

    out = dict(batch)
    out["lot_id"] = canonical
    out["product_code"] = canonical
    out["ripeness"] = r
    out["discount_pct"] = round(discount_pct, 2)
    out["recommended_price"] = rec
    out["days_left"] = days_left
    out["expiration"] = exp_dt.isoformat(sep=" ")
    out["lot_match"] = True
    out["freshness_score"] = freshness_score
    if restock_result is not None:
        out["restock_alert_level"] = restock_result.alert_level
        out["restock_message"] = restock_result.alert_message
        out["suggested_order_qty"] = restock_result.suggested_order_qty
        out["stockout_risk_pct"] = restock_result.stockout_risk_pct
    sid = fi.get("store_id")
    if sid is not None:
        out["store_id"] = int(sid)

    set_doc: dict = {
        "recommended_price": rec,
        "discount_pct": round(discount_pct, 2),
        "ripeness": r,
        "days_left": days_left,
        "expiration": exp_dt,
        "expires_at": exp_dt,
        "lot_id": canonical,
        "lot_code": canonical,
    }
    if freshness_score is not None:
        set_doc["freshness_score"] = freshness_score
    if restock_result is not None:
        set_doc["restock_alert_level"] = restock_result.alert_level
        set_doc["restock_message"] = restock_result.alert_message
        set_doc["suggested_order_qty"] = restock_result.suggested_order_qty
        set_doc["stockout_risk_pct"] = restock_result.stockout_risk_pct
    if sid is not None:
        set_doc["store_id"] = int(sid)
    for fld in ("weight_grams", "temperature_c", "humidity_pct"):
        v = out.get(fld)
        if v is not None:
            set_doc[fld] = v
    db.lots.update_one({"_id": lot["_id"]}, {"$set": set_doc})

    wg = out.get("weight_grams")
    tc = out.get("temperature_c")
    hp = out.get("humidity_pct")
    if wg is not None or tc is not None or hp is not None:
        db.sensor_readings.insert_one(
            {
                "_id": alloc_id("sensor_readings"),
                "lot_id": lot["_id"],
                "weight_g": wg,
                "temp_c": tc,
                "humidity_rh": hp,
                "voc_ppb": 0,
                "recorded_at": now,
                "created_at": now_ts(),
            }
        )

    return out, "lot_updated"


def format_datetime_for_store_users(value):
    dt = parse_storage_datetime(value)
    if dt is None:
        return None
    # Example: "Apr 20, 11:16 AM"
    return dt.strftime("%b %-d, %-I:%M %p") if hasattr(dt, "strftime") else str(value)


def format_date_for_store_users(value):
    dt = parse_storage_datetime(value)
    if dt is None:
        return None
    return dt.strftime("%b %-d")


def abbreviate_product_name(name, max_len=20):
    if name is None:
        return ""
    s = str(name).strip()
    if len(s) <= max_len:
        return s
    return s[: max(0, max_len - 1)].rstrip() + "…"


def generate_barcode_for_item_id(item_id):
    # 12-digit demo barcode, stable per item_id.
    return str(10_000_000_000 + int(item_id))


def generate_image_url_for_item_id(item_id):
    # Deterministic placeholder image per item_id.
    return f"https://picsum.photos/seed/sku-{int(item_id)}/80"


def compute_markdown_recommendation(base_price, days_left):
    if base_price is None:
        return {"status": "missing_price", "recommended_price": None, "label": "Set price"}
    if days_left is None:
        return {"status": "missing_expiry", "recommended_price": base_price, "label": "Add expiry"}
    if days_left <= 0:
        return {"status": "expired", "recommended_price": 0.0, "label": "Remove/Donate"}
    if days_left <= 1:
        return {"status": "urgent", "recommended_price": round(base_price * 0.5, 2), "label": "50% off today"}
    if days_left <= 2:
        return {"status": "soon", "recommended_price": round(base_price * 0.75, 2), "label": "25% off soon"}
    return {"status": "ok", "recommended_price": base_price, "label": "Full price"}


def city_admin_required(view_func):
    @wraps(view_func)
    def _wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        if not session.get("city_admin"):
            flash("City-wide metrics require logging in as master.", "error")
            return redirect(url_for("dashboard", store_id=session.get("store_id") or get_or_create_default_store()))
        return view_func(*args, **kwargs)

    return _wrapped


def get_city_health_metrics():
    """Aggregate demo + DB-backed metrics for city-wide food health (spoilage, markdowns, freshness)."""
    db = get_mongo_db()
    store_count = db.stores.count_documents({})

    rows = []
    for lot in db.lots.find():
        fi = db.food_items.find_one({"_id": lot["food_item_id"]})
        if fi is None:
            continue
        rows.append({"expires_at": lot.get("expires_at"), "price": fi.get("price")})

    now = datetime.datetime.now()
    status_counts = {
        "expired": 0,
        "urgent": 0,
        "soon": 0,
        "ok": 0,
        "missing_price": 0,
        "missing_expiry": 0,
    }
    markdown_mix = {"full_price": 0, "markdown_25": 0, "markdown_50": 0, "remove_donate": 0}

    for r in rows:
        price = r["price"]
        expires_at = r["expires_at"]
        days_left = None
        if expires_at:
            exp_dt = parse_storage_datetime(expires_at)
            if exp_dt is not None:
                days_left = (exp_dt.date() - now.date()).days
        rec = compute_markdown_recommendation(price, days_left)
        st = rec["status"]
        if st == "expired":
            status_counts["expired"] += 1
            markdown_mix["remove_donate"] += 1
        elif st == "urgent":
            status_counts["urgent"] += 1
            markdown_mix["markdown_50"] += 1
        elif st == "soon":
            status_counts["soon"] += 1
            markdown_mix["markdown_25"] += 1
        elif st == "ok":
            status_counts["ok"] += 1
            markdown_mix["full_price"] += 1
        elif st == "missing_price":
            status_counts["missing_price"] += 1
        else:
            status_counts["missing_expiry"] += 1
            markdown_mix["full_price"] += 1

    total_lots = len(rows)
    spoilage_at_risk = status_counts["expired"] + status_counts["urgent"]
    discount_active = status_counts["urgent"] + status_counts["soon"]
    freshness_ok_pct = round(100.0 * status_counts["ok"] / total_lots, 1) if total_lots else 0.0

    # Synthetic weekly trend (seeded so charts are stable; scales with observed totals)
    seed = int(hashlib.md5(str(store_count).encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    weeks = 12
    labels = []
    spoilage_series = []
    discount_series = []
    affordability_proxy = []
    base_s = max(2.0, float(spoilage_at_risk or 1) * 1.2)
    base_d = max(2.0, float(discount_active or 1) * 1.2)
    for w in range(weeks):
        labels.append(f"W{w + 1}")
        spoilage_series.append(round(base_s * (0.65 + 0.55 * rng.random()) + w * 0.25, 1))
        discount_series.append(round(base_d * (0.75 + 0.45 * rng.random()) + w * 0.3, 1))
        affordability_proxy.append(round(58 + 22 * rng.random() + min(w * 0.4, 8), 1))

    return {
        "store_count": store_count,
        "total_lots": total_lots,
        "status_counts": status_counts,
        "markdown_mix": markdown_mix,
        "kpis": {
            "spoilage_at_risk": spoilage_at_risk,
            "discount_lots": discount_active,
            "freshness_ok_pct": freshness_ok_pct,
            "expired_lots": status_counts["expired"],
        },
        "weekly": {
            "labels": labels,
            "spoilage_index": spoilage_series,
            "discount_velocity": discount_series,
            "affordability_index": affordability_proxy,
        },
    }


def get_or_create_default_store():
    db = get_mongo_db()
    first = db.stores.find_one(sort=[("_id", 1)])
    if first is not None:
        return int(first["_id"])
    sid = alloc_id("stores")
    db.stores.insert_one({"_id": sid, "name": "Demo Corner Store", "address": "", "created_at": now_ts()})
    return sid


def _seed_store_catalog(store_id, variant_index=0):
    """Insert minimal SKUs + batches (see demo_seed) if this store has no items. variant_index ignored."""
    return seed_store_catalog_if_empty(store_id)


def _store_has_items(store_id):
    db = get_mongo_db()
    return db.food_items.count_documents({"store_id": store_id}) > 0


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route('/')
def home():
    if session.get("user_id"):
        if session.get("city_admin"):
            return redirect(url_for("city_health"))
        store_id = session.get("store_id") or get_or_create_default_store()
        session["store_id"] = store_id
        return redirect(url_for("dashboard", store_id=store_id))
    return render_template("login.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get("user_id"):
            if session.get("city_admin"):
                return redirect(url_for("city_health"))
            store_id = session.get("store_id") or get_or_create_default_store()
            session["store_id"] = store_id
            return redirect(url_for("dashboard", store_id=store_id))
        return render_template("login.html")

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""

    # City-wide metrics login (master / master)
    if username == "master" and password == "master":
        user_id = get_or_create_user("master", "master")
        session["user_id"] = user_id
        session["city_admin"] = True
        store_id = get_or_create_default_store()
        session["store_id"] = store_id
        flash("City-wide dashboard (master access).", "success")
        return redirect(url_for("city_health"))

    session["city_admin"] = False

    # Demo behavior (for now): accept any credentials and proceed.
    user_id = get_or_create_user(username or "demo", password or "demo")
    session["user_id"] = user_id
    store_id = get_or_create_default_store()
    session["store_id"] = store_id
    flash("Logged in (demo).", "success")
    return redirect(url_for("dashboard", store_id=store_id))


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("home"))


@app.route("/city")
@city_admin_required
def city_health():
    metrics = get_city_health_metrics()
    map_bundle = dc_grocery.get_dc_grocery_pins()
    return render_template(
        "city_health.html",
        metrics=metrics,
        map_pins=map_bundle.get("pins") or [],
        map_meta={
            "source": map_bundle.get("source"),
            "fetched_at": map_bundle.get("fetched_at"),
            "health_weights": dc_grocery.get_health_factor_weights(),
            "health_factor_labels": {
                "freshness_uptime": "Freshness & shelf-life",
                "markdown_discipline": "Markdown discipline",
                "cold_chain_stability": "Cold-chain stability",
                "community_access": "Community & SNAP fit",
            },
        },
    )


@app.route("/dashboard")
@login_required
def dashboard():
    store_id = request.args.get("store_id", type=int) or session.get("store_id") or get_or_create_default_store()
    session["store_id"] = store_id
    selected_department = (request.args.get("department") or "").strip() or None
    selected_food_item_id = request.args.get("food_item_id", type=int)
    sku_sort = (request.args.get("sku_sort") or "").strip() or "created"

    db = get_mongo_db()

    store_doc = db.stores.find_one({"_id": store_id})
    if store_doc is None:
        store_doc = db.stores.find_one(sort=[("_id", 1)])
        if store_doc is not None:
            store_id = int(store_doc["_id"])
            session["store_id"] = store_id
        else:
            store_id = get_or_create_default_store()
            session["store_id"] = store_id
            return redirect(url_for("dashboard", store_id=store_id))
    store = _with_id(store_doc)

    raw_depts = db.food_items.distinct("department", {"store_id": store_id})
    departments = sorted(
        {str(d).strip() for d in raw_depts if d is not None and str(d).strip() != ""}
    )

    po_query: dict = {"store_id": store_id}
    if selected_department:
        po_query["department"] = selected_department
    product_options = [
        _with_id(x)
        for x in db.food_items.find(po_query, {"name": 1, "department": 1}).sort("name", 1)
    ]

    sku_query: dict = {"store_id": store_id}
    if selected_department:
        sku_query["department"] = selected_department
    sku_items = list(db.food_items.find(sku_query))
    if sku_sort == "department":
        sku_items.sort(key=lambda x: ((x.get("department") or ""), (x.get("name") or "")))
    else:
        sku_items.sort(
            key=lambda x: x.get("created_at") or datetime.datetime.min,
            reverse=True,
        )

    skus = []
    for fi in sku_items:
        fid = fi["_id"]
        _lq = {
            "food_item_id": fid,
            "$or": [{"store_id": store_id}, {"store_id": {"$exists": False}}],
        }
        total_lots = len(_dedupe_lots_for_display(list(db.lots.find(_lq))))
        skus.append(
            {
                "food_item_id": fid,
                "item_name": fi.get("name"),
                "item_name_short": abbreviate_product_name(fi.get("name"), 18),
                "item_description": fi.get("description"),
                "department": fi.get("department"),
                "sku_number": fi.get("sku_number"),
                "barcode": fi.get("barcode"),
                "image_url": fi.get("image_url"),
                "base_price": fi.get("price"),
                "total_lots": total_lots,
            }
        )

    now = datetime.datetime.now()
    inv_fi_query: dict = {"store_id": store_id}
    if selected_department:
        inv_fi_query["department"] = selected_department
    if selected_food_item_id:
        inv_fi_query["_id"] = selected_food_item_id
    inv_fitems = list(db.food_items.find(inv_fi_query))
    fi_by_id = {f["_id"]: f for f in inv_fitems}
    if not fi_by_id:
        lots_for_inv = []
    else:
        _lot_store_filter = {
            "food_item_id": {"$in": list(fi_by_id.keys())},
            "$or": [{"store_id": store_id}, {"store_id": {"$exists": False}}],
        }
        lots_for_inv = _dedupe_lots_for_display(list(db.lots.find(_lot_store_filter)))

    def _exp_sort_key(lot):
        ex = lot.get("expires_at")
        if ex is None:
            return (1, datetime.datetime.max)
        if isinstance(ex, datetime.datetime):
            dt = ex
        else:
            dt = parse_storage_datetime(ex) or datetime.datetime.max
        return (0, dt)

    lots_for_inv.sort(key=_exp_sort_key)
    lots_for_inv = lots_for_inv[:200]

    inventory_rows = []
    for lot in lots_for_inv:
        fi = fi_by_id.get(lot["food_item_id"])
        if fi is None:
            continue
        pr = db.pricing_rules.find_one({"food_item_id": fi["_id"]})
        min_price = pr.get("min_price") if pr else None
        max_price = pr.get("max_price") if pr else None

        sr = db.sensor_readings.find_one({"lot_id": lot["_id"]}, sort=[("recorded_at", -1)])
        latest_weight_g = lot.get("weight_grams")
        if latest_weight_g is None and sr:
            latest_weight_g = sr.get("weight_g")
        temp_c = lot.get("temperature_c")
        humidity_rh = lot.get("humidity_pct")
        if sr:
            if temp_c is None:
                temp_c = sr.get("temp_c")
            if humidity_rh is None:
                humidity_rh = sr.get("humidity_rh")

        expires_at = lot.get("expires_at") or lot.get("expiration")
        days_left = lot.get("days_left")
        if days_left is None and expires_at:
            exp_dt = expires_at if isinstance(expires_at, datetime.datetime) else parse_storage_datetime(expires_at)
            if exp_dt is not None:
                days_left = (exp_dt.date() - now.date()).days

        rec = compute_markdown_recommendation(fi.get("price"), days_left)
        batch_price = lot.get("recommended_price")
        if batch_price is not None:
            recommended_price = float(batch_price)
            rec = {**rec, "recommended_price": recommended_price, "label": "Batch stored"}
        else:
            recommended_price = rec["recommended_price"]
        if recommended_price is not None:
            if min_price is not None and recommended_price < min_price:
                recommended_price = min_price
                rec["label"] = f"{rec['label']} (floored)"
            if max_price is not None and recommended_price > max_price:
                recommended_price = max_price
                rec["label"] = f"{rec['label']} (capped)"

        lot_label = _normalize_lot_label(lot.get("lot_code") or lot.get("lot_id") or "") or f"#{lot['_id']}"
        guardrails = None
        if min_price is not None or max_price is not None:
            lo = f"${float(min_price):.2f}" if min_price is not None else "—"
            hi = f"${float(max_price):.2f}" if max_price is not None else "—"
            guardrails = f"{lo} – {hi}"

        live_pricing = _pricing_algo_for_lot(lot, latest_weight_g, temp_c, humidity_rh, lot.get("ripeness"))
        if live_pricing is not None:
            freshness_score = live_pricing.freshness_score
            live_rec_price = round(float(fi.get("price") or 0) * live_pricing.multiplier, 2) if fi.get("price") else live_pricing.final_price
            if min_price is not None and live_rec_price < float(min_price):
                live_rec_price = float(min_price)
            if max_price is not None and live_rec_price > float(max_price):
                live_rec_price = float(max_price)
            if recommended_price is None:
                recommended_price = live_rec_price
            live_discount_pct = round((1.0 - live_pricing.multiplier) * 100.0, 1)
        else:
            freshness_score = lot.get("freshness_score")
            live_discount_pct = lot.get("discount_pct")

        live_restock = _restock_algo_for_lot(recommended_price, latest_weight_g)
        if live_restock is not None:
            restock_alert_level = live_restock.alert_level
            restock_message = live_restock.alert_message
            suggested_order_qty = live_restock.suggested_order_qty if live_restock.should_reorder else None
        else:
            restock_alert_level = lot.get("restock_alert_level")
            restock_message = lot.get("restock_message")
            suggested_order_qty = lot.get("suggested_order_qty")

        if live_pricing is not None:
            rec["label"] = f"Fresh {freshness_score:.0f}/100"
            rec["status"] = "ok" if freshness_score >= 70 else ("soon" if freshness_score >= 40 else "urgent")

        inventory_rows.append(
            {
                "lot_id": lot["_id"],
                "lot_code": lot_label,
                "batch_type": (lot.get("type") or "").strip() or "—",
                "quantity_label": (lot.get("quantity_label") or "").strip() or "—",
                "notes": (lot.get("notes") or "").strip() or None,
                "item_name": fi.get("name"),
                "item_name_short": abbreviate_product_name(fi.get("name"), 22),
                "department": fi.get("department"),
                "base_price": fi.get("price"),
                "received_at_human": format_datetime_for_store_users(lot.get("received_at")),
                "expires_at_human": format_date_for_store_users(lot.get("expires_at") or lot.get("expiration")),
                "days_left": days_left,
                "ripeness": lot.get("ripeness"),
                "discount_pct": live_discount_pct if live_pricing is not None else lot.get("discount_pct"),
                "temperature_c": temp_c,
                "humidity_pct": humidity_rh,
                "latest_weight_g": latest_weight_g,
                "rec_status": rec["status"],
                "rec_label": rec["label"],
                "recommended_price": recommended_price,
                "min_price": min_price,
                "max_price": max_price,
                "guardrails": guardrails,
                "freshness_score": freshness_score,
                "restock_alert_level": restock_alert_level,
                "restock_message": restock_message,
                "suggested_order_qty": suggested_order_qty,
            }
        )

    fis_store = list(db.food_items.find({"store_id": store_id}))
    fi_dept = {
        f["_id"]: (f.get("department") or "").strip() or "Uncategorized" for f in fis_store
    }

    dept_skus = defaultdict(set)
    dept_batches = defaultdict(int)
    for f in fis_store:
        d = (f.get("department") or "").strip() or "Uncategorized"
        dept_skus[d].add(f["_id"])
    dept_lots_raw = list(
        db.lots.find(
            {
                "food_item_id": {"$in": list(fi_dept.keys())},
                "$or": [{"store_id": store_id}, {"store_id": {"$exists": False}}],
            }
        )
    )
    for lot in _dedupe_lots_for_display(dept_lots_raw):
        d = fi_dept.get(lot["food_item_id"], "Uncategorized")
        dept_batches[d] += 1
    department_batch_summary = [
        {"department": d, "sku_count": len(dept_skus[d]), "batch_count": dept_batches.get(d, 0)}
        for d in sorted(dept_skus.keys())
    ]

    stores_nav = [_with_id(s) for s in db.stores.find().sort("name", 1)]
    food_items = [_with_id(f) for f in db.food_items.find({"store_id": store_id}).sort("name", 1)]

    fi_ids_nav = [f["_id"] for f in db.food_items.find({"store_id": store_id}, {"_id": 1})]
    lots = []
    if fi_ids_nav:
        nav_lots = list(
            db.lots.find(
                {
                    "food_item_id": {"$in": fi_ids_nav},
                    "$or": [{"store_id": store_id}, {"store_id": {"$exists": False}}],
                }
            ).sort("received_at", -1)
        )
        nav_lots = _dedupe_lots_for_display(nav_lots)[:50]
        for l in nav_lots:
            fi = db.food_items.find_one({"_id": l["food_item_id"]})
            lots.append(
                {
                    "id": l["_id"],
                    "item_name": fi["name"] if fi else "?",
                    "lot_code": _normalize_lot_label(l.get("lot_code") or l.get("lot_id") or "")
                    or f"#{l['_id']}",
                    "received_at": l.get("received_at"),
                    "received_at_human": format_datetime_for_store_users(l.get("received_at")),
                }
            )

    return render_template(
        "dashboard.html",
        store=store,
        stores_nav=stores_nav,
        skus=skus,
        inventory_rows=inventory_rows,
        food_items=food_items,
        lots=lots,
        departments=departments,
        department_batch_summary=department_batch_summary,
        selected_department=selected_department,
        product_options=product_options,
        selected_food_item_id=selected_food_item_id,
        sku_sort=sku_sort,
        city_admin=bool(session.get("city_admin")),
    )


@app.route("/items/new", methods=["POST"])
@login_required
def create_item():
    store_id = request.form.get("store_id", type=int) or get_or_create_default_store()
    name = (request.form.get("name") or "").strip()
    description = (request.form.get("description") or "").strip()
    sku_number = (request.form.get("sku_number") or "").strip()
    barcode = (request.form.get("barcode") or "").strip()
    image_url = (request.form.get("image_url") or "").strip()
    department = (request.form.get("department") or "").strip()
    price = parse_optional_float(request.form.get("price"))
    if not name:
        flash("Item name is required.", "error")
        return redirect(url_for("dashboard", store_id=store_id))

    db = get_mongo_db()
    new_id = alloc_id("food_items")
    doc = {
        "_id": new_id,
        "name": name,
        "description": description or None,
        "department": department or None,
        "sku_number": sku_number or None,
        "barcode": barcode or None,
        "image_url": image_url or None,
        "price": price,
        "store_id": store_id,
        "created_at": now_ts(),
    }
    if not barcode:
        doc["barcode"] = generate_barcode_for_item_id(new_id)
    if not image_url:
        doc["image_url"] = generate_image_url_for_item_id(new_id)
    try:
        db.food_items.insert_one(doc)
    except DuplicateKeyError:
        flash("Barcode already in use; choose another.", "error")
        return redirect(url_for("dashboard", store_id=store_id))
    flash("Item added.", "success")
    return redirect(url_for("dashboard", store_id=store_id))


@app.route("/lots/new", methods=["POST"])
@login_required
def create_lot():
    store_id = request.form.get("store_id", type=int) or get_or_create_default_store()
    food_item_id = request.form.get("food_item_id", type=int)
    lot_code = _normalize_lot_label(request.form.get("lot_code") or "")
    lot_id_label = _normalize_lot_label(request.form.get("lot_id") or "") or lot_code
    received_at = parse_optional_datetime_local(request.form.get("received_at")) or datetime.datetime.now().replace(microsecond=0)
    expires_at = parse_optional_datetime_local(request.form.get("expires_at"))
    expiration = parse_optional_datetime_local(request.form.get("expiration")) or expires_at
    quantity_label = (request.form.get("quantity_label") or "").strip()
    notes = (request.form.get("notes") or "").strip()

    batch_type = (request.form.get("type") or "").strip() or None
    weight_grams = parse_optional_float(request.form.get("weight_grams"))
    temperature_c = parse_optional_float(request.form.get("temperature_c"))
    humidity_pct = parse_optional_float(request.form.get("humidity_pct"))
    recommended_price = parse_optional_float(request.form.get("recommended_price"))
    ripeness = parse_optional_int(request.form.get("ripeness"))
    days_left_in = parse_optional_int(request.form.get("days_left"))

    if not food_item_id:
        flash("Select an item to create a lot.", "error")
        return redirect(url_for("dashboard", store_id=store_id))

    if not lot_code:
        flash("Lot code is required (e.g. ST1-I1-B1-334).", "error")
        return redirect(url_for("dashboard", store_id=store_id))

    now = datetime.datetime.now().replace(microsecond=0)
    days_left = days_left_in
    if days_left is None and expiration is not None:
        days_left = max(0, (expiration.date() - now.date()).days)

    db = get_mongo_db()
    fi = db.food_items.find_one({"_id": food_item_id})
    if fi is None:
        flash("Selected item was not found.", "error")
        return redirect(url_for("dashboard", store_id=store_id))
    lot_store_id = int(fi.get("store_id") or store_id)

    lot_id = alloc_id("lots")
    try:
        db.lots.insert_one(
            {
                "_id": lot_id,
                "store_id": lot_store_id,
                "food_item_id": food_item_id,
                "lot_code": lot_code,
                "lot_id": lot_id_label,
                "type": batch_type,
                "weight_grams": weight_grams,
                "temperature_c": temperature_c,
                "humidity_pct": humidity_pct,
                "recommended_price": recommended_price,
                "ripeness": ripeness,
                "expiration": expiration,
                "expires_at": expiration or expires_at,
                "days_left": days_left,
                "received_at": received_at,
                "quantity_label": quantity_label or None,
                "notes": notes or None,
                "created_at": now_ts(),
            }
        )
    except DuplicateKeyError:
        flash("That lot ID already exists for this product.", "error")
        return redirect(url_for("dashboard", store_id=store_id))
    flash("Lot created.", "success")
    return redirect(url_for("dashboard", store_id=store_id))


@app.route("/readings/new", methods=["POST"])
@login_required
def create_reading():
    store_id = request.form.get("store_id", type=int) or get_or_create_default_store()
    lot_id = request.form.get("lot_id", type=int)
    weight_g = parse_optional_float(request.form.get("weight_g"))
    temp_c = parse_optional_float(request.form.get("temp_c"))
    humidity_rh = parse_optional_float(request.form.get("humidity_rh"))
    voc_ppb = parse_optional_float(request.form.get("voc_ppb"))
    recorded_at = parse_optional_datetime_local(request.form.get("recorded_at")) or datetime.datetime.now().replace(microsecond=0)

    if not lot_id:
        flash("Lot is required for a sensor reading.", "error")
        return redirect(url_for("dashboard", store_id=store_id))

    db = get_mongo_db()
    rid = alloc_id("sensor_readings")
    db.sensor_readings.insert_one(
        {
            "_id": rid,
            "lot_id": lot_id,
            "weight_g": weight_g,
            "temp_c": temp_c,
            "humidity_rh": humidity_rh,
            "voc_ppb": voc_ppb,
            "recorded_at": recorded_at,
            "created_at": now_ts(),
        }
    )
    flash("Reading logged.", "success")
    return redirect(url_for("dashboard", store_id=store_id))


@app.route("/pricing_rules/upsert", methods=["POST"])
@login_required
def upsert_pricing_rules():
    store_id = request.form.get("store_id", type=int) or get_or_create_default_store()
    food_item_id = request.form.get("food_item_id", type=int)
    min_price = parse_optional_float(request.form.get("min_price"))
    max_price = parse_optional_float(request.form.get("max_price"))
    margin_floor_pct = parse_optional_float(request.form.get("margin_floor_pct"))
    if not food_item_id:
        flash("Item is required to set pricing rules.", "error")
        return redirect(url_for("dashboard", store_id=store_id))

    db = get_mongo_db()
    existing = db.pricing_rules.find_one({"food_item_id": food_item_id})
    payload = {
        "food_item_id": food_item_id,
        "min_price": min_price,
        "max_price": max_price,
        "margin_floor_pct": margin_floor_pct,
    }
    if existing:
        db.pricing_rules.update_one({"_id": existing["_id"]}, {"$set": payload})
    else:
        payload["_id"] = alloc_id("pricing_rules")
        payload["created_at"] = now_ts()
        db.pricing_rules.insert_one(payload)
    flash("Pricing rules saved.", "success")
    return redirect(url_for("dashboard", store_id=store_id))


@app.route("/seed_demo", methods=["POST"])
@login_required
def seed_demo():
    get_or_create_default_store()

    db = get_mongo_db()
    seeded_count = 0
    for row in db.stores.find().sort("_id", 1):
        sid = row["_id"]
        if _store_has_items(sid):
            continue
        if _seed_store_catalog(sid, 0):
            seeded_count += 1

    store_id = session.get("store_id") or get_or_create_default_store()
    if seeded_count:
        flash(
            f"Seeded minimal demo SKUs and batches for {seeded_count} empty store(s).",
            "success",
        )
    else:
        flash("Every store already has a catalog. No changes made.", "info")
    return redirect(url_for("dashboard", store_id=store_id))


@app.route("/favicon.ico")
def favicon():
    # Real .ico (multi-size) — many browsers only accept this at /favicon.ico, not PNG-in-disguise.
    response = send_from_directory(app.static_folder, "favicon.ico", mimetype="image/x-icon")
    response.headers["Cache-Control"] = "public, max-age=86400, must-revalidate"
    return response


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)
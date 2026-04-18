from flask import Flask, render_template, redirect, url_for, request, flash, session

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import hashlib
import os
import random
import datetime
from collections import defaultdict
from functools import wraps

from pymongo.errors import DuplicateKeyError
from werkzeug.security import generate_password_hash

import dc_grocery
from mongo_db import get_mongo_db
from db_mongo import alloc_id, init_mongo, now_ts

app = Flask("app")
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


# Demo catalogs: (name, description, department / product type, base price)
_DEMO_CATALOG_VARIANTS = [
    [
        ("Bananas", "Organic bunches", "Produce", 0.79),
        ("Baby spinach", "5 oz clamshell", "Produce", 3.49),
        ("Avocados", "Hass, ripe", "Produce", 1.29),
        ("Whole milk 1 gal", "Vitamin D", "Dairy", 4.29),
        ("Greek yogurt", "Plain 32 oz", "Dairy", 5.99),
        ("Sourdough loaf", "Bakery artisan", "Bakery", 6.5),
        ("Eggs dozen", "Large cage-free", "Dairy", 4.99),
        ("Orange juice", "NFC half gallon", "Beverages", 3.99),
    ],
    [
        ("Chicken thighs", "Bone-in family pack", "Meat", 8.99),
        ("Ground beef", "85% lean", "Meat", 6.49),
        ("Frozen berries", "Mixed 12 oz", "Frozen", 4.29),
        ("Frozen peas", "Steamable bag", "Frozen", 2.19),
        ("Cheddar block", "Sharp 8 oz", "Dairy", 3.99),
        ("Butter quarters", "Unsalted", "Dairy", 4.49),
        ("Iced tea gallon", "Unsweetened", "Beverages", 2.99),
        ("Corn tortillas", "30 count", "Pantry", 2.79),
    ],
    [
        ("Long-grain rice", "2 lb bag", "Pantry", 3.49),
        ("Black beans", "Canned low-sodium", "Pantry", 1.29),
        ("Pasta penne", "1 lb dry", "Pantry", 1.99),
        ("Tomatoes on vine", "Local when available", "Produce", 2.99),
        ("Romaine hearts", "3-pack", "Produce", 3.19),
        ("Almond milk", "Unsweetened half gal", "Beverages", 3.49),
        ("Frozen pizza", "Cheese thin crust", "Frozen", 5.99),
        ("Bagels", "6-pack plain", "Bakery", 3.29),
    ],
]

_DEMO_PARTNER_STORES = [
    ("Healthy Corners — Georgia Ave", "1200 Georgia Ave NW, Washington, DC"),
    ("South Capitol Fresh Market", "1015 Half St SE, Washington, DC"),
    ("Anacostia Pantry Co-op", "1800 Good Hope Rd SE, Washington, DC"),
]


def _ensure_partner_stores():
    db = get_mongo_db()
    for name, address in _DEMO_PARTNER_STORES:
        if db.stores.find_one({"name": name}) is None:
            sid = alloc_id("stores")
            db.stores.insert_one({"_id": sid, "name": name, "address": address, "created_at": now_ts()})


def _seed_store_catalog(store_id, variant_index):
    """Insert SKUs, lots, and sample readings. Caller ensures store has no items yet."""
    db = get_mongo_db()
    catalog = _DEMO_CATALOG_VARIANTS[variant_index % len(_DEMO_CATALOG_VARIANTS)]
    now = datetime.datetime.now().replace(microsecond=0)
    food_item_ids = []

    for name, desc, department, price in catalog:
        fid = alloc_id("food_items")
        db.food_items.insert_one(
            {
                "_id": fid,
                "name": name,
                "description": desc,
                "department": department,
                "sku_number": None,
                "barcode": generate_barcode_for_item_id(fid),
                "image_url": generate_image_url_for_item_id(fid),
                "price": price,
                "store_id": store_id,
                "created_at": now_ts(),
            }
        )
        food_item_ids.append(fid)

        batch_specs = [
            (0, 36, 5, "Case A / primary"),
            (1, 12, 1, "Case B / backup"),
        ]
        for batch_n, hours_ago, days_until_exp, qty_note in batch_specs:
            received = now - datetime.timedelta(hours=hours_ago + batch_n * 4)
            expires = now + datetime.timedelta(days=days_until_exp, hours=batch_n * 2)
            lot_code = f"ST{store_id}-I{fid}B{batch_n + 1}"
            lot_id = alloc_id("lots")
            db.lots.insert_one(
                {
                    "_id": lot_id,
                    "food_item_id": fid,
                    "lot_code": lot_code,
                    "received_at": received,
                    "expires_at": expires,
                    "quantity_label": qty_note,
                    "notes": f"Demo batch · {department}",
                    "created_at": now_ts(),
                }
            )
            weight_g = 1100.0 + (fid % 7) * 35 + batch_n * 120
            rid = alloc_id("sensor_readings")
            db.sensor_readings.insert_one(
                {
                    "_id": rid,
                    "lot_id": lot_id,
                    "weight_g": weight_g,
                    "temp_c": 3.5 + batch_n * 0.4,
                    "humidity_rh": 52.0 + batch_n * 2,
                    "voc_ppb": 420 + batch_n * 40,
                    "recorded_at": now,
                    "created_at": now_ts(),
                }
            )

    for fid in food_item_ids[:3]:
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


def _store_has_items(store_id):
    db = get_mongo_db()
    return db.food_items.count_documents({"store_id": store_id}) > 0


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
        total_lots = db.lots.count_documents({"food_item_id": fid})
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
        lots_for_inv = list(db.lots.find({"food_item_id": {"$in": list(fi_by_id.keys())}}))

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
        latest_weight_g = sr.get("weight_g") if sr else None

        expires_at = lot.get("expires_at")
        days_left = None
        if expires_at:
            exp_dt = expires_at if isinstance(expires_at, datetime.datetime) else parse_storage_datetime(expires_at)
            if exp_dt is not None:
                days_left = (exp_dt.date() - now.date()).days

        rec = compute_markdown_recommendation(fi.get("price"), days_left)
        recommended_price = rec["recommended_price"]
        if recommended_price is not None:
            if min_price is not None and recommended_price < min_price:
                recommended_price = min_price
                rec["label"] = f"{rec['label']} (floored)"
            if max_price is not None and recommended_price > max_price:
                recommended_price = max_price
                rec["label"] = f"{rec['label']} (capped)"

        inventory_rows.append(
            {
                "lot_id": lot["_id"],
                "lot_code": lot.get("lot_code") or f"#{lot['_id']}",
                "item_name": fi.get("name"),
                "item_name_short": abbreviate_product_name(fi.get("name"), 22),
                "department": fi.get("department"),
                "received_at_human": format_datetime_for_store_users(lot.get("received_at")),
                "expires_at_human": format_date_for_store_users(lot.get("expires_at")),
                "days_left": days_left,
                "latest_weight_g": latest_weight_g,
                "rec_status": rec["status"],
                "rec_label": rec["label"],
                "recommended_price": recommended_price,
                "min_price": min_price,
                "max_price": max_price,
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
    for lot in db.lots.find({"food_item_id": {"$in": list(fi_dept.keys())}}):
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
        for l in db.lots.find({"food_item_id": {"$in": fi_ids_nav}}).sort("received_at", -1).limit(50):
            fi = db.food_items.find_one({"_id": l["food_item_id"]})
            lots.append(
                {
                    "id": l["_id"],
                    "item_name": fi["name"] if fi else "?",
                    "lot_code": l.get("lot_code"),
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
    lot_code = (request.form.get("lot_code") or "").strip()
    received_at = parse_optional_datetime_local(request.form.get("received_at")) or datetime.datetime.now().replace(microsecond=0)
    expires_at = parse_optional_datetime_local(request.form.get("expires_at"))
    quantity_label = (request.form.get("quantity_label") or "").strip()
    notes = (request.form.get("notes") or "").strip()

    if not food_item_id:
        flash("Select an item to create a lot.", "error")
        return redirect(url_for("dashboard", store_id=store_id))

    if not lot_code:
        flash("Lot ID is required (e.g., A12, BAN-042).", "error")
        return redirect(url_for("dashboard", store_id=store_id))

    db = get_mongo_db()
    lot_id = alloc_id("lots")
    try:
        db.lots.insert_one(
            {
                "_id": lot_id,
                "food_item_id": food_item_id,
                "lot_code": lot_code,
                "received_at": received_at,
                "expires_at": expires_at,
                "quantity_label": quantity_label,
                "notes": notes,
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
    _ensure_partner_stores()

    db = get_mongo_db()
    seeded_count = 0
    for idx, row in enumerate(db.stores.find().sort("_id", 1)):
        sid = row["_id"]
        if _store_has_items(sid):
            continue
        _seed_store_catalog(sid, idx)
        seeded_count += 1

    store_id = session.get("store_id") or get_or_create_default_store()
    if seeded_count:
        flash(
            f"Seeded demo SKUs and batches for {seeded_count} store(s). Use the store menu to switch locations.",
            "success",
        )
    else:
        flash("Every store already has a catalog. No changes made.", "info")
    return redirect(url_for("dashboard", store_id=store_id))

if __name__ == '__main__':
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", "5000"))
    app.run(host=host, port=port, debug=True)
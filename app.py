from flask import Flask, render_template, redirect, url_for, request, g, flash

import sqlite3
import datetime

app = Flask("app")
FLASK_ENV = "development"
app.secret_key = "CHANGE ME"


def get_connection():
    connection = getattr(g, "_database", None)
    if connection is None:
        connection = g._database = sqlite3.connect("database.db")
        connection.row_factory = sqlite3.Row
    return connection


@app.teardown_appcontext
def close_connection(exception):
    connection = getattr(g, "_database", None)
    if connection is not None:
        connection.close()


'''
TEMPLATE FOR CALLING THE DB

conn = get_connection()
cursor = conn.cursor()
cursor.execute("SQL QUERY")
data = cursor.fetchall()
row_1 = data[0]
cursor.close()

'''


def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    with open("database_schema.sql", "r", encoding="utf-8") as f:
        cursor.executescript(f.read())

    # Lightweight migrations for existing local DB files.
    # Keeps the project demo-friendly without a full migration framework.
    cursor.execute("PRAGMA table_info(lots)")
    lot_cols = {row["name"] for row in cursor.fetchall()}
    if "lot_code" not in lot_cols:
        cursor.execute("ALTER TABLE lots ADD COLUMN lot_code TEXT")
    # Create after ensuring the column exists (handles old DBs + fresh DBs)
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_lots_food_item_lot_code ON lots(food_item_id, lot_code)")

    cursor.execute("PRAGMA table_info(food_items)")
    item_cols = {row["name"] for row in cursor.fetchall()}
    if "department" not in item_cols:
        cursor.execute("ALTER TABLE food_items ADD COLUMN department TEXT")
        # Best-effort backfill for older DBs that used description as a category label.
        cursor.execute(
            """
            UPDATE food_items
            SET department = COALESCE(department, description)
            WHERE department IS NULL AND description IS NOT NULL
            """
        )
    if "sku_number" not in item_cols:
        cursor.execute("ALTER TABLE food_items ADD COLUMN sku_number TEXT")
    if "barcode" not in item_cols:
        cursor.execute("ALTER TABLE food_items ADD COLUMN barcode TEXT")
    if "image_url" not in item_cols:
        cursor.execute("ALTER TABLE food_items ADD COLUMN image_url TEXT")
    if "barcode" in item_cols or "barcode" not in item_cols:
        # Create after ensuring the column exists (handles old DBs + fresh DBs)
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_food_items_barcode ON food_items(barcode)")

    conn.commit()
    cursor.close()


@app.before_request
def _ensure_db():
    init_db()


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


def get_or_create_default_store():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM stores ORDER BY id ASC LIMIT 1")
    store = cursor.fetchone()
    if store is not None:
        cursor.close()
        return store["id"]
    cursor.execute("INSERT INTO stores (name, address) VALUES (?, ?)", ("Demo Corner Store", ""))
    conn.commit()
    store_id = cursor.lastrowid
    cursor.close()
    return store_id



@app.route('/')
def home():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    store_id = request.args.get("store_id", type=int) or get_or_create_default_store()
    selected_department = (request.args.get("department") or "").strip() or None
    selected_food_item_id = request.args.get("food_item_id", type=int)
    sku_sort = (request.args.get("sku_sort") or "").strip() or "created"

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, address FROM stores WHERE id = ?", (store_id,))
    store = cursor.fetchone()

    cursor.execute(
        """
        SELECT DISTINCT department
        FROM food_items
        WHERE store_id = ? AND department IS NOT NULL AND TRIM(department) != ''
        ORDER BY department ASC
        """,
        (store_id,),
    )
    departments = [r["department"] for r in cursor.fetchall()]

    cursor.execute(
        """
        SELECT id, name, department
        FROM food_items
        WHERE store_id = ?
          AND (? IS NULL OR department = ?)
        ORDER BY name ASC
        """,
        (store_id, selected_department, selected_department),
    )
    product_options = cursor.fetchall()

    sku_order_by = "datetime(fi.created_at) DESC"
    if sku_sort == "department":
        sku_order_by = "COALESCE(fi.department, ''), fi.name ASC"

    sku_params = [store_id]
    sku_dept_clause = ""
    if selected_department:
        sku_dept_clause = "AND fi.department = ?"
        sku_params.append(selected_department)

    cursor.execute(
        f"""
        SELECT
          fi.id AS food_item_id,
          fi.name AS item_name,
          fi.description AS item_description,
          fi.department AS department,
          fi.sku_number AS sku_number,
          fi.barcode AS barcode,
          fi.image_url AS image_url,
          fi.price AS base_price,
          (
            SELECT COUNT(*)
            FROM lots l
            WHERE l.food_item_id = fi.id
          ) AS total_lots
        FROM food_items fi
        WHERE fi.store_id = ?
        {sku_dept_clause}
        ORDER BY {sku_order_by}
        """,
        tuple(sku_params),
    )
    skus = []
    for it in cursor.fetchall():
        skus.append(
            {
                "food_item_id": it["food_item_id"],
                "item_name": it["item_name"],
                "item_name_short": abbreviate_product_name(it["item_name"], 18),
                "item_description": it["item_description"],
                "department": it["department"],
                "sku_number": it["sku_number"],
                "barcode": it["barcode"],
                "image_url": it["image_url"],
                "base_price": it["base_price"],
                "total_lots": it["total_lots"] or 0,
            }
        )

    now = datetime.datetime.now()
    inventory_rows = []

    dept_clause = ""
    product_clause = ""
    params = [store_id]
    if selected_department:
        dept_clause = "AND fi.department = ?"
        params.append(selected_department)
    if selected_food_item_id:
        product_clause = "AND fi.id = ?"
        params.append(selected_food_item_id)

    cursor.execute(
        f"""
        SELECT
          l.id AS lot_id,
          l.lot_code AS lot_code,
          l.received_at AS received_at,
          l.expires_at AS expires_at,
          fi.price AS base_price,
          fi.department AS department,
          pr.min_price AS min_price,
          pr.max_price AS max_price,
          (
            SELECT sr.weight_g
            FROM sensor_readings sr
            WHERE sr.lot_id = l.id
            ORDER BY datetime(sr.recorded_at) DESC
            LIMIT 1
          ) AS latest_weight_g
        FROM lots l
        JOIN food_items fi ON fi.id = l.food_item_id
        LEFT JOIN pricing_rules pr ON pr.food_item_id = fi.id
        WHERE fi.store_id = ?
        {dept_clause}
        {product_clause}
        ORDER BY
          CASE WHEN l.expires_at IS NULL THEN 1 ELSE 0 END,
          datetime(l.expires_at) ASC
        LIMIT 200
        """,
        tuple(params),
    )

    for it in cursor.fetchall():
        expires_at = it["expires_at"]
        days_left = None
        if expires_at:
            exp_dt = parse_storage_datetime(expires_at)
            if exp_dt is not None:
                days_left = (exp_dt.date() - now.date()).days

        rec = compute_markdown_recommendation(it["base_price"], days_left)
        recommended_price = rec["recommended_price"]
        if recommended_price is not None:
            min_price = it["min_price"]
            max_price = it["max_price"]
            if min_price is not None and recommended_price < min_price:
                recommended_price = min_price
                rec["label"] = f"{rec['label']} (floored)"
            if max_price is not None and recommended_price > max_price:
                recommended_price = max_price
                rec["label"] = f"{rec['label']} (capped)"

        inventory_rows.append(
            {
                "lot_id": it["lot_id"],
                "lot_code": it["lot_code"] or f"#{it['lot_id']}",
                "received_at_human": format_datetime_for_store_users(it["received_at"]),
                "expires_at_human": format_date_for_store_users(it["expires_at"]),
                "days_left": days_left,
                "latest_weight_g": it["latest_weight_g"],
                "rec_status": rec["status"],
                "rec_label": rec["label"],
                "recommended_price": recommended_price,
                "min_price": it["min_price"],
                "max_price": it["max_price"],
            }
        )

    cursor.execute("SELECT id, name FROM food_items WHERE store_id = ? ORDER BY name ASC", (store_id,))
    food_items = cursor.fetchall()
    cursor.execute(
        """
        SELECT l.id, l.lot_code, fi.name AS item_name, l.received_at
        FROM lots l
        JOIN food_items fi ON fi.id = l.food_item_id
        WHERE fi.store_id = ?
        ORDER BY datetime(l.received_at) DESC
        LIMIT 50
        """,
        (store_id,),
    )
    lots = []
    for l in cursor.fetchall():
        lots.append(
            {
                "id": l["id"],
                "item_name": l["item_name"],
                "lot_code": l["lot_code"],
                "received_at": l["received_at"],
                "received_at_human": format_datetime_for_store_users(l["received_at"]),
            }
        )

    cursor.close()
    return render_template(
        "dashboard.html",
        store=store,
        skus=skus,
        inventory_rows=inventory_rows,
        food_items=food_items,
        lots=lots,
        departments=departments,
        selected_department=selected_department,
        product_options=product_options,
        selected_food_item_id=selected_food_item_id,
        sku_sort=sku_sort,
    )


@app.route("/items/new", methods=["POST"])
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

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO food_items (name, description, department, sku_number, barcode, image_url, price, store_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (name, description, department or None, sku_number or None, barcode or None, image_url or None, price, store_id),
    )
    new_id = cursor.lastrowid
    if not barcode:
        cursor.execute("UPDATE food_items SET barcode = ? WHERE id = ?", (generate_barcode_for_item_id(new_id), new_id))
    if not image_url:
        cursor.execute("UPDATE food_items SET image_url = ? WHERE id = ?", (generate_image_url_for_item_id(new_id), new_id))
    conn.commit()
    cursor.close()
    flash("Item added.", "success")
    return redirect(url_for("dashboard", store_id=store_id))


@app.route("/lots/new", methods=["POST"])
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

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO lots (food_item_id, lot_code, received_at, expires_at, quantity_label, notes)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            food_item_id,
            lot_code,
            to_storage_datetime(received_at),
            to_storage_datetime(expires_at) if expires_at else None,
            quantity_label,
            notes,
        ),
    )
    conn.commit()
    cursor.close()
    flash("Lot created.", "success")
    return redirect(url_for("dashboard", store_id=store_id))


@app.route("/readings/new", methods=["POST"])
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

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO sensor_readings (lot_id, weight_g, temp_c, humidity_rh, voc_ppb, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            lot_id,
            weight_g,
            temp_c,
            humidity_rh,
            voc_ppb,
            to_storage_datetime(recorded_at),
        ),
    )
    conn.commit()
    cursor.close()
    flash("Reading logged.", "success")
    return redirect(url_for("dashboard", store_id=store_id))


@app.route("/pricing_rules/upsert", methods=["POST"])
def upsert_pricing_rules():
    store_id = request.form.get("store_id", type=int) or get_or_create_default_store()
    food_item_id = request.form.get("food_item_id", type=int)
    min_price = parse_optional_float(request.form.get("min_price"))
    max_price = parse_optional_float(request.form.get("max_price"))
    margin_floor_pct = parse_optional_float(request.form.get("margin_floor_pct"))
    if not food_item_id:
        flash("Item is required to set pricing rules.", "error")
        return redirect(url_for("dashboard", store_id=store_id))

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO pricing_rules (food_item_id, min_price, max_price, margin_floor_pct)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(food_item_id) DO UPDATE SET
          min_price = excluded.min_price,
          max_price = excluded.max_price,
          margin_floor_pct = excluded.margin_floor_pct
        """,
        (food_item_id, min_price, max_price, margin_floor_pct),
    )
    conn.commit()
    cursor.close()
    flash("Pricing rules saved.", "success")
    return redirect(url_for("dashboard", store_id=store_id))


@app.route("/seed_demo", methods=["POST"])
def seed_demo():
    store_id = get_or_create_default_store()
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) AS c FROM food_items WHERE store_id = ?", (store_id,))
    if cursor.fetchone()["c"] > 0:
        cursor.close()
        flash("Demo already seeded.", "info")
        return redirect(url_for("dashboard", store_id=store_id))

    items = [
        ("Bananas", "Ripe yellow bananas", "Produce", 0.79),
        ("Milk (half gallon)", "Whole milk", "Dairy", 2.99),
        ("Strawberries", "1 lb clamshell", "Produce", 3.49),
    ]
    food_item_ids = []
    for name, desc, department, price in items:
        cursor.execute(
            "INSERT INTO food_items (name, description, department, sku_number, barcode, image_url, price, store_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, desc, department, None, None, None, price, store_id),
        )
        fid = cursor.lastrowid
        cursor.execute("UPDATE food_items SET barcode = ? WHERE id = ?", (generate_barcode_for_item_id(fid), fid))
        cursor.execute("UPDATE food_items SET image_url = ? WHERE id = ?", (generate_image_url_for_item_id(fid), fid))
        food_item_ids.append(fid)

    now = datetime.datetime.now().replace(microsecond=0)
    for fid in food_item_ids:
        received = now - datetime.timedelta(hours=2)
        expires = now + datetime.timedelta(days=2)
        cursor.execute(
            "INSERT INTO lots (food_item_id, lot_code, received_at, expires_at, quantity_label, notes) VALUES (?, ?, ?, ?, ?, ?)",
            (fid, f"LOT-{fid}-1", to_storage_datetime(received), to_storage_datetime(expires), "1 unit", "demo lot"),
        )
        lot_id = cursor.lastrowid
        cursor.execute(
            """
            INSERT INTO sensor_readings (lot_id, weight_g, temp_c, humidity_rh, voc_ppb, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (lot_id, 1200.0, 4.0, 55.0, 450.0, to_storage_datetime(now)),
        )

    conn.commit()
    cursor.close()
    flash("Seeded demo data.", "success")
    return redirect(url_for("dashboard", store_id=store_id))

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
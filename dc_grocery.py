"""
DC grocery / corner-store locations for the city map.

We pull public POI data from the OpenStreetMap Overpass API (POST request + JSON
parse). This avoids brittle HTML scraping of commercial store locators and
respects typical site terms of use.

Results are cached on disk (24h) so the city dashboard stays fast and we do not
hammer public infrastructure.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

# District of Columbia — approximate bounding box (south, west, north, east)
DC_BBOX = (38.7916, -77.1198, 38.9956, -76.9093)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
CACHE_FILE = os.path.join(CACHE_DIR, "dc_grocery_pins.json")
CACHE_MAX_AGE_SEC = 86400
MAX_PINS = 200

FALLBACK = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "static",
    "data",
    "dc_grocery_fallback.json",
)


def _overpass_query() -> str:
    s, w, n, e = DC_BBOX
    # Supermarkets, convenience (corner/bodega), greengrocers — nodes + ways (center)
    return f"""[out:json][timeout:60];
(
  node["shop"~"supermarket|convenience|greengrocer"]({s},{w},{n},{e});
  way["shop"~"supermarket|convenience|greengrocer"]({s},{w},{n},{e});
);
out center;
"""


def _parse_overpass_elements(payload: dict) -> list[dict]:
    out: list[dict] = []
    for el in payload.get("elements") or []:
        tags = el.get("tags") or {}
        name = (tags.get("name") or tags.get("brand") or "Grocery / corner store").strip()
        shop = (tags.get("shop") or "grocery").strip()
        lat = el.get("lat")
        lon = el.get("lon")
        if lat is None or lon is None:
            c = el.get("center") or {}
            lat, lon = c.get("lat"), c.get("lon")
        if lat is None or lon is None:
            continue
        out.append(
            {
                "lat": float(lat),
                "lon": float(lon),
                "name": name,
                "shop": shop,
                "source": "openstreetmap",
            }
        )
    return out[:MAX_PINS]


def _fetch_overpass_live() -> list[dict]:
    body = urllib.parse.urlencode({"data": _overpass_query()}).encode("utf-8")
    req = urllib.request.Request(
        OVERPASS_URL,
        data=body,
        method="POST",
        headers={
            "User-Agent": "VitalShelf/1.0 (DC grocery map; contact: local dev)",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        raw = resp.read().decode("utf-8")
    payload = json.loads(raw)
    return _parse_overpass_elements(payload)


def _load_fallback() -> list[dict]:
    try:
        with open(FALLBACK, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return data.get("pins") or []
    except (OSError, json.JSONDecodeError, TypeError):
        return []


def _pin_identity_key(pin: dict) -> str:
    return (
        f"{float(pin['lat']):.6f}|{float(pin['lon']):.6f}|"
        f"{pin.get('name') or ''}|{pin.get('shop') or ''}"
    )


# Sub-scores are 0–100 (higher = better). Health index = weighted sum, clamped to 15–99.
HEALTH_FACTOR_WEIGHTS: dict[str, float] = {
    "freshness_uptime": 0.35,  # shelf-life / sensor freshness band (demo)
    "markdown_discipline": 0.25,  # alignment with dynamic markdown recommendations (demo)
    "cold_chain_stability": 0.20,  # storage temp / humidity stability proxy (demo)
    "community_access": 0.20,  # SNAP / neighborhood affordability fit (demo)
}


def enrich_pins_with_demo_metrics(pins: list[dict]) -> list[dict]:
    """
    Deterministic synthetic metrics per store for the city map (demo only).

    - health_index: derived as Σ (weight × factor) with factors in 0–100
    - weekly_sales_usd: synthetic sales volume for dot sizing
    """
    out: list[dict] = []
    strip = {
        "health_index",
        "health_tier",
        "weekly_sales_usd",
        "spoilage_stress_demo",
        "metrics_note",
        "health_factors",
        "health_weighted_points",
        "health_index_raw",
    }
    for raw in pins:
        p = {k: v for k, v in raw.items() if k not in strip}
        key = _pin_identity_key(p)
        digest = hashlib.sha256(key.encode("utf-8")).digest()

        shop = (p.get("shop") or "").lower()
        h = int.from_bytes(digest[:8], "big")
        weekly_sales_usd = int(4500 + (h % 215_000))
        if "supermarket" in shop:
            weekly_sales_usd = int(weekly_sales_usd * 1.18)
        elif "greengrocer" in shop:
            weekly_sales_usd = int(weekly_sales_usd * 0.92)

        def _clamp_score(x: float) -> float:
            return max(0.0, min(100.0, x))

        # Base draws from different digest bytes so factors vary independently (demo).
        freshness = _clamp_score(44.0 + (digest[0] / 255.0) * 48.0)
        markdown_disc = _clamp_score(40.0 + (digest[1] / 255.0) * 52.0)
        cold_chain = _clamp_score(38.0 + (digest[2] / 255.0) * 54.0)
        community = _clamp_score(41.0 + (digest[3] / 255.0) * 50.0)

        if "supermarket" in shop:
            cold_chain = _clamp_score(cold_chain + 6.0)
            markdown_disc = _clamp_score(markdown_disc + 4.0)
        if "convenience" in shop:
            community = _clamp_score(community + 8.0)
            cold_chain = _clamp_score(cold_chain - 5.0)
        if "greengrocer" in shop:
            freshness = _clamp_score(freshness + 7.0)

        factors = {
            "freshness_uptime": round(freshness, 1),
            "markdown_discipline": round(markdown_disc, 1),
            "cold_chain_stability": round(cold_chain, 1),
            "community_access": round(community, 1),
        }

        weighted_points = {
            k: round(HEALTH_FACTOR_WEIGHTS[k] * factors[k], 2) for k in HEALTH_FACTOR_WEIGHTS
        }
        raw_index = sum(weighted_points.values())
        health_index = int(max(15, min(99, round(raw_index))))

        if health_index < 36:
            tier = "critical"
        elif health_index < 55:
            tier = "at_risk"
        elif health_index < 70:
            tier = "fair"
        elif health_index < 85:
            tier = "good"
        else:
            tier = "excellent"

        spoilage_stress_demo = int((digest[4] / 255.0) * 40)

        p["health_index"] = health_index
        p["health_tier"] = tier
        p["health_factors"] = factors
        p["health_weighted_points"] = weighted_points
        p["health_index_raw"] = round(raw_index, 2)
        p["weekly_sales_usd"] = weekly_sales_usd
        p["spoilage_stress_demo"] = spoilage_stress_demo
        p["metrics_note"] = "synthetic_demo"
        out.append(p)
    return out


def get_health_factor_weights() -> dict[str, float]:
    """Exposed for API / templates (same weights used in enrich)."""
    return dict(HEALTH_FACTOR_WEIGHTS)


def get_dc_grocery_pins(*, force_refresh: bool = False) -> dict:
    """
    Return { "pins": [...], "source": "cache"|"live"|"fallback", "fetched_at": iso|None }.
    """
    if not force_refresh and os.path.isfile(CACHE_FILE):
        age = time.time() - os.path.getmtime(CACHE_FILE)
        if age < CACHE_MAX_AGE_SEC:
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                pins = cached.get("pins") or []
                if pins:
                    pins = enrich_pins_with_demo_metrics(pins)
                    return {
                        "pins": pins,
                        "source": "cache",
                        "fetched_at": cached.get("fetched_at"),
                    }
            except (OSError, json.JSONDecodeError, TypeError):
                pass

    pins: list[dict] = []
    fetched_at = None
    src = "fallback"
    try:
        pins = _fetch_overpass_live()
        fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        src = "live"
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, ValueError):
        pins = _load_fallback()
        src = "fallback"

    if not pins:
        pins = _load_fallback()
        src = "fallback"

    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"pins": pins, "fetched_at": fetched_at, "source": src}, f, indent=0)
    except OSError:
        pass

    pins = enrich_pins_with_demo_metrics(pins)
    return {"pins": pins, "source": src, "fetched_at": fetched_at}

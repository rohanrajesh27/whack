#!/usr/bin/env python3
"""Check MongoDB connectivity. From project root: python scripts/ping_mongo.py"""

import os
import sys

# Project root on path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Load .env if python-dotenv is installed (optional)
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass

from mongo_db import close_mongo_client, get_mongo_db, mongo_ping


def main() -> None:
    try:
        info = mongo_ping()
        db = get_mongo_db()
        print("MongoDB OK")
        print("  version:", info.get("version", "?"))
        print("  database:", db.name)
        print("  URI (masked):", _mask_uri(os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27017")))
    except Exception as e:
        print("MongoDB connection failed:", e, file=sys.stderr)
        sys.exit(1)
    finally:
        close_mongo_client()


def _mask_uri(uri: str) -> str:
    if "@" not in uri:
        return uri
    head, tail = uri.split("@", 1)
    if "://" in head:
        scheme, rest = head.split("://", 1)
        if ":" in rest:
            user, _ = rest.split(":", 1)
            return f"{scheme}://{user}:****@{tail}"
    return uri


if __name__ == "__main__":
    main()

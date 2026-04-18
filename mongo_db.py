"""
MongoDB connection helpers for VitalShelf.

Usage (any module):
    from mongo_db import get_mongo_db

    db = get_mongo_db()
    db.demo_events.insert_one({"event": "ping", "source": "flask"})

Configuration (environment variables):
    MONGODB_URI      — default mongodb://127.0.0.1:27017
    MONGODB_DB_NAME  — default vitalshelf

Local server: docker compose up -d mongodb
Atlas: set MONGODB_URI to your SRV connection string (include user/password in the URI).
"""

from __future__ import annotations

import os
from typing import Optional

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

from urllib.parse import urlparse

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import ConfigurationError

_client: Optional[MongoClient] = None


def _normalize_mongodb_uri(uri: str) -> str:
    """Strip .env quirks: surrounding quotes, newlines, stray spaces."""
    u = (uri or "").strip()
    if (u.startswith('"') and u.endswith('"')) or (u.startswith("'") and u.endswith("'")):
        u = u[1:-1].strip()
    u = "".join(u.splitlines()).replace("\t", "")
    return u.strip()


def _check_srv_hostname(uri: str) -> None:
    """Catch common Atlas copy/paste mistakes before dnspython raises EmptyLabel."""
    if not uri.startswith("mongodb+srv://"):
        return
    parsed = urlparse(uri)
    host = parsed.hostname
    if not host:
        raise ConfigurationError(
            "MONGODB_URI has no hostname after @. Example: "
            "mongodb+srv://USER:PASS@cluster0.abcd123.mongodb.net/ — re-copy from Atlas → Connect → Drivers."
        )
    if ".." in host or host.startswith(".") or host.endswith("."):
        raise ConfigurationError(
            f"MONGODB_URI hostname is invalid ({host!r}). Remove extra dots or line breaks; paste the URI as one line."
        )
    if any(part == "" for part in host.split(".")):
        raise ConfigurationError(
            f"MONGODB_URI hostname has an empty segment ({host!r}). Usually a typo, stray @, or an unencoded @ in your password "
            "(use %40 instead of @ in the password part)."
        )


def get_mongo_client() -> MongoClient:
    """One client per process (connection pool inside PyMongo)."""
    global _client
    if _client is None:
        uri = _normalize_mongodb_uri(os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27017"))
        _check_srv_hostname(uri)
        try:
            _client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        except ConfigurationError as e:
            msg = str(e)
            hint = ""
            if "DNS label is empty" in msg or "EmptyLabel" in msg:
                hint = (
                    " — Usually: line break inside MONGODB_URI, a typo like '..' in the host, "
                    "or an @ in the password (encode as %40). Re-copy the string from Atlas → Connect → Drivers."
                )
            elif "password" not in msg.lower():
                hint = " — If the password has @ # : / ?, URL-encode it (see https://www.urlencoder.org/)."
            raise ConfigurationError(msg + hint) from e
    return _client


def get_mongo_db() -> Database:
    name = os.environ.get("MONGODB_DB_NAME", "vitalshelf")
    return get_mongo_client()[name]


def close_mongo_client() -> None:
    """Call on shutdown (tests or scripts) to close sockets cleanly."""
    global _client
    if _client is not None:
        _client.close()
        _client = None


def mongo_ping() -> dict:
    """Return server build info; raises if unreachable."""
    return get_mongo_client().admin.command("buildInfo")

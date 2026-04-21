import os
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


DB_PATH = Path(os.getenv("LICENSE_DB_PATH", "licenses.db"))
ADMIN_TOKEN = os.getenv("LICENSE_ADMIN_TOKEN", "")
PRODUCT_ID = os.getenv("LICENSE_PRODUCT_ID", "autopiar")

app = FastAPI(title="AutoPiar License Server", version="1.0.0")


class ActivateRequest(BaseModel):
    license_key: str = Field(min_length=4, max_length=128)
    device_id: str = Field(min_length=8, max_length=128)
    product: str = Field(default=PRODUCT_ID, max_length=64)
    hostname: str = Field(default="", max_length=256)
    platform: str = Field(default="", max_length=256)


class CreateKeyRequest(BaseModel):
    owner: str = Field(default="client", max_length=128)
    days: int = Field(default=30, ge=1, le=3650)
    max_devices: int = Field(default=1, ge=1, le=100)
    license_type: str = Field(default="user", max_length=32)
    key: Optional[str] = Field(default=None, max_length=128)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS license_keys (
                key TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                product TEXT NOT NULL,
                type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                max_devices INTEGER NOT NULL DEFAULT 1,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS license_devices (
                key TEXT NOT NULL,
                device_id TEXT NOT NULL,
                hostname TEXT NOT NULL DEFAULT '',
                platform TEXT NOT NULL DEFAULT '',
                activated_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                PRIMARY KEY (key, device_id),
                FOREIGN KEY (key) REFERENCES license_keys(key) ON DELETE CASCADE
            )
            """
        )
        conn.commit()


@app.on_event("startup")
def on_startup() -> None:
    init_db()


def require_admin(x_admin_token: str = Header(default="")) -> None:
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=500, detail="LICENSE_ADMIN_TOKEN is not configured.")
    if not secrets.compare_digest(x_admin_token, ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid admin token.")


def public_license_row(row: sqlite3.Row, devices: int = 0) -> dict:
    return {
        "key": row["key"],
        "owner": row["owner"],
        "product": row["product"],
        "type": row["type"],
        "status": row["status"],
        "max_devices": int(row["max_devices"]),
        "devices": int(devices),
        "expires_at": row["expires_at"],
        "created_at": row["created_at"],
    }


@app.get("/health")
def health() -> dict:
    return {"ok": True, "date": date.today().isoformat()}


@app.post("/api/activate")
def activate(payload: ActivateRequest) -> dict:
    init_db()
    key = payload.license_key.strip()
    now = utc_now()
    now_s = utc_iso(now)

    with connect() as conn:
        row = conn.execute("SELECT * FROM license_keys WHERE key = ?", (key,)).fetchone()
        if row is None:
            return {"ok": False, "message": "Ключ не найден."}
        if row["product"] != payload.product:
            return {"ok": False, "message": "Ключ не подходит для этого продукта."}
        if row["status"] != "active":
            return {"ok": False, "message": "Ключ отключён."}
        if parse_utc(row["expires_at"]) < now:
            return {"ok": False, "message": "Срок действия ключа истёк."}

        existing = conn.execute(
            "SELECT * FROM license_devices WHERE key = ? AND device_id = ?",
            (key, payload.device_id),
        ).fetchone()
        device_count = int(
            conn.execute("SELECT COUNT(*) FROM license_devices WHERE key = ?", (key,)).fetchone()[0]
        )

        if existing is None and device_count >= int(row["max_devices"]):
            return {"ok": False, "message": "Превышен лимит устройств для ключа."}

        if existing is None:
            conn.execute(
                """
                INSERT INTO license_devices(key, device_id, hostname, platform, activated_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (key, payload.device_id, payload.hostname, payload.platform, now_s, now_s),
            )
            device_count += 1
        else:
            conn.execute(
                """
                UPDATE license_devices
                SET hostname = ?, platform = ?, last_seen_at = ?
                WHERE key = ? AND device_id = ?
                """,
                (payload.hostname, payload.platform, now_s, key, payload.device_id),
            )
        conn.commit()

    return {
        "ok": True,
        "message": "Лицензия активна.",
        "owner": row["owner"],
        "type": row["type"],
        "expires_at": row["expires_at"],
        "devices": device_count,
        "max_devices": int(row["max_devices"]),
        "server_time": now_s,
    }


@app.post("/admin/keys", dependencies=[Depends(require_admin)])
def create_key(payload: CreateKeyRequest) -> dict:
    init_db()
    key = (payload.key or "").strip() or "AP-" + secrets.token_urlsafe(18).replace("-", "").replace("_", "")[:24]
    now = utc_now()
    expires_at = utc_iso(now + timedelta(days=payload.days))
    with connect() as conn:
        try:
            conn.execute(
                """
                INSERT INTO license_keys(key, owner, product, type, status, max_devices, expires_at, created_at)
                VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (key, payload.owner, PRODUCT_ID, payload.license_type, int(payload.max_devices), expires_at, utc_iso(now)),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="Key already exists.")
        row = conn.execute("SELECT * FROM license_keys WHERE key = ?", (key,)).fetchone()
    return {"ok": True, "license": public_license_row(row)}


@app.get("/admin/keys", dependencies=[Depends(require_admin)])
def list_keys() -> dict:
    init_db()
    with connect() as conn:
        rows = conn.execute("SELECT * FROM license_keys ORDER BY created_at DESC").fetchall()
        result = []
        for row in rows:
            devices = conn.execute("SELECT COUNT(*) FROM license_devices WHERE key = ?", (row["key"],)).fetchone()[0]
            result.append(public_license_row(row, devices))
    return {"ok": True, "licenses": result}


@app.post("/admin/keys/{license_key}/revoke", dependencies=[Depends(require_admin)])
def revoke_key(license_key: str) -> dict:
    init_db()
    with connect() as conn:
        conn.execute("UPDATE license_keys SET status = 'revoked' WHERE key = ?", (license_key,))
        conn.commit()
    return {"ok": True}

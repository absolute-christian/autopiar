import argparse
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


DB_PATH = Path("licenses.db")
PRODUCT_ID = "autopiar"


def utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    from server import init_db as server_init_db

    server_init_db()


def make_key() -> str:
    return "AP-" + secrets.token_urlsafe(18).replace("-", "").replace("_", "")[:24]


def create(args) -> None:
    init_db()
    key = args.key or make_key()
    now = datetime.now(timezone.utc)
    expires_at = utc_iso(now + timedelta(days=args.days))
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO license_keys(key, owner, product, type, status, max_devices, expires_at, created_at)
            VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
            """,
            (key, args.owner, PRODUCT_ID, args.type, args.max_devices, expires_at, utc_iso(now)),
        )
        conn.commit()
    print(key)


def list_keys(_args) -> None:
    init_db()
    with connect() as conn:
        rows = conn.execute("SELECT * FROM license_keys ORDER BY created_at DESC").fetchall()
        for row in rows:
            devices = conn.execute("SELECT COUNT(*) FROM license_devices WHERE key = ?", (row["key"],)).fetchone()[0]
            print(
                f"{row['key']} | {row['owner']} | {row['status']} | "
                f"{devices}/{row['max_devices']} devices | expires {row['expires_at']}"
            )


def revoke(args) -> None:
    init_db()
    with connect() as conn:
        conn.execute("UPDATE license_keys SET status = 'revoked' WHERE key = ?", (args.key,))
        conn.commit()
    print("revoked")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage AutoPiar license keys.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    create_p = sub.add_parser("create")
    create_p.add_argument("--owner", default="client")
    create_p.add_argument("--days", type=int, default=30)
    create_p.add_argument("--max-devices", type=int, default=1)
    create_p.add_argument("--type", default="user")
    create_p.add_argument("--key", default="")
    create_p.set_defaults(func=create)

    list_p = sub.add_parser("list")
    list_p.set_defaults(func=list_keys)

    revoke_p = sub.add_parser("revoke")
    revoke_p.add_argument("key")
    revoke_p.set_defaults(func=revoke)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

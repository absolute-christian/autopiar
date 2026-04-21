import os
import secrets
import sqlite3
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field


DB_PATH = Path(os.getenv("LICENSE_DB_PATH", "licenses.db"))
BACKUP_DIR = Path(os.getenv("LICENSE_BACKUP_DIR", "backups"))
ADMIN_TOKEN = os.getenv("LICENSE_ADMIN_TOKEN", "")
PRODUCT_ID = os.getenv("LICENSE_PRODUCT_ID", "autopiar")

app = FastAPI(title="AutoPiar License Server", version="1.0.0")


def html_page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      --bg:#070512; --card:#100B2A; --card2:#171038; --line:#5227FF;
      --pink:#FF9FFC; --text:#F4F7FF; --muted:#B9B3D8; --green:#39FF9A; --red:#FF4D7D;
    }}
    * {{ box-sizing:border-box; }}
    body {{
      margin:0; min-height:100vh; color:var(--text);
      font-family:Segoe UI, Arial, sans-serif;
      background:
        radial-gradient(circle at 20% 10%, rgba(82,39,255,.35), transparent 30%),
        radial-gradient(circle at 80% 0%, rgba(255,159,252,.18), transparent 26%),
        linear-gradient(135deg, #05030D, #120B31 55%, #24106E);
    }}
    main {{ max-width:1360px; margin:0 auto; padding:32px 18px; }}
    h1 {{ margin:0 0 8px; font-size:30px; letter-spacing:.2px; }}
    p {{ color:var(--muted); }}
    .grid {{ display:grid; grid-template-columns:minmax(320px, 360px) minmax(560px, 1fr); gap:18px; align-items:start; }}
    .wide {{ grid-column:1 / -1; }}
    .card {{
      background:rgba(12,8,38,.86); border:1px solid rgba(255,159,252,.22);
      border-radius:22px; padding:18px; box-shadow:0 18px 70px rgba(0,0,0,.35);
    }}
    .notice {{
      margin:0 0 18px; padding:14px 16px; border-radius:18px;
      border:1px solid rgba(255,159,252,.28); background:rgba(255,159,252,.08);
      color:var(--muted);
    }}
    label {{ display:block; color:var(--muted); font-size:12px; margin:12px 0 6px; }}
    input, select {{
      width:100%; padding:13px 14px; border-radius:14px; outline:none;
      border:1px solid rgba(82,39,255,.55); background:#070512; color:var(--text);
    }}
    input:focus {{ border-color:var(--pink); }}
    button, .button {{
      display:inline-block; border:0; cursor:pointer; text-decoration:none;
      margin-top:14px; padding:12px 16px; border-radius:14px; color:#100A24;
      font-weight:800; background:linear-gradient(90deg, var(--line), var(--pink));
      white-space:nowrap;
    }}
    .table-wrap {{ width:100%; overflow-x:auto; border-radius:18px; }}
    table {{ width:100%; min-width:1080px; border-collapse:collapse; }}
    th, td {{ text-align:left; padding:12px; border-bottom:1px solid rgba(255,255,255,.08); vertical-align:middle; }}
    th {{ color:#fff; background:rgba(82,39,255,.24); font-size:12px; }}
    td {{ color:#EAF1FF; font-size:13px; }}
    code {{ color:var(--pink); }}
    .key-cell {{ min-width:420px; width:44%; }}
    .key-pill {{
      display:inline-block; max-width:min(620px, 52vw); overflow:hidden; text-overflow:ellipsis;
      white-space:nowrap; padding:7px 9px; border-radius:10px;
      background:rgba(255,159,252,.08); border:1px solid rgba(255,159,252,.18);
      font-family:Consolas, monospace;
    }}
    .key-created {{
      display:block; margin-top:8px; max-width:100%; overflow:auto; white-space:nowrap;
      padding:10px 12px; border-radius:12px; background:rgba(57,255,154,.08);
      border:1px solid rgba(57,255,154,.22); font-family:Consolas, monospace;
    }}
    .actions {{ width:120px; text-align:right; }}
    .status-active {{ color:var(--green); font-weight:800; }}
    .status-revoked {{ color:var(--red); font-weight:800; }}
    .copy {{ user-select:all; }}
    @media (max-width: 980px) {{ .grid {{ grid-template-columns:1fr; }} .wide {{ grid-column:auto; }} table {{ display:block; overflow-x:auto; }} }}
  </style>
</head>
<body>
<main>{body}</main>
</body>
</html>"""
    )


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


def safe_backup_label(label: str) -> str:
    clean = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(label or "manual"))
    return clean[:48] or "manual"


def create_sqlite_backup(label: str = "manual") -> Path:
    init_db()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().strftime("%Y%m%d-%H%M%S")
    backup_path = BACKUP_DIR / f"licenses-{stamp}-{safe_backup_label(label)}.db"
    source = sqlite3.connect(DB_PATH)
    try:
        dest = sqlite3.connect(backup_path)
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()
    return backup_path


def list_backup_files() -> list[Path]:
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.glob("licenses-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)


def export_license_data() -> dict:
    init_db()
    with connect() as conn:
        keys = [
            dict(row)
            for row in conn.execute("SELECT * FROM license_keys ORDER BY created_at DESC").fetchall()
        ]
        devices = [
            dict(row)
            for row in conn.execute("SELECT * FROM license_devices ORDER BY last_seen_at DESC").fetchall()
        ]
    return {
        "product": PRODUCT_ID,
        "exported_at": utc_iso(utc_now()),
        "license_keys": keys,
        "license_devices": devices,
    }


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


def is_admin_token(token: str) -> bool:
    return bool(ADMIN_TOKEN) and secrets.compare_digest(token or "", ADMIN_TOKEN)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "date": date.today().isoformat()}


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return html_page(
        "AutoPiar License",
        """
        <h1>AutoPiar License Server</h1>
        <p>Сервер работает. Для управления ключами откройте админ-панель.</p>
        <a class="button" href="/admin">Открыть админ-панель</a>
        """,
    )


@app.get("/admin", response_class=HTMLResponse)
def admin_page(token: str = Query(default=""), created: str = Query(default="")) -> HTMLResponse:
    if not is_admin_token(token):
        error = ""
        if token:
            error = "<p style='color:var(--red);font-weight:800'>Неверный админ-токен.</p>"
        return html_page(
            "AutoPiar Admin",
            f"""
            <h1>Вход в админ-панель</h1>
            <p>Введите `LICENSE_ADMIN_TOKEN`, который задан на хостинге.</p>
            {error}
            <form method="get" action="/admin" class="card" style="max-width:420px">
              <label>Админ-токен</label>
              <input name="token" type="password" placeholder="LICENSE_ADMIN_TOKEN" autofocus>
              <button type="submit">Войти</button>
            </form>
            """,
        )

    init_db()
    with connect() as conn:
        rows = conn.execute("SELECT * FROM license_keys ORDER BY created_at DESC").fetchall()
        table_rows = []
        for row in rows:
            devices = conn.execute("SELECT COUNT(*) FROM license_devices WHERE key = ?", (row["key"],)).fetchone()[0]
            status_class = "status-active" if row["status"] == "active" else "status-revoked"
            revoke = (
                f"<form method='post' action='/admin/revoke' style='margin:0'>"
                f"<input type='hidden' name='token' value='{token}'>"
                f"<input type='hidden' name='license_key' value='{row['key']}'>"
                f"<button type='submit' style='margin:0;padding:8px 10px'>Отозвать</button>"
                f"</form>"
            )
            table_rows.append(
                f"""
                <tr>
                  <td class="key-cell"><code class="copy key-pill" title="{row['key']}">{row['key']}</code></td>
                  <td>{row['owner']}</td>
                  <td><span class="{status_class}">{row['status']}</span></td>
                  <td>{devices}/{row['max_devices']}</td>
                  <td>{row['expires_at']}</td>
                  <td class="actions">{revoke if row['status'] == 'active' else ''}</td>
                </tr>
                """
            )

    created_block = (
        f"<div class='card' style='border-color:rgba(57,255,154,.45);margin-bottom:18px'>"
        f"<p style='margin:0;color:var(--green);font-weight:800'>Создан ключ:</p>"
        f"<code class='copy key-created'>{created}</code></div>"
        if created
        else ""
    )
    backup_files = list_backup_files()[:8]
    backup_items = "".join(
        f"<li><a href='/admin/backup/file/{item.name}?token={token}' style='color:var(--pink)'>{item.name}</a></li>"
        for item in backup_files
    ) or "<li style='color:var(--muted)'>Бэкапов пока нет.</li>"
    rows_html = "\n".join(table_rows) or "<tr><td colspan='6'>Ключей пока нет.</td></tr>"
    storage_warning = (
        "<div class='notice'><b>Если ключи пропадают после деплоя:</b> подключите Railway Volume "
        "и задайте переменные <code>LICENSE_DB_PATH=/data/licenses.db</code> и "
        "<code>LICENSE_BACKUP_DIR=/data/backups</code>. Без постоянного диска SQLite может "
        "очищаться при пересборке контейнера.</div>"
        if not DB_PATH.is_absolute()
        else ""
    )
    return html_page(
        "AutoPiar Admin",
        f"""
        <h1>Панель лицензий AutoPiar</h1>
        <p>Создавайте ключи, ограничивайте срок и количество устройств. Клиент вводит только ключ.</p>
        {storage_warning}
        {created_block}
        <div class="grid">
          <form method="post" action="/admin/create" class="card">
            <input type="hidden" name="token" value="{token}">
            <h2 style="margin-top:0">Создать ключ</h2>
            <label>Клиент / заметка</label>
            <input name="owner" value="client">
            <label>Срок, дней</label>
            <input name="days" type="number" min="1" max="3650" value="30">
            <label>Лимит устройств</label>
            <input name="max_devices" type="number" min="1" max="100" value="1">
            <label>Тип</label>
            <select name="license_type"><option value="user">user</option><option value="dev">dev</option></select>
            <button type="submit">Создать ключ</button>
          </form>
          <section class="card">
            <h2 style="margin-top:0">Бэкапы</h2>
            <p>Скачайте БД перед переносом на другой хостинг. JSON удобен для миграции в другую БД.</p>
            <a class="button" href="/admin/backup/download?token={token}">Скачать SQLite</a>
            <a class="button" href="/admin/export.json?token={token}">Экспорт JSON</a>
            <form method="post" action="/admin/backup/create" style="margin-top:10px">
              <input type="hidden" name="token" value="{token}">
              <button type="submit">Создать snapshot</button>
            </form>
            <ul style="padding-left:18px;line-height:1.8">{backup_items}</ul>
          </section>
          <section class="card wide">
            <h2 style="margin-top:0">Ключи</h2>
            <div class="table-wrap">
              <table>
                <thead><tr><th>Ключ</th><th>Клиент</th><th>Статус</th><th>Устройства</th><th>До</th><th></th></tr></thead>
                <tbody>{rows_html}</tbody>
              </table>
            </div>
          </section>
        </div>
        """,
    )


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

    if existing is None:
        try:
            create_sqlite_backup("activation")
        except Exception:
            pass

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
    try:
        create_sqlite_backup("create_key")
    except Exception:
        pass
    return {"ok": True, "license": public_license_row(row)}


@app.post("/admin/create")
def admin_create_key(
    token: str = Form(...),
    owner: str = Form(default="client"),
    days: int = Form(default=30),
    max_devices: int = Form(default=1),
    license_type: str = Form(default="user"),
):
    if not is_admin_token(token):
        raise HTTPException(status_code=401, detail="Invalid admin token.")
    payload = CreateKeyRequest(
        owner=owner,
        days=days,
        max_devices=max_devices,
        license_type=license_type,
    )
    created = create_key(payload)["license"]["key"]
    return RedirectResponse(url=f"/admin?token={token}&created={created}", status_code=303)


@app.get("/admin/export.json")
def admin_export_json(token: str = Query(default="")):
    if not is_admin_token(token):
        raise HTTPException(status_code=401, detail="Invalid admin token.")
    data = export_license_data()
    headers = {
        "Content-Disposition": f"attachment; filename=autopiar-licenses-{utc_now().strftime('%Y%m%d-%H%M%S')}.json"
    }
    return JSONResponse(content=data, headers=headers)


@app.get("/admin/backup/download")
def admin_download_current_db(token: str = Query(default="")):
    if not is_admin_token(token):
        raise HTTPException(status_code=401, detail="Invalid admin token.")
    backup_path = create_sqlite_backup("download")
    return FileResponse(
        backup_path,
        media_type="application/octet-stream",
        filename=backup_path.name,
    )


@app.post("/admin/backup/create")
def admin_create_backup(token: str = Form(...)):
    if not is_admin_token(token):
        raise HTTPException(status_code=401, detail="Invalid admin token.")
    create_sqlite_backup("manual")
    return RedirectResponse(url=f"/admin?token={token}", status_code=303)


@app.get("/admin/backup/file/{filename}")
def admin_download_backup_file(filename: str, token: str = Query(default="")):
    if not is_admin_token(token):
        raise HTTPException(status_code=401, detail="Invalid admin token.")
    if "/" in filename or "\\" in filename or not filename.endswith(".db"):
        raise HTTPException(status_code=400, detail="Invalid filename.")
    path = BACKUP_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Backup not found.")
    return FileResponse(path, media_type="application/octet-stream", filename=path.name)


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
    try:
        create_sqlite_backup("revoke_key")
    except Exception:
        pass
    return {"ok": True}


@app.post("/admin/revoke")
def admin_revoke_key(token: str = Form(...), license_key: str = Form(...)):
    if not is_admin_token(token):
        raise HTTPException(status_code=401, detail="Invalid admin token.")
    revoke_key(license_key)
    return RedirectResponse(url=f"/admin?token={token}", status_code=303)

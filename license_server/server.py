import os
import secrets
import sqlite3
import json
import html as html_utils
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field


DEFAULT_DATA_DIR = Path(os.getenv("LICENSE_DATA_DIR", "")).expanduser() if os.getenv("LICENSE_DATA_DIR") else Path(__file__).resolve().parent
if Path("/data").exists() and not os.getenv("LICENSE_DATA_DIR"):
    DEFAULT_DATA_DIR = Path("/data")

DB_PATH = Path(os.getenv("LICENSE_DB_PATH", str(DEFAULT_DATA_DIR / "licenses.db"))).expanduser()
BACKUP_DIR = Path(os.getenv("LICENSE_BACKUP_DIR", str(DEFAULT_DATA_DIR / "backups"))).expanduser()
ADMIN_TOKEN = os.getenv("LICENSE_ADMIN_TOKEN", "")
PRODUCT_ID = os.getenv("LICENSE_PRODUCT_ID", "autopiar")

app = FastAPI(title="AutoPiar License Server", version="1.0.0")


def html_page(title: str, body: str) -> HTMLResponse:
    template = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__TITLE__</title>
  <style>
    :root {
      --bg:#05030d; --panel:#0d0822; --panel2:#130d2e; --line:#5227FF;
      --pink:#FF9FFC; --text:#F7F4FF; --muted:#BDB6DA; --soft:#8f82ff;
      --green:#59ffb1; --red:#ff5d8f; --amber:#ffd36e; --border:rgba(255,159,252,.22);
    }
    * { box-sizing:border-box; }
    html { scroll-behavior:smooth; }
    body {
      margin:0; min-height:100vh; color:var(--text); overflow-x:hidden;
      font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background:#05030d;
    }
    body::before {
      content:""; position:fixed; inset:0; pointer-events:none; z-index:-2;
      background:
        radial-gradient(circle at 18% 8%, rgba(82,39,255,.42), transparent 34%),
        radial-gradient(circle at 84% 6%, rgba(255,159,252,.22), transparent 28%),
        radial-gradient(circle at 50% 105%, rgba(82,39,255,.25), transparent 42%),
        linear-gradient(135deg, #05030d 0%, #0c0620 48%, #150a36 100%);
    }
    #dark-veil {
      position:fixed; inset:0; width:100%; height:100%; z-index:-1; opacity:.72;
      filter:saturate(1.08) contrast(1.08);
    }
    ::selection { background:rgba(255,159,252,.35); color:#fff; }
    ::-webkit-scrollbar { width:10px; height:10px; }
    ::-webkit-scrollbar-track { background:#080515; border-radius:999px; }
    ::-webkit-scrollbar-thumb {
      background:linear-gradient(180deg, rgba(82,39,255,.9), rgba(255,159,252,.86));
      border-radius:999px; border:2px solid #080515;
    }
    main { width:min(1380px, calc(100% - 34px)); margin:0 auto; padding:34px 0 48px; }
    h1, h2, h3, p { margin-top:0; }
    h1 { font-size:clamp(34px, 5vw, 68px); line-height:.95; letter-spacing:-.06em; margin-bottom:18px; }
    h2 { font-size:22px; letter-spacing:-.03em; }
    p { color:var(--muted); line-height:1.62; }
    code { color:#ffd6ff; }
    a { color:#ffd6ff; }
    .hero {
      min-height:210px; display:grid; align-items:end; margin-bottom:22px; position:relative;
      padding:30px; border-radius:32px; overflow:hidden;
      border:1px solid rgba(255,255,255,.12); background:linear-gradient(135deg, rgba(13,8,34,.72), rgba(19,13,46,.48));
      box-shadow:0 24px 100px rgba(0,0,0,.38), inset 0 1px 0 rgba(255,255,255,.08);
    }
    .hero::after {
      content:""; position:absolute; inset:auto -18% -58% 34%; height:230px; pointer-events:none;
      background:radial-gradient(circle, rgba(255,159,252,.34), transparent 63%);
      filter:blur(8px);
    }
    .hero-kicker { color:#FF9FFC; font-weight:900; letter-spacing:.18em; text-transform:uppercase; font-size:12px; }
    .hero-copy { max-width:760px; position:relative; z-index:1; }
    .hero-meta { display:flex; gap:10px; flex-wrap:wrap; margin-top:18px; }
    .pill {
      display:inline-flex; align-items:center; gap:8px; padding:9px 12px; border-radius:999px;
      border:1px solid rgba(255,255,255,.12); background:rgba(255,255,255,.055); color:#ede8ff;
      font-size:12px; font-weight:800; backdrop-filter:blur(12px);
    }
    .dot { width:8px; height:8px; border-radius:999px; background:var(--green); box-shadow:0 0 18px var(--green); }
    .grid { display:grid; grid-template-columns:minmax(320px, 390px) minmax(560px, 1fr); gap:18px; align-items:start; }
    .wide { grid-column:1 / -1; }
    .bento-card, .card {
      position:relative; isolation:isolate; overflow:hidden; border-radius:28px; padding:22px;
      border:1px solid var(--border); background:linear-gradient(145deg, rgba(15,9,39,.88), rgba(10,6,25,.76));
      box-shadow:0 22px 80px rgba(0,0,0,.36), inset 0 1px 0 rgba(255,255,255,.07);
      transition:transform .28s ease, border-color .28s ease, box-shadow .28s ease;
    }
    .bento-card::before, .card::before {
      content:""; position:absolute; inset:0; z-index:-1; opacity:0; transition:opacity .28s ease;
      background:radial-gradient(520px circle at var(--mx, 50%) var(--my, 0%), rgba(255,159,252,.18), transparent 42%);
    }
    .bento-card:hover, .card:hover { transform:translateY(-3px); border-color:rgba(255,159,252,.44); box-shadow:0 28px 90px rgba(82,39,255,.2); }
    .bento-card:hover::before, .card:hover::before { opacity:1; }
    .notice {
      margin:0 0 18px; padding:15px 17px; border-radius:20px; color:#e9e2ff;
      border:1px solid rgba(255,211,110,.24); background:linear-gradient(135deg, rgba(255,211,110,.13), rgba(82,39,255,.08));
    }
    label { display:block; color:var(--muted); font-size:12px; margin:13px 0 7px; font-weight:800; }
    input, select {
      width:100%; padding:14px 15px; border-radius:16px; outline:none;
      border:1px solid rgba(82,39,255,.55); background:rgba(5,3,13,.74); color:var(--text);
      transition:border-color .2s ease, box-shadow .2s ease, background .2s ease;
    }
    input:focus, select:focus { border-color:var(--pink); box-shadow:0 0 0 4px rgba(255,159,252,.1); background:rgba(7,5,18,.95); }
    button, .button {
      display:inline-flex; align-items:center; justify-content:center; gap:8px; border:0; cursor:pointer; text-decoration:none;
      margin-top:14px; padding:13px 17px; border-radius:16px; color:#100A24;
      font-weight:950; letter-spacing:-.02em; background:linear-gradient(100deg, var(--line), var(--pink));
      white-space:nowrap; box-shadow:0 12px 28px rgba(82,39,255,.28); transition:transform .2s ease, filter .2s ease;
    }
    button:hover, .button:hover { transform:translateY(-2px); filter:saturate(1.14); }
    .button.secondary { color:#f6f2ff; background:rgba(255,255,255,.08); border:1px solid rgba(255,255,255,.14); box-shadow:none; }
    .button.danger { background:linear-gradient(100deg, #ff4d7d, #ff9ffc); }
    .button-row { display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
    .stats { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:12px; margin-bottom:18px; }
    .stat { padding:16px; border-radius:22px; background:rgba(255,255,255,.055); border:1px solid rgba(255,255,255,.09); }
    .stat b { display:block; font-size:24px; letter-spacing:-.05em; }
    .stat span { color:var(--muted); font-size:12px; }
    .created-key { border-color:rgba(89,255,177,.45); margin-bottom:18px; }
    .created-key p { margin:0 0 8px; color:var(--green); font-weight:900; }
    .key-created, .key-code {
      display:block; max-width:100%; overflow:auto; white-space:nowrap; user-select:all;
      padding:11px 12px; border-radius:16px; color:#ffd6ff; font-family:Consolas, ui-monospace, monospace;
      background:rgba(255,159,252,.08); border:1px solid rgba(255,159,252,.18);
    }
    .keys-shell { position:relative; }
    .keys-list {
      max-height:590px; overflow:auto; padding:13px; border-radius:24px;
      background:rgba(5,3,13,.48); border:1px solid rgba(255,255,255,.08);
      scroll-behavior:smooth;
    }
    .keys-list::before, .keys-list::after { content:""; position:sticky; left:0; right:0; display:block; height:26px; pointer-events:none; z-index:2; }
    .keys-list::before { top:-13px; margin:-13px -13px 0; background:linear-gradient(to bottom, rgba(7,4,18,.96), transparent); }
    .keys-list::after { bottom:-13px; margin:0 -13px -13px; background:linear-gradient(to top, rgba(7,4,18,.96), transparent); }
    .key-item {
      display:grid; grid-template-columns:minmax(0, 1.25fr) .58fr .46fr .42fr .65fr auto; gap:12px; align-items:center;
      margin-bottom:12px; padding:14px; border-radius:22px; background:linear-gradient(135deg, rgba(255,255,255,.07), rgba(82,39,255,.08));
      border:1px solid rgba(255,255,255,.1); box-shadow:none;
      animation:listIn .58s cubic-bezier(.2,.82,.2,1) both; animation-delay:calc(var(--i, 0) * 48ms);
    }
    .key-item:last-child { margin-bottom:0; }
    .key-label { color:var(--muted); font-size:11px; font-weight:900; text-transform:uppercase; letter-spacing:.08em; margin-bottom:5px; }
    .key-value { color:#fff; font-size:13px; overflow:hidden; text-overflow:ellipsis; }
    .status { display:inline-flex; align-items:center; gap:7px; font-weight:950; }
    .status::before { content:""; width:8px; height:8px; border-radius:50%; background:currentColor; box-shadow:0 0 15px currentColor; }
    .status-active { color:var(--green); }
    .status-revoked { color:var(--red); }
    .empty-state { padding:30px; text-align:center; color:var(--muted); }
    .backup-list { padding-left:18px; line-height:1.9; color:var(--muted); max-height:165px; overflow:auto; }
    [data-animate] { opacity:0; transform:translateY(34px) scale(.985); filter:blur(8px); }
    [data-animate].is-visible { opacity:1; transform:translateY(0) scale(1); filter:blur(0); transition:opacity .72s ease, transform .72s cubic-bezier(.2,.82,.2,1), filter .72s ease; transition-delay:calc(var(--i, 0) * 65ms); }
    @keyframes listIn { from { opacity:0; transform:translateY(22px) scale(.985); } to { opacity:1; transform:translateY(0) scale(1); } }
    @media (max-width: 1050px) {
      .grid { grid-template-columns:1fr; }
      .wide { grid-column:auto; }
      .key-item { grid-template-columns:1fr 1fr; }
      .stats { grid-template-columns:1fr; }
    }
    @media (max-width: 620px) {
      main { width:min(100% - 22px, 1380px); padding-top:18px; }
      .hero, .card, .bento-card { border-radius:22px; padding:18px; }
      .key-item { grid-template-columns:1fr; }
      h1 { font-size:40px; }
    }
  </style>
</head>
<body>
<canvas id="dark-veil" aria-hidden="true"></canvas>
<main>__BODY__</main>
<script>
(() => {
  const canvas = document.getElementById('dark-veil');
  const ctx = canvas.getContext('2d');
  let w = 0, h = 0, t = 0;
  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = canvas.width = Math.floor(innerWidth * dpr);
    h = canvas.height = Math.floor(innerHeight * dpr);
    canvas.style.width = innerWidth + 'px';
    canvas.style.height = innerHeight + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  };
  const draw = () => {
    t += 0.006;
    ctx.clearRect(0, 0, innerWidth, innerHeight);
    ctx.globalCompositeOperation = 'lighter';
    for (let i = 0; i < 9; i++) {
      const x = innerWidth * (.08 + i * .12) + Math.sin(t * 1.8 + i) * 90;
      const y = innerHeight * (.18 + Math.sin(t + i * .7) * .22);
      const g = ctx.createRadialGradient(x, y, 0, x, y, 240 + i * 22);
      g.addColorStop(0, i % 2 ? 'rgba(255,159,252,.13)' : 'rgba(82,39,255,.16)');
      g.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(x, y, 260 + i * 20, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalCompositeOperation = 'source-over';
    requestAnimationFrame(draw);
  };
  resize(); draw(); addEventListener('resize', resize);

  document.querySelectorAll('.bento-card, .card').forEach(card => {
    card.addEventListener('pointermove', event => {
      const rect = card.getBoundingClientRect();
      card.style.setProperty('--mx', `${event.clientX - rect.left}px`);
      card.style.setProperty('--my', `${event.clientY - rect.top}px`);
    });
  });

  const reveal = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-visible');
        reveal.unobserve(entry.target);
      }
    });
  }, { threshold: .12 });
  document.querySelectorAll('[data-animate]').forEach(el => reveal.observe(el));

  document.querySelectorAll('[data-copy]').forEach(el => {
    el.addEventListener('click', async () => {
      const value = el.getAttribute('data-copy') || el.textContent.trim();
      try { await navigator.clipboard.writeText(value); } catch (_) {}
      const old = el.getAttribute('data-label') || el.textContent;
      el.setAttribute('data-label', old);
      el.textContent = 'Скопировано';
      setTimeout(() => { el.textContent = old; }, 900);
    });
  });
})();
</script>
</body>
</html>"""
    return HTMLResponse(
        template.replace("__TITLE__", html_utils.escape(title)).replace("__BODY__", body)
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


def h(value) -> str:
    return html_utils.escape(str(value or ""), quote=False)


def ha(value) -> str:
    return html_utils.escape(str(value or ""), quote=True)


def admin_url(token: str, **params) -> str:
    query = {"token": token}
    query.update({key: value for key, value in params.items() if value is not None})
    return "/admin?" + urlencode(query)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "date": date.today().isoformat()}


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return html_page(
        "AutoPiar License",
        """
        <section class="hero" data-animate>
          <div class="hero-copy">
            <div class="hero-kicker">license core</div>
            <h1>AutoPiar<br>License Server</h1>
            <p>Сервер работает. Управление ключами доступно через приватную админ-панель.</p>
            <div class="hero-meta">
              <span class="pill"><span class="dot"></span> online</span>
              <span class="pill">SQLite + backups</span>
              <span class="pill">Railway ready</span>
            </div>
            <a class="button" href="/admin">Открыть админ-панель</a>
          </div>
        </section>
        """,
    )


@app.get("/admin", response_class=HTMLResponse)
def admin_page(token: str = Query(default=""), created: str = Query(default="")) -> HTMLResponse:
    if not is_admin_token(token):
        error = ""
        if token:
            error = "<div class='notice' style='border-color:rgba(255,93,143,.38)'>Неверный админ-токен.</div>"
        return html_page(
            "AutoPiar Admin",
            f"""
            <section class="hero" data-animate>
              <div class="hero-copy">
                <div class="hero-kicker">private access</div>
                <h1>Вход в<br>админку</h1>
                <p>Введите <code>LICENSE_ADMIN_TOKEN</code>, который задан в переменных хостинга.</p>
                {error}
              </div>
            </section>
            <form method="get" action="/admin" class="card" style="max-width:480px" data-animate>
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
        active_count = 0
        revoked_count = 0
        device_total = 0
        for index, row in enumerate(rows):
            devices = conn.execute("SELECT COUNT(*) FROM license_devices WHERE key = ?", (row["key"],)).fetchone()[0]
            device_total += int(devices)
            is_active = row["status"] == "active"
            active_count += 1 if is_active else 0
            revoked_count += 0 if is_active else 1
            status_class = "status-active" if is_active else "status-revoked"
            revoke = (
                f"<form method='post' action='/admin/revoke' style='margin:0'>"
                f"<input type='hidden' name='token' value='{ha(token)}'>"
                f"<input type='hidden' name='license_key' value='{ha(row['key'])}'>"
                f"<button class='button danger' type='submit' style='margin:0;padding:10px 12px'>Отозвать</button>"
                f"</form>"
            )
            table_rows.append(
                f"""
                <article class="key-item" data-animate style="--i:{index}">
                  <div>
                    <div class="key-label">Ключ</div>
                    <button class="key-code" type="button" data-copy="{ha(row['key'])}">{h(row['key'])}</button>
                  </div>
                  <div>
                    <div class="key-label">Клиент</div>
                    <div class="key-value">{h(row['owner'])}</div>
                  </div>
                  <div>
                    <div class="key-label">Статус</div>
                    <div class="status {status_class}">{h(row['status'])}</div>
                  </div>
                  <div>
                    <div class="key-label">Устройства</div>
                    <div class="key-value">{int(devices)}/{int(row['max_devices'])}</div>
                  </div>
                  <div>
                    <div class="key-label">До</div>
                    <div class="key-value">{h(row['expires_at'])}</div>
                  </div>
                  <div>{revoke if is_active else ''}</div>
                </article>
                """
            )

    created_block = (
        f"<section class='bento-card created-key wide' data-animate>"
        f"<p>Создан ключ</p>"
        f"<button class='key-created' type='button' data-copy='{ha(created)}'>{h(created)}</button>"
        f"</section>"
        if created
        else ""
    )
    backup_files = list_backup_files()[:8]
    backup_items = "".join(
        f"<li><a href='{ha('/admin/backup/file/' + item.name + '?' + urlencode({'token': token}))}'>{h(item.name)}</a></li>"
        for item in backup_files
    ) or "<li>Бэкапов пока нет.</li>"
    rows_html = "\n".join(table_rows) or "<div class='empty-state'>Ключей пока нет. Создайте первый ключ слева.</div>"
    storage_warning = (
        "<div class='notice wide' data-animate><b>Если ключи пропадают после деплоя:</b> подключите Railway Volume "
        "и задайте переменные <code>LICENSE_DB_PATH=/data/licenses.db</code> и "
        "<code>LICENSE_BACKUP_DIR=/data/backups</code>. Без постоянного диска SQLite может "
        "очищаться при пересборке контейнера.</div>"
        if not Path(str(DB_PATH)).is_absolute() or str(DB_PATH).startswith(str(Path(__file__).resolve().parent))
        else ""
    )
    return html_page(
        "AutoPiar Admin",
        f"""
        <section class="hero" data-animate>
          <div class="hero-copy">
            <div class="hero-kicker">control room</div>
            <h1>Панель<br>лицензий</h1>
            <p>Создавайте много ключей, отслеживайте устройства и сохраняйте бэкапы базы. Клиент вводит только ключ.</p>
            <div class="hero-meta">
              <span class="pill"><span class="dot"></span> active: {active_count}</span>
              <span class="pill">revoked: {revoked_count}</span>
              <span class="pill">devices: {device_total}</span>
            </div>
          </div>
        </section>
        {storage_warning}
        {created_block}
        <div class="grid">
          <form method="post" action="/admin/create" class="bento-card" data-animate style="--i:1">
            <input type="hidden" name="token" value="{ha(token)}">
            <h2>Создать ключ</h2>
            <p>Новый ключ добавится в общий список, старые ключи не перезаписываются.</p>
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
          <section class="bento-card" data-animate style="--i:2">
            <h2>Бэкапы</h2>
            <p>Скачайте БД перед переносом на другой хостинг. JSON удобен для миграции в другую БД.</p>
            <div class="button-row">
              <a class="button" href="/admin/backup/download?{ha(urlencode({'token': token}))}">Скачать SQLite</a>
              <a class="button secondary" href="/admin/export.json?{ha(urlencode({'token': token}))}">Экспорт JSON</a>
            </div>
            <form method="post" action="/admin/backup/create" style="margin-top:10px">
              <input type="hidden" name="token" value="{ha(token)}">
              <button type="submit">Создать snapshot</button>
            </form>
            <ul class="backup-list">{backup_items}</ul>
          </section>
          <section class="bento-card wide" data-animate style="--i:3">
            <div class="stats">
              <div class="stat"><b>{len(rows)}</b><span>ключей всего</span></div>
              <div class="stat"><b>{active_count}</b><span>активных</span></div>
              <div class="stat"><b>{device_total}</b><span>устройств</span></div>
            </div>
            <h2>Ключи</h2>
            <p>Список не обрезается: скролльте внутри блока, нажмите на ключ для копирования.</p>
            <div class="keys-shell">
              <div class="keys-list">{rows_html}</div>
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
    return RedirectResponse(url=admin_url(token, created=created), status_code=303)


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
    return RedirectResponse(url=admin_url(token), status_code=303)


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
    return RedirectResponse(url=admin_url(token), status_code=303)

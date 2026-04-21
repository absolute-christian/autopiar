import hashlib
import json
import os
import platform
import socket
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


PRODUCT_ID = "autopiar"
APP_DATA_DIR_NAME = "AutoPiar"
LICENSE_CONFIG_FILE = "online_license.json"
DEVICE_ID_FILE = "device_id.txt"
EMBEDDED_LICENSE_SERVER_URL = "https://autopiar-production.up.railway.app"


@dataclass
class OnlineLicenseResult:
    ok: bool
    message: str
    payload: dict


def app_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        if base:
            path = Path(base) / APP_DATA_DIR_NAME
            path.mkdir(parents=True, exist_ok=True)
            return path
    path = Path.home() / ".autopiar"
    path.mkdir(parents=True, exist_ok=True)
    return path


def license_config_path() -> Path:
    return app_data_dir() / LICENSE_CONFIG_FILE


def load_license_config() -> dict:
    path = license_config_path()
    default_server_url = normalize_server_url(
        os.getenv("AUTOPIAR_DEFAULT_LICENSE_SERVER_URL", "").strip()
        or EMBEDDED_LICENSE_SERVER_URL
    )
    if not path.exists():
        return {
            "server_url": os.getenv("AUTOPIAR_LICENSE_SERVER_URL", "").strip() or default_server_url,
            "license_key": os.getenv("AUTOPIAR_LICENSE_KEY", "").strip(),
            "server_embedded": bool(default_server_url),
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    configured_server_url = os.getenv("AUTOPIAR_LICENSE_SERVER_URL", "").strip()
    if default_server_url:
        server_url = configured_server_url or default_server_url
    else:
        server_url = configured_server_url or data.get("server_url") or ""
    return {
        "server_url": str(server_url).strip(),
        "license_key": str(data.get("license_key") or os.getenv("AUTOPIAR_LICENSE_KEY", "")).strip(),
        "server_embedded": bool(default_server_url),
    }


def save_license_config(server_url: str, license_key: str) -> None:
    path = license_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "server_url": normalize_server_url(server_url),
        "license_key": license_key.strip(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_server_url(server_url: str) -> str:
    url = (server_url or "").strip().rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def get_device_id() -> str:
    path = app_data_dir() / DEVICE_ID_FILE
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except Exception:
        pass

    parts = [
        platform.system(),
        platform.release(),
        platform.machine(),
        platform.node() or socket.gethostname(),
        str(uuid.getnode()),
        os.environ.get("USERNAME") or os.environ.get("USER") or "",
        uuid.uuid4().hex,
    ]
    raw = "|".join(parts).encode("utf-8", errors="ignore")
    device_id = hashlib.sha256(raw).hexdigest()
    try:
        path.write_text(device_id, encoding="utf-8")
    except Exception:
        pass
    return device_id


def verify_online_license(
    server_url: str,
    license_key: str,
    product: str = PRODUCT_ID,
    timeout: int = 12,
) -> OnlineLicenseResult:
    server_url = normalize_server_url(server_url)
    license_key = (license_key or "").strip()
    if not server_url:
        return OnlineLicenseResult(False, "Не указан адрес сервера лицензий.", {})
    if not license_key:
        return OnlineLicenseResult(False, "Не указан лицензионный ключ.", {})

    endpoint = server_url + "/api/activate"
    body = json.dumps(
        {
            "license_key": license_key,
            "device_id": get_device_id(),
            "product": product,
            "hostname": platform.node() or socket.gethostname(),
            "platform": platform.platform(),
        },
        ensure_ascii=False,
    ).encode("utf-8")

    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw)
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8")
            data = json.loads(raw)
            message = str(data.get("detail") or data.get("message") or exc)
        except Exception:
            message = str(exc)
        return OnlineLicenseResult(False, message, {})
    except Exception as exc:
        return OnlineLicenseResult(False, f"Сервер лицензий недоступен: {exc}", {})

    ok = bool(data.get("ok"))
    message = str(data.get("message") or ("Лицензия активна." if ok else "Лицензия отклонена."))
    return OnlineLicenseResult(ok, message, data)


def require_cli_license() -> OnlineLicenseResult:
    config = load_license_config()
    server_url = config.get("server_url", "")
    license_key = config.get("license_key", "")

    if not server_url:
        server_url = input("Адрес сервера лицензий: ").strip()

    for attempt in range(3):
        if not license_key:
            license_key = input("Лицензионный ключ: ").strip()

        result = verify_online_license(server_url, license_key)
        if result.ok:
            save_license_config(server_url, license_key)
            return result

        print(f"Лицензия не прошла проверку: {result.message}")
        if attempt >= 2:
            return result

        retry = input("Ввести другой ключ? y/n [y]: ").strip().lower()
        if retry in {"n", "no", "нет"}:
            return result
        license_key = ""

    return result

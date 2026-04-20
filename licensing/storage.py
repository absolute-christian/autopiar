import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from licensing.crypto import extract_and_verify_document, load_public_key_from_b64
from licensing.model import LicensePayload


APP_DIR_NAME = "TelethonNeonSender"
LICENSE_FILE_NAME = "license.json"
STATE_FILE_NAME = "state.json"


@dataclass
class ValidationResult:
    ok: bool
    message: str
    payload: Optional[LicensePayload] = None


def get_runtime_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_license_path() -> Path:
    return get_runtime_dir() / LICENSE_FILE_NAME


def get_appdata_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        if base:
            p = Path(base) / APP_DIR_NAME
            p.mkdir(parents=True, exist_ok=True)
            return p
    p = Path.home() / f".{APP_DIR_NAME}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_state_path() -> Path:
    return get_appdata_dir() / STATE_FILE_NAME


def save_license_from_file(src_path: str) -> Path:
    src = Path(src_path)
    if not src.exists():
        raise FileNotFoundError(src_path)
    dst = get_license_path()
    shutil.copy2(src, dst)
    return dst


def read_json_file(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Invalid JSON file: {path}") from exc


def load_license_document(path: Optional[Path] = None) -> dict:
    lp = path or get_license_path()
    if not lp.exists():
        raise FileNotFoundError(str(lp))
    return read_json_file(lp)


def load_last_ok_date() -> Optional[date]:
    state_path = get_state_path()
    if not state_path.exists():
        return None
    try:
        data = read_json_file(state_path)
        raw = data.get("last_ok_date")
        if not raw:
            return None
        return date.fromisoformat(str(raw))
    except Exception:
        return None


def save_last_ok_date(today: date) -> None:
    state_path = get_state_path()
    payload = {"last_ok_date": today.isoformat()}
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_current_license(
    public_key_b64: str,
    expected_product: str,
    today: Optional[date] = None,
    license_path: Optional[Path] = None,
) -> ValidationResult:
    today = today or date.today()

    if not public_key_b64 or "REPLACE_WITH_" in public_key_b64:
        return ValidationResult(False, "Public key is not configured in app.")

    try:
        document = load_license_document(license_path)
    except FileNotFoundError:
        return ValidationResult(False, "License file not found.")
    except Exception as exc:
        return ValidationResult(False, str(exc))

    try:
        pub = load_public_key_from_b64(public_key_b64)
    except Exception as exc:
        return ValidationResult(False, f"Invalid embedded public key: {exc}")

    ok_sig, payload_bytes = extract_and_verify_document(document, pub)
    if not ok_sig:
        return ValidationResult(False, "License signature is invalid.")

    try:
        payload_data = json.loads(payload_bytes.decode("utf-8"))
        payload = LicensePayload.from_dict(payload_data)
    except Exception as exc:
        return ValidationResult(False, f"Invalid license payload: {exc}")

    if payload.product != expected_product:
        return ValidationResult(False, "License product mismatch.")

    if payload.is_expired(today):
        return ValidationResult(False, f"License expired on {payload.expires_date.isoformat()}.")

    last_ok = load_last_ok_date()
    if last_ok and today < last_ok:
        return ValidationResult(
            False,
            f"Clock rollback detected (today={today.isoformat()} < last_ok_date={last_ok.isoformat()}).",
        )

    save_last_ok_date(today)
    return ValidationResult(True, "License is valid.", payload=payload)


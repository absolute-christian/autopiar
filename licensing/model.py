from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional


@dataclass(frozen=True)
class LicensePayload:
    product: str
    license_to: str
    issued_at: str
    expires: str
    type: str
    hwid: Optional[str] = None

    @property
    def issued_date(self) -> date:
        return _parse_iso_date(self.issued_at, "issued_at")

    @property
    def expires_date(self) -> date:
        return _parse_iso_date(self.expires, "expires")

    @classmethod
    def from_dict(cls, data: dict) -> "LicensePayload":
        required = ("product", "license_to", "issued_at", "expires", "type")
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"Missing license payload field(s): {', '.join(missing)}")

        license_type = str(data["type"]).strip().lower()
        if license_type not in {"user", "dev"}:
            raise ValueError("License type must be 'user' or 'dev'.")

        payload = cls(
            product=str(data["product"]).strip(),
            license_to=str(data["license_to"]).strip(),
            issued_at=str(data["issued_at"]).strip(),
            expires=str(data["expires"]).strip(),
            type=license_type,
            hwid=str(data["hwid"]).strip() if data.get("hwid") else None,
        )
        if not payload.product:
            raise ValueError("Field 'product' must not be empty.")
        if not payload.license_to:
            raise ValueError("Field 'license_to' must not be empty.")
        _ = payload.issued_date
        _ = payload.expires_date
        return payload

    def is_expired(self, today: date) -> bool:
        return today > self.expires_date


def _parse_iso_date(value: str, field_name: str) -> date:
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        try:
            return date.fromisoformat(value)
        except Exception as exc:
            raise ValueError(f"Field '{field_name}' must be ISO date.") from exc


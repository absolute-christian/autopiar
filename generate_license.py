import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from licensing.crypto import build_signed_license_document, load_private_key_from_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate signed license.json")
    parser.add_argument("--to", dest="license_to", required=True, help="License owner (username/name/id)")
    parser.add_argument("--days", type=int, required=True, help="License duration in days")
    parser.add_argument("--type", dest="license_type", choices=["user", "dev"], default="user")
    parser.add_argument("--product", default="telethon_neon_sender")
    parser.add_argument("--key", default="private.key", help="Path to Ed25519 private key")
    parser.add_argument("--out", default="license.json", help="Output license file")
    args = parser.parse_args()

    if args.days <= 0:
        raise SystemExit("--days must be > 0")

    key_path = Path(args.key)
    if not key_path.exists():
        raise SystemExit(f"Private key not found: {key_path}")

    issued = date.today()
    expires = issued + timedelta(days=args.days)

    payload = {
        "product": args.product,
        "license_to": args.license_to.strip(),
        "issued_at": issued.isoformat(),
        "expires": expires.isoformat(),
        "type": args.license_type,
    }

    private_key = load_private_key_from_file(str(key_path))
    document = build_signed_license_document(payload, private_key)

    out_path = Path(args.out)
    out_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"License created: {out_path.resolve()}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
